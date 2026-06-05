"""Flow 一键部署编排（Phase 4a）：specs 构建 → 预检 → manifest 渲染 → apply（决策 12）。

将 FlowDeployment 翻译为 K8s 资源（决策 3.1 重写为 Flow 级模型 A）：
- 每个 Block 一个常驻 invoke Deployment + Service（暴露 /invoke，被 Flow 编排按 DAG 调用）；
- 触发方式为 mq/both 的已发布接口各渲染一个 Flow-Consumer Deployment + KEDA ScaledObject
  （按 flow.{api_id}.queue 深度扩缩）。
部署前做容量/GPU/scope 预检，不满足直接报 PYFLOW_K8S_DEPLOY_FAILED。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.k8s import cluster_monitor, deployment_manager, image_builder, keda_manager, middleware
from app.core.storage.minio_client import get_storage
from app.core.k8s.manifest_generator import (
    BlockDeploySpec,
    DeployContext,
    FlowConsumerSpec,
    capacity_precheck,
    deployment_name,
    gcp_scope_precheck,
    gpu_precheck,
    render_block_manifests,
    render_flow_consumer_manifests,
)
from app.errors import PYFLOW_K8S_DEPLOY_FAILED, BusinessException
from app.models.api_portal import PublishedApi
from app.models.block import Block
from app.models.deployment import FlowDeployment
from app.models.flow import FlowEdge, FlowNode
from app.models.platform_env import PlatformEnv
from app.models.version import BlockVersion
from app.observability.logging import get_logger
from sqlalchemy import select as _select

logger = get_logger("pyflow.k8s.orchestrator")
settings = get_settings()


def _build_context(deployment: FlowDeployment) -> DeployContext:
    return DeployContext(
        namespace=settings.k8s_namespace,
        resource_prefix=deployment.resource_prefix or f"flow-{deployment.flow_id[:8]}",
        runner_image=settings.runner_image,
        gpu_runner_image=settings.gpu_runner_image,
        ksa_default=settings.ksa_default,
        ksa_bigquery=settings.ksa_bigquery,
        ksa_storage=settings.ksa_storage,
        inject_middleware=settings.block_inject_middleware,
        middleware_secret=settings.block_middleware_secret if settings.block_inject_middleware else "",
        middleware_egress=middleware.build_egress_for_settings(settings) if settings.block_inject_middleware else [],
        minio_bucket=settings.minio_bucket,
        minio_secure=settings.minio_secure,
    )


async def load_global_env(session: AsyncSession) -> dict[str, str]:
    """加载平台级全局环境变量（注入所有部署的块）。"""
    rows = (await session.execute(_select(PlatformEnv))).scalars().all()
    return {r.env_key: r.env_value for r in rows}


def merge_env_into_specs(
    specs: list[BlockDeploySpec],
    *,
    global_env: dict[str, str],
    deployment_env: dict[str, str],
    deployment_secret_refs: dict[str, str],
) -> None:
    """env 优先级：全局 < 部署 < 块（更具体者覆盖）；secret_refs 同理。"""
    for spec in specs:
        spec.env_vars = {**global_env, **(deployment_env or {}), **(spec.env_vars or {})}
        spec.secret_refs = {**(deployment_secret_refs or {}), **(spec.secret_refs or {})}


# 允许部署级覆盖的 compute_config 资源键（其余键不受部署级覆盖影响）
RESOURCE_OVERRIDE_KEYS = (
    "cpu_request",
    "memory_request",
    "cpu_limit",
    "memory_limit",
    "gpu_enabled",
    "gpu_count",
    "gpu_type",
    "cuda_version",
)


def merge_resource_overrides_into_specs(
    specs: list[BlockDeploySpec], resource_overrides: dict[str, dict] | None
) -> None:
    """将部署级 Pod 资源覆盖合并进各 Block 的 compute_config（仅作用于该部署）。

    覆盖优先级：块默认 compute_config < 部署级 resource_overrides[block_id]；
    仅合并 RESOURCE_OVERRIDE_KEYS 中的非空键，避免误清空块自带配置。
    """
    if not resource_overrides:
        return
    for spec in specs:
        override = resource_overrides.get(spec.block_id)
        if not override:
            continue
        merged = dict(spec.compute_config or {})
        for key in RESOURCE_OVERRIDE_KEYS:
            if key in override and override[key] not in (None, ""):
                merged[key] = override[key]
        spec.compute_config = merged


async def build_specs(session: AsyncSession, flow_id: str) -> list[BlockDeploySpec]:
    """从 Flow 节点 + Block + 稳定版本派生部署描述。"""
    nodes = (await session.execute(
        select(FlowNode).where(FlowNode.flow_id == flow_id, FlowNode.node_type == "block")
    )).scalars().all()

    specs: list[BlockDeploySpec] = []
    seen: set[str] = set()
    for node in nodes:
        if not node.block_id or node.block_id in seen:
            continue
        seen.add(node.block_id)
        block = await session.get(Block, node.block_id)
        if block is None:
            continue
        code_path = ""
        version_id = block.stable_version_id or ""
        if version_id:
            bv = await session.get(BlockVersion, version_id)
            if bv is not None:
                code_path = bv.code_path
        specs.append(BlockDeploySpec(
            block_id=block.id,
            name=block.name,
            type=block.type,
            compute_config=block.compute_config or {},
            env_vars=block.env_vars or {},
            secret_refs=block.secret_refs or {},
            gcp_resource_scope=block.gcp_resource_scope or [],
            requirements_hash=block.requirements_hash or "",
            version_id=version_id,
            code_path=code_path,
        ))
    return specs


async def build_deployment_specs(
    session: AsyncSession, deployment: FlowDeployment
) -> list[BlockDeploySpec]:
    """构建部署描述并合并 全局/部署级 环境变量 + Pod 资源覆盖（统一入口）。"""
    specs = await build_specs(session, deployment.flow_id)
    global_env = await load_global_env(session)
    merge_env_into_specs(
        specs,
        global_env=global_env,
        deployment_env=deployment.env_vars or {},
        deployment_secret_refs=deployment.secret_refs or {},
    )
    merge_resource_overrides_into_specs(specs, deployment.resource_overrides or {})
    return specs


def effective_resources(compute_config: dict[str, Any]) -> dict[str, Any]:
    """返回 compute_config 生效后的资源规格（含默认值），供前端展示当前 Pod 配置。"""
    return {
        "cpu_request": compute_config.get("cpu_request", "100m"),
        "memory_request": compute_config.get("memory_request", "256Mi"),
        "cpu_limit": compute_config.get("cpu_limit", "1000m"),
        "memory_limit": compute_config.get("memory_limit", "1Gi"),
        "gpu_enabled": bool(compute_config.get("gpu_enabled", False)),
        "gpu_count": int(compute_config.get("gpu_count", 1)),
        "gpu_type": compute_config.get("gpu_type", "nvidia-tesla-t4"),
    }


async def list_block_resources(
    session: AsyncSession, deployment: FlowDeployment
) -> list[dict[str, Any]]:
    """列出该部署各 Block 的 Pod 资源信息：块默认值 + 部署级覆盖 + 生效值。"""
    specs = await build_specs(session, deployment.flow_id)
    overrides = deployment.resource_overrides or {}
    rows: list[dict[str, Any]] = []
    for spec in specs:
        override = overrides.get(spec.block_id) or {}
        merged = dict(spec.compute_config or {})
        for key in RESOURCE_OVERRIDE_KEYS:
            if key in override and override[key] not in (None, ""):
                merged[key] = override[key]
        rows.append({
            "block_id": spec.block_id,
            "name": spec.name,
            "default": effective_resources(spec.compute_config or {}),
            "override": override,
            "effective": effective_resources(merged),
        })
    return rows


async def _resolve_images(specs: list[BlockDeploySpec]) -> None:
    """为每个 spec 解析依赖层镜像（命中缓存复用，否则触发 Cloud Build；dev 用基础镜像）。"""
    storage = get_storage()
    cache: dict[str, str] = {}
    for spec in specs:
        if not spec.requirements_hash:
            continue
        cuda = str(spec.compute_config.get("cuda_version", "12.4"))
        cache_key = f"{spec.gpu_enabled}:{cuda}:{spec.requirements_hash}"
        if cache_key in cache:
            spec.image = cache[cache_key]
            continue
        req_text = ""
        # 依赖清单存于版本对象（requirements_path）；缺失则空（构建用 base）
        try:
            if spec.code_path:
                req_key = spec.code_path.rsplit("/", 1)[0] + "/requirements.txt"
                if await storage.exists(req_key):
                    req_text = (await storage.get(req_key)).decode("utf-8")
        except Exception as exc:  # noqa: BLE001 拉取依赖清单失败不阻断（用 base 镜像）
            logger.warning("requirements_fetch_failed", block_id=spec.block_id, error=str(exc))
        try:
            spec.image = await image_builder.ensure_dependency_image(
                req_text, spec.requirements_hash, gpu=spec.gpu_enabled, cuda_version=cuda
            )
            cache[cache_key] = spec.image
        except BusinessException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("image_resolve_failed", block_id=spec.block_id, error=str(exc))


def run_prechecks(specs: list[BlockDeploySpec]) -> dict[str, Any]:
    """容量 + GPU + scope 预检；返回结构化结果，失败汇总。"""
    cap = capacity_precheck(
        specs,
        pool_cpu_cores=settings.workers_pool_cpu_cores,
        pool_mem_mib=settings.workers_pool_mem_mib,
    )
    allowed_gpu = [t.strip() for t in settings.gpu_allowed_types.split(",") if t.strip()]
    cuda_matrix = dict(
        pair.split(":", 1) for pair in settings.gpu_cuda_matrix.split(",") if ":" in pair
    )
    authorized_scopes = [s.strip() for s in settings.gcp_authorized_scopes.split(",") if s.strip()]

    issues: list[dict[str, Any]] = []
    if not cap.ok:
        issues.append({"kind": "capacity", "reason": cap.reason, "detail": cap.detail})
    for spec in specs:
        g = gpu_precheck(
            spec, allowed_types=allowed_gpu, cuda_matrix=cuda_matrix,
            quota_enabled=settings.gpu_quota_enabled,
        )
        if not g.ok:
            issues.append({"kind": "gpu", "block_id": spec.block_id, "reason": g.reason})
        sc = gcp_scope_precheck(spec, authorized_scopes=authorized_scopes)
        if not sc.ok:
            issues.append({"kind": "gcp_scope", "block_id": spec.block_id, "reason": sc.reason})

    return {"ok": not issues, "issues": issues, "capacity": cap.detail}


async def build_flow_consumer_specs(
    session: AsyncSession,
    deployment: FlowDeployment,
    ctx: DeployContext,
    block_specs: list[BlockDeploySpec],
) -> list[FlowConsumerSpec]:
    """为该 Flow 上触发方式为 mq/both 的已发布接口构建 Flow-Consumer 部署描述（决策 3.1）。

    DAG 快照内嵌每个块节点的 invoke Service 名，供 runner flow_consumer 角色按 DAG 调用。
    """
    flow_id = deployment.flow_id
    # 接口的「有效流程」= active_flow_id or flow_id（与调用/消费路径一致）；
    # 兼容历史数据 active_flow_id 为空的行，避免漏建消费者。
    apis = (await session.execute(
        select(PublishedApi).where(
            PublishedApi.trigger_type.in_(["mq", "both"]),
            or_(
                PublishedApi.active_flow_id == flow_id,
                and_(PublishedApi.active_flow_id.is_(None), PublishedApi.flow_id == flow_id),
            ),
        )
    )).scalars().all()
    if not apis:
        return []

    nodes = (await session.execute(
        select(FlowNode).where(FlowNode.flow_id == flow_id)
    )).scalars().all()
    edges = (await session.execute(
        select(FlowEdge).where(FlowEdge.flow_id == flow_id)
    )).scalars().all()

    # 块节点 → invoke Service 名（与 render_block_manifests 一致）
    block_service = {bs.block_id: deployment_name(ctx, bs) for bs in block_specs}
    dag_nodes = [
        {
            "id": n.id, "node_type": n.node_type, "block_id": n.block_id,
            "config": n.config, "position": n.position,
            "service": block_service.get(n.block_id) if n.block_id else None,
        }
        for n in nodes
    ]
    dag_edges = [
        {
            "id": e.id, "source_node_id": e.source_node_id, "target_node_id": e.target_node_id,
            "source_port": e.source_port, "target_port": e.target_port,
        }
        for e in edges
    ]
    dag = {"nodes": dag_nodes, "edges": dag_edges}

    global_env = await load_global_env(session)
    consumer_env = {**global_env, **(deployment.env_vars or {})}

    specs: list[FlowConsumerSpec] = []
    for api in apis:
        specs.append(FlowConsumerSpec(
            api_id=api.id,
            api_name=api.name,
            flow_id=flow_id,
            mq_config=api.mq_config or {},
            dag=dag,
            compute_config={},
            env_vars=consumer_env,
            image=ctx.runner_image,
        ))
    return specs


def render_all_manifests(
    specs: list[BlockDeploySpec],
    ctx: DeployContext,
    *,
    keda_enabled: bool = True,
    flow_consumer_specs: list[FlowConsumerSpec] | None = None,
) -> list[dict[str, Any]]:
    """渲染全部 manifest：中间件连接 Secret + KEDA 鉴权（各一次）+ 各 Block invoke 资源
    + 各接口 Flow-Consumer Deployment/ScaledObject（决策 3.1 重写为 Flow 级模型 A）。

    keda_enabled=False（集群未装 KEDA）时跳过 KEDA 鉴权 + ScaledObject，Flow-Consumer 退化为固定副本。
    """
    flow_consumer_specs = flow_consumer_specs or []
    manifests: list[dict[str, Any]] = []
    # 共享中间件连接 Secret（让块/消费者连 redis/mq/db/minio）
    if ctx.inject_middleware and ctx.middleware_secret:
        manifests.append(middleware.build_middleware_secret(settings, ctx.namespace))
    # 仅当存在 MQ 触发接口时才需要 KEDA RabbitMQ 鉴权
    if keda_enabled and flow_consumer_specs:
        manifests.extend(keda_manager.build_rabbitmq_auth_manifests(ctx.namespace))
    # 块：一律 invoke Service
    for spec in specs:
        manifests.extend(render_block_manifests(spec, ctx, keda_enabled=keda_enabled))
    # 接口级 Flow-Consumer（KEDA 按 flow.{api_id}.queue 扩缩）
    for fc in flow_consumer_specs:
        max_replica = max(1, min(settings.keda_max_replica_cap, 20))
        manifests.extend(render_flow_consumer_manifests(
            fc, ctx, max_replica=max_replica,
            msgs_per_replica=settings.keda_msgs_per_replica, keda_enabled=keda_enabled,
        ))
    return manifests


async def deploy(session: AsyncSession, deployment: FlowDeployment) -> dict[str, Any]:
    """执行一键部署。"""
    from app.observability.metrics import K8S_DEPLOY

    specs = await build_deployment_specs(session, deployment)
    if not specs:
        raise BusinessException(PYFLOW_K8S_DEPLOY_FAILED, "no deployable blocks in flow")

    precheck = run_prechecks(specs)
    if not precheck["ok"]:
        K8S_DEPLOY.labels(action="deploy", result="precheck_failed").inc()
        raise BusinessException(
            PYFLOW_K8S_DEPLOY_FAILED, f"precheck failed: {precheck['issues']}"
        )

    ctx = _build_context(deployment)

    # 镜像分层：按 requirements_hash 复用/构建依赖层（决策 11，4b）
    await _resolve_images(specs)

    # 接口级 Flow-Consumer（trigger_type ∈ {mq,both} 的已发布接口）
    flow_consumer_specs = await build_flow_consumer_specs(session, deployment, ctx, specs)

    # 集群未装 KEDA 时优雅降级：跳过 ScaledObject，Flow-Consumer 退化为固定副本
    keda_ok = await deployment_manager.keda_available()
    warnings: list[str] = []
    if not keda_ok and flow_consumer_specs:
        warnings.append(
            "集群未安装 KEDA：Flow-Consumer 以固定副本(min=1)运行，未启用基于队列深度的自动扩缩。"
            "安装 KEDA 后重新部署即可恢复弹性伸缩。"
        )

    manifests = render_all_manifests(
        specs, ctx, keda_enabled=keda_ok, flow_consumer_specs=flow_consumer_specs
    )

    deployment.status = "deploying"
    await session.commit()

    try:
        await deployment_manager.apply_manifests(manifests, ctx.namespace)
    except BusinessException:
        deployment.status = "stopped"
        await session.commit()
        K8S_DEPLOY.labels(action="deploy", result="apply_failed").inc()
        raise

    block_statuses = await cluster_monitor.collect_deployment_status(
        specs, ctx, flow_consumer_specs
    )
    deployment.status = cluster_monitor.aggregate_status(block_statuses)
    deployment.block_statuses = block_statuses
    await session.commit()
    K8S_DEPLOY.labels(action="deploy", result="ok").inc()
    logger.info("flow_deployed", deployment_id=deployment.id, blocks=len(specs), keda=keda_ok)
    return {"status": deployment.status, "block_statuses": block_statuses, "warnings": warnings}


async def destroy(session: AsyncSession, deployment: FlowDeployment) -> dict[str, Any]:
    """销毁部署：删除全部 K8s 资源。"""
    from app.observability.metrics import K8S_DEPLOY

    specs = await build_deployment_specs(session, deployment)
    ctx = _build_context(deployment)
    flow_consumer_specs = await build_flow_consumer_specs(session, deployment, ctx, specs)
    manifests = render_all_manifests(specs, ctx, flow_consumer_specs=flow_consumer_specs)
    await deployment_manager.delete_manifests(manifests, ctx.namespace)
    deployment.status = "stopped"
    deployment.block_statuses = []
    await session.commit()
    K8S_DEPLOY.labels(action="destroy", result="ok").inc()
    return {"status": "stopped"}


async def status(session: AsyncSession, deployment: FlowDeployment) -> dict[str, Any]:
    specs = await build_specs(session, deployment.flow_id)
    ctx = _build_context(deployment)
    flow_consumer_specs = await build_flow_consumer_specs(session, deployment, ctx, specs)
    block_statuses = await cluster_monitor.collect_deployment_status(
        specs, ctx, flow_consumer_specs
    )
    agg = cluster_monitor.aggregate_status(block_statuses)
    deployment.status = agg
    deployment.block_statuses = block_statuses
    await session.commit()
    return {"status": agg, "block_statuses": block_statuses}
