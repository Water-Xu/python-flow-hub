"""Flow 一键部署编排（Phase 4a）：specs 构建 → 预检 → manifest 渲染 → apply（决策 12）。

将 FlowDeployment 翻译为 K8s 资源：每个 Block 一个常驻 Deployment（自消费 MQ / 暴露 /invoke），
async 块附 KEDA ScaledObject；部署前做容量/GPU/scope 预检，不满足直接报 PYFLOW_K8S_DEPLOY_FAILED。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.k8s import cluster_monitor, deployment_manager, image_builder, keda_manager
from app.core.storage.minio_client import get_storage
from app.core.k8s.manifest_generator import (
    BlockDeploySpec,
    DeployContext,
    capacity_precheck,
    derive_max_replica,
    gcp_scope_precheck,
    gpu_precheck,
    render_block_manifests,
)
from app.errors import PYFLOW_K8S_DEPLOY_FAILED, BusinessException
from app.models.block import Block
from app.models.deployment import FlowDeployment
from app.models.flow import FlowNode
from app.models.version import BlockVersion
from app.observability.logging import get_logger

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
    )


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
            execution_mode=block.execution_mode,
            compute_config=block.compute_config or {},
            mq_config=block.mq_config or {},
            env_vars=block.env_vars or {},
            secret_refs=block.secret_refs or {},
            gcp_resource_scope=block.gcp_resource_scope or [],
            requirements_hash=block.requirements_hash or "",
            version_id=version_id,
            code_path=code_path,
        ))
    return specs


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


def render_all_manifests(specs: list[BlockDeploySpec], ctx: DeployContext) -> list[dict[str, Any]]:
    """渲染全部 manifest：KEDA 鉴权（一次）+ 各 Block 资源。"""
    manifests: list[dict[str, Any]] = []
    if any(s.consumes_mq for s in specs):
        manifests.extend(keda_manager.build_rabbitmq_auth_manifests(ctx.namespace))
    for spec in specs:
        max_replica = derive_max_replica(
            spec, pool_cpu_cores=settings.workers_pool_cpu_cores, cap=settings.keda_max_replica_cap
        )
        manifests.extend(render_block_manifests(
            spec, ctx, max_replica=max_replica, msgs_per_replica=settings.keda_msgs_per_replica
        ))
    return manifests


async def deploy(session: AsyncSession, deployment: FlowDeployment) -> dict[str, Any]:
    """执行一键部署。"""
    from app.observability.metrics import K8S_DEPLOY

    specs = await build_specs(session, deployment.flow_id)
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

    manifests = render_all_manifests(specs, ctx)

    deployment.status = "deploying"
    await session.commit()

    try:
        await deployment_manager.apply_manifests(manifests, ctx.namespace)
    except BusinessException:
        deployment.status = "stopped"
        await session.commit()
        K8S_DEPLOY.labels(action="deploy", result="apply_failed").inc()
        raise

    block_statuses = await cluster_monitor.collect_deployment_status(specs, ctx)
    deployment.status = cluster_monitor.aggregate_status(block_statuses)
    deployment.block_statuses = block_statuses
    await session.commit()
    K8S_DEPLOY.labels(action="deploy", result="ok").inc()
    logger.info("flow_deployed", deployment_id=deployment.id, blocks=len(specs))
    return {"status": deployment.status, "block_statuses": block_statuses}


async def destroy(session: AsyncSession, deployment: FlowDeployment) -> dict[str, Any]:
    """销毁部署：删除全部 K8s 资源。"""
    from app.observability.metrics import K8S_DEPLOY

    specs = await build_specs(session, deployment.flow_id)
    ctx = _build_context(deployment)
    manifests = render_all_manifests(specs, ctx)
    await deployment_manager.delete_manifests(manifests, ctx.namespace)
    deployment.status = "stopped"
    deployment.block_statuses = []
    await session.commit()
    K8S_DEPLOY.labels(action="destroy", result="ok").inc()
    return {"status": "stopped"}


async def status(session: AsyncSession, deployment: FlowDeployment) -> dict[str, Any]:
    specs = await build_specs(session, deployment.flow_id)
    ctx = _build_context(deployment)
    block_statuses = await cluster_monitor.collect_deployment_status(specs, ctx)
    agg = cluster_monitor.aggregate_status(block_statuses)
    deployment.status = agg
    deployment.block_statuses = block_statuses
    await session.commit()
    return {"status": agg, "block_statuses": block_statuses}
