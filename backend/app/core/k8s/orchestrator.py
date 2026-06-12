"""Flow 一键部署编排（Phase 4a）：specs 构建 → 预检 → manifest 渲染 → apply（决策 12）。

将 FlowDeployment 翻译为 K8s 资源（决策 3.1 重写为 Flow 级模型 A）：
- 每个 Block 一个常驻 invoke Deployment + Service（暴露 /invoke，被 Flow 编排按 DAG 调用）；
- 触发方式为 mq/both 的已发布接口各渲染一个 Flow-Consumer Deployment + KEDA ScaledObject
  （按 flow.{api_id}.queue 深度扩缩）。
部署前做容量/GPU/scope 预检，不满足直接报 PYFLOW_K8S_DEPLOY_FAILED。
"""

from __future__ import annotations

import re
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
    FlowRunnerSpec,
    capacity_precheck,
    deployment_name,
    derive_max_replica,
    flow_runner_name,
    gcp_scope_precheck,
    gpu_precheck,
    parse_cpu_millicores,
    parse_mem_mib,
    render_block_manifests,
    render_flow_consumer_manifests,
    render_flow_runner_manifests,
)
from app.errors import PYFLOW_K8S_DEPLOY_FAILED, BusinessException
from app.models.api_portal import PublishedApi
from app.models.block import Block
from app.models.deployment import FlowDeployment
from app.models.flow import Flow, FlowEdge, FlowNode
from app.models.platform_env import PlatformEnv
from app.models.version import BlockVersion
from app.observability.logging import get_logger
from sqlalchemy import select as _select

logger = get_logger("pyflow.k8s.orchestrator")
settings = get_settings()


FLOW_RUNNER_RESOURCE_KEY = "__flow__"

# flow_mode 整流 Pod 的默认资源（单 Pod 承载所有块，默认比单块要大）
_FLOW_RUNNER_DEFAULT_COMPUTE: dict[str, Any] = {
    "cpu_request": "200m",
    "memory_request": "512Mi",
    "cpu_limit": "2000m",
    "memory_limit": "4Gi",
}


def _sanitize_k8s_prefix(raw: str) -> str:
    """确保 resource_prefix 只含 K8s 合法字符（[a-z0-9-]），过滤中文/特殊字符。"""
    s = re.sub(r"[^a-z0-9]+", "-", raw.lower())
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:52] if s else ""


def _build_context(deployment: FlowDeployment) -> DeployContext:
    raw_prefix = deployment.resource_prefix or f"flow-{deployment.flow_id[:8]}"
    safe_prefix = _sanitize_k8s_prefix(raw_prefix)
    # 如果清洗后为空（极端情况），fallback 到纯 ID
    if not safe_prefix:
        safe_prefix = f"flow-{deployment.flow_id[:12]}"
    return DeployContext(
        namespace=settings.k8s_namespace,
        resource_prefix=safe_prefix,
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
        requirements_path = ""
        version_id = block.stable_version_id or ""
        if version_id:
            bv = await session.get(BlockVersion, version_id)
            if bv is not None:
                code_path = bv.code_path
                requirements_path = bv.requirements_path or ""
        specs.append(BlockDeploySpec(
            block_id=block.id,
            name=block.name,
            type=block.type,
            compute_config=block.compute_config or {},
            env_vars=block.env_vars or {},
            secret_refs=block.secret_refs or {},
            gcp_resource_scope=block.gcp_resource_scope or [],
            requirements_hash=block.requirements_hash or "",
            requirements_path=requirements_path or "",
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


def list_flow_runner_resource(deployment: FlowDeployment) -> list[dict[str, Any]]:
    """flow_mode：返回整流 Pod 的单一资源配置行（与 list_block_resources 结构一致）。

    resource_overrides 中使用键 "__flow__" 存储整流 Pod 的资源配置，与 block_mode 的
    block_id 键对称，由前端统一的 PUT /resources 接口保存，下次部署生效。
    """
    overrides = deployment.resource_overrides or {}
    override = overrides.get(FLOW_RUNNER_RESOURCE_KEY, {})
    default_config = dict(_FLOW_RUNNER_DEFAULT_COMPUTE)
    merged = dict(default_config)
    for key in RESOURCE_OVERRIDE_KEYS:
        if key in override and override[key] not in (None, ""):
            merged[key] = override[key]
    return [{
        "block_id": FLOW_RUNNER_RESOURCE_KEY,
        "name": "Flow 整体 Pod（FlowRunner）",
        "default": effective_resources(default_config),
        "override": override,
        "effective": effective_resources(merged),
    }]


def flow_runner_resource_summary(deployment: FlowDeployment) -> dict[str, Any]:
    """flow_mode 的 Flow 资源汇总：整流单 Pod 请求/上限 + 节点池占用 + KEDA 峰值。

    与 flow_resource_summary（block_mode）结构完全一致，前端同一套模板渲染。
    is_flow_mode=True 供前端调整描述文案。
    """
    overrides = deployment.resource_overrides or {}
    override = overrides.get(FLOW_RUNNER_RESOURCE_KEY, {})
    merged = dict(_FLOW_RUNNER_DEFAULT_COMPUTE)
    for key in RESOURCE_OVERRIDE_KEYS:
        if key in override and override[key] not in (None, ""):
            merged[key] = override[key]

    pool_cpu_cores = settings.workers_pool_cpu_cores
    pool_mem_mib = settings.workers_pool_mem_mib
    pool_cpu_m = int(pool_cpu_cores * 1000)

    req_cpu_m = parse_cpu_millicores(merged.get("cpu_request", "200m"), 200)
    req_mem_mib = parse_mem_mib(merged.get("memory_request", "512Mi"), 512)
    lim_cpu_m = parse_cpu_millicores(merged.get("cpu_limit", "2000m"), 2000)
    lim_mem_mib = parse_mem_mib(merged.get("memory_limit", "4Gi"), 4096)
    max_rep = max(1, min(
        int((pool_cpu_cores * 1000) // max(lim_cpu_m, 1)),
        settings.keda_max_replica_cap,
    ))
    gpu_enabled = bool(merged.get("gpu_enabled", False))
    capacity_ok = req_cpu_m <= pool_cpu_m and req_mem_mib <= pool_mem_mib

    return {
        "block_count": 1,
        "is_flow_mode": True,
        "pool": {"name": "pyflow-workers", "cpu_m": pool_cpu_m, "mem_mib": pool_mem_mib},
        "resident": {"cpu_m": req_cpu_m, "mem_mib": req_mem_mib},
        "limit": {"cpu_m": lim_cpu_m, "mem_mib": lim_mem_mib},
        "keda_peak": {"cpu_m": lim_cpu_m * max_rep, "mem_mib": lim_mem_mib * max_rep},
        "gpu": {
            "total": int(merged.get("gpu_count", 1)) if gpu_enabled else 0,
            "block_count": 1 if gpu_enabled else 0,
        },
        "usage": {
            "cpu_pct": round(req_cpu_m / pool_cpu_m * 100, 1) if pool_cpu_m else 0,
            "mem_pct": round(req_mem_mib / pool_mem_mib * 100, 1) if pool_mem_mib else 0,
        },
        "capacity_ok": capacity_ok,
        "capacity_reason": "" if capacity_ok else "FlowRunner 资源请求超出 pyflow-workers 节点池可分配容量",
        "blocks": [{
            "block_id": FLOW_RUNNER_RESOURCE_KEY,
            "name": "Flow 整体 Pod（FlowRunner）",
            "gpu_enabled": gpu_enabled,
            "request": {"cpu_m": req_cpu_m, "mem_mib": req_mem_mib},
            "limit": {"cpu_m": lim_cpu_m, "mem_mib": lim_mem_mib},
            "max_replica": max_rep,
        }],
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


async def flow_resource_summary(
    session: AsyncSession, deployment: FlowDeployment
) -> dict[str, Any]:
    """Flow 维度资源汇总（决策 12）：各块均为独立 Pod，这里把它们的请求/上限累加，
    对照 pyflow-workers 节点池可分配容量给出占用率与容量预检；并估算 KEDA 峰值上限。

    注：块（invoke Service）为常驻副本（min≥1），按 request 计常驻占用；KEDA 实际作用于
    每条 MQ 接口的 Flow-Consumer（0→N 按队列扩缩），其峰值由各块 limit×maxReplica 估算上界。
    """
    specs = await build_specs(session, deployment.flow_id)
    merge_resource_overrides_into_specs(specs, deployment.resource_overrides or {})

    pool_cpu_cores = settings.workers_pool_cpu_cores
    pool_mem_mib = settings.workers_pool_mem_mib
    pool_cpu_m = int(pool_cpu_cores * 1000)

    req_cpu_m = req_mem_mib = lim_cpu_m = lim_mib = 0
    peak_cpu_m = peak_mem_mib = 0
    gpu_total = gpu_blocks = 0
    blocks: list[dict[str, Any]] = []
    for s in specs:
        cc = s.compute_config or {}
        b_req_cpu = parse_cpu_millicores(cc.get("cpu_request", "100m"), 100)
        b_req_mem = parse_mem_mib(cc.get("memory_request", "256Mi"), 256)
        b_lim_cpu = parse_cpu_millicores(cc.get("cpu_limit", "1000m"), 1000)
        b_lim_mem = parse_mem_mib(cc.get("memory_limit", "1Gi"), 1024)
        max_rep = derive_max_replica(
            s, pool_cpu_cores=pool_cpu_cores, cap=settings.keda_max_replica_cap
        )
        req_cpu_m += b_req_cpu
        req_mem_mib += b_req_mem
        lim_cpu_m += b_lim_cpu
        lim_mib += b_lim_mem
        peak_cpu_m += b_lim_cpu * max_rep
        peak_mem_mib += b_lim_mem * max_rep
        if cc.get("gpu_enabled"):
            gpu_blocks += 1
            gpu_total += int(cc.get("gpu_count", 1))
        blocks.append({
            "block_id": s.block_id,
            "name": s.name,
            "gpu_enabled": bool(cc.get("gpu_enabled", False)),
            "request": {"cpu_m": b_req_cpu, "mem_mib": b_req_mem},
            "limit": {"cpu_m": b_lim_cpu, "mem_mib": b_lim_mem},
            "max_replica": max_rep,
        })

    cap = capacity_precheck(
        specs, pool_cpu_cores=pool_cpu_cores, pool_mem_mib=pool_mem_mib
    )
    return {
        "block_count": len(specs),
        "pool": {"name": "pyflow-workers", "cpu_m": pool_cpu_m, "mem_mib": pool_mem_mib},
        "resident": {"cpu_m": req_cpu_m, "mem_mib": req_mem_mib},
        "limit": {"cpu_m": lim_cpu_m, "mem_mib": lim_mib},
        "keda_peak": {"cpu_m": peak_cpu_m, "mem_mib": peak_mem_mib},
        "gpu": {"total": gpu_total, "block_count": gpu_blocks},
        "usage": {
            "cpu_pct": round(req_cpu_m / pool_cpu_m * 100, 1) if pool_cpu_m else 0,
            "mem_pct": round(req_mem_mib / pool_mem_mib * 100, 1) if pool_mem_mib else 0,
        },
        "capacity_ok": cap.ok,
        "capacity_reason": cap.reason,
        "blocks": blocks,
    }


async def _fetch_requirements_text(spec: BlockDeploySpec) -> str:
    """从 MinIO 拉取单个块的 requirements 文本；失败返回空串。"""
    storage = get_storage()
    req_key = spec.requirements_path
    if not req_key and spec.code_path:
        req_key = spec.code_path.rsplit("/", 1)[0] + "/requirements.txt"
    if not req_key:
        return ""
    try:
        if await storage.exists(req_key):
            return (await storage.get(req_key)).decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("requirements_fetch_failed", block_id=spec.block_id, error=str(exc))
    return ""


async def _resolve_images(specs: list[BlockDeploySpec]) -> None:
    """为每个 spec 解析依赖层镜像（命中缓存复用，否则触发 Cloud Build；dev 用基础镜像）。"""
    cache: dict[str, str] = {}
    for spec in specs:
        if not spec.requirements_hash:
            continue
        cuda = str(spec.compute_config.get("cuda_version", "12.4"))
        cache_key = f"{spec.gpu_enabled}:{cuda}:{spec.requirements_hash}"
        if cache_key in cache:
            spec.image = cache[cache_key]
            continue
        req_text = await _fetch_requirements_text(spec)
        if not req_text.strip():
            logger.warning(
                "requirements_empty_for_hash",
                block_id=spec.block_id,
                requirements_hash=spec.requirements_hash,
            )
        try:
            spec.image = await image_builder.ensure_dependency_image(
                req_text, spec.requirements_hash, gpu=spec.gpu_enabled, cuda_version=cuda
            )
            cache[cache_key] = spec.image
        except BusinessException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("image_resolve_failed", block_id=spec.block_id, error=str(exc))


async def _resolve_flow_runner_image(specs: list[BlockDeploySpec]) -> str:
    """flow_mode 专用：合并所有块的 requirements 构建单一依赖镜像。

    各块的 requirements 行去重合并后计算统一 hash，复用已有镜像或触发 Cloud Build 构建；
    所有块均无 requirements 时直接返回基础镜像（无需构建）。
    """
    import hashlib

    merged_lines: list[str] = []
    seen_lines: set[str] = set()
    has_real_deps = False

    for spec in specs:
        req_text = await _fetch_requirements_text(spec)
        for line in req_text.splitlines():
            stripped = line.strip()
            if not stripped or stripped in seen_lines:
                continue
            seen_lines.add(stripped)
            merged_lines.append(stripped)
            if not stripped.startswith("#"):
                has_real_deps = True

    if not has_real_deps:
        return settings.runner_image

    merged_text = "\n".join(merged_lines) + "\n"
    combined_hash = hashlib.sha256(merged_text.encode("utf-8")).hexdigest()
    logger.info("flow_runner_image_resolving", combined_hash=combined_hash[:16], lines=len(merged_lines))
    try:
        image = await image_builder.ensure_dependency_image(merged_text, combined_hash)
        logger.info("flow_runner_image_resolved", image=image)
        return image
    except BusinessException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("flow_runner_image_resolve_failed", error=str(exc))
        return settings.runner_image


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
    仅在 block_mode 下使用；flow_mode 由 build_flow_runner_spec 统一处理。
    """
    flow_id = deployment.flow_id
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
    flow_obj = await session.get(Flow, flow_id)
    dag = {
        "nodes": dag_nodes,
        "edges": dag_edges,
        "entry_node_id": flow_obj.entry_node_id if flow_obj else None,
    }

    global_env = await load_global_env(session)
    consumer_env = {**global_env, **(deployment.env_vars or {})}

    specs: list[FlowConsumerSpec] = []
    for api in apis:
        # 将 API 级 entrypoint_map 嵌入 DAG 快照，runner flow_consumer 据此解析各节点入口
        api_dag = {
            **dag,
            "entrypoint_map": api.entrypoint_map or {},
            "entrypoint": api.entrypoint or None,
            "entry_node_id": api.entry_node_id or dag.get("entry_node_id"),
        }
        specs.append(FlowConsumerSpec(
            api_id=api.id,
            api_name=api.name,
            flow_id=flow_id,
            mq_config=api.mq_config or {},
            dag=api_dag,
            compute_config={},
            env_vars=consumer_env,
            image=ctx.runner_image,
        ))
    return specs


async def build_flow_runner_spec(
    session: AsyncSession,
    deployment: FlowDeployment,
    ctx: DeployContext,
    block_specs: list[BlockDeploySpec],
    *,
    image: str = "",
) -> FlowRunnerSpec:
    """构建 flow_mode 整流单 Pod 的部署描述（决策 flow_mode）。

    与 build_flow_consumer_specs 不同：
    - DAG 快照不含 service 字段（in-process 无需块 Service）；
    - mq_apis 包含该 Flow 上所有 MQ 接口（含 entry_node_id 和 entrypoint_map），
      由 flow_runner 在 Pod 内为每个接口独立消费；
    - block_specs 转换为 blocks 列表（仅 block_id + code_path，runner 拉取代码用）。
    """
    flow_id = deployment.flow_id
    nodes = (await session.execute(
        select(FlowNode).where(FlowNode.flow_id == flow_id)
    )).scalars().all()
    edges = (await session.execute(
        select(FlowEdge).where(FlowEdge.flow_id == flow_id)
    )).scalars().all()
    flow_obj = await session.get(Flow, flow_id)

    # DAG 快照（无 service 字段）
    dag_nodes = [
        {
            "id": n.id, "node_type": n.node_type, "block_id": n.block_id,
            "config": n.config, "position": n.position,
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
    dag = {
        "nodes": dag_nodes,
        "edges": dag_edges,
        "entry_node_id": flow_obj.entry_node_id if flow_obj else None,
    }

    # 块代码路径列表（runner 启动时逐一从 MinIO 拉取）
    blocks = [
        {"block_id": bs.block_id, "code_path": bs.code_path}
        for bs in block_specs
        if bs.code_path
    ]

    # MQ 触发接口列表（含接口级 entry_node_id 和 entrypoint_map，支持同 Flow 多入口）
    mq_apis_rows = (await session.execute(
        select(PublishedApi).where(
            PublishedApi.trigger_type.in_(["mq", "both"]),
            or_(
                PublishedApi.active_flow_id == flow_id,
                and_(PublishedApi.active_flow_id.is_(None), PublishedApi.flow_id == flow_id),
            ),
        )
    )).scalars().all()
    mq_apis = [
        {
            "api_id": api.id,
            "mq_config": api.mq_config or {},
            "entry_node_id": api.entry_node_id or (flow_obj.entry_node_id if flow_obj else None),
            "entrypoint_map": api.entrypoint_map or {},
            "entrypoint": api.entrypoint or None,
        }
        for api in mq_apis_rows
    ]

    global_env = await load_global_env(session)
    runner_env = {**global_env, **(deployment.env_vars or {})}

    # 应用部署级 Pod 资源覆盖（保存在 resource_overrides["__flow__"]，与 block_mode 逻辑对称）
    flow_override = (deployment.resource_overrides or {}).get(FLOW_RUNNER_RESOURCE_KEY, {})
    compute_config = dict(_FLOW_RUNNER_DEFAULT_COMPUTE)
    for key in RESOURCE_OVERRIDE_KEYS:
        if key in flow_override and flow_override[key] not in (None, ""):
            compute_config[key] = flow_override[key]

    return FlowRunnerSpec(
        flow_id=flow_id,
        flow_name=flow_obj.name if flow_obj else flow_id,
        blocks=blocks,
        dag=dag,
        mq_apis=mq_apis,
        compute_config=compute_config,
        env_vars=runner_env,
        image=image or ctx.runner_image,
    )


def render_all_manifests(
    specs: list[BlockDeploySpec],
    ctx: DeployContext,
    *,
    keda_enabled: bool = True,
    flow_consumer_specs: list[FlowConsumerSpec] | None = None,
    flow_runner_spec: FlowRunnerSpec | None = None,
) -> list[dict[str, Any]]:
    """渲染全部 manifest。

    - block_mode（默认）：中间件 Secret + KEDA 鉴权 + 各 Block invoke 资源
      + 各接口 Flow-Consumer Deployment/ScaledObject（决策 3.1 重写为 Flow 级模型 A）。
    - flow_mode（flow_runner_spec 非空）：中间件 Secret + KEDA 鉴权
      + 整流单 Pod FlowRunner Deployment/Service/NetworkPolicy/ScaledObject。
      block_mode 的块 Deployment/Service 不生成（所有块在 Pod 内 in-process 执行）。

    keda_enabled=False（集群未装 KEDA）时跳过 KEDA 鉴权 + ScaledObject，Flow-Consumer 退化为固定副本。
    """
    flow_consumer_specs = flow_consumer_specs or []
    manifests: list[dict[str, Any]] = []

    # 共享中间件连接 Secret
    if ctx.inject_middleware and ctx.middleware_secret:
        manifests.append(middleware.build_middleware_secret(settings, ctx.namespace))

    # flow_mode：整流单 Pod 路径（不生成块级资源）
    if flow_runner_spec is not None:
        has_mq = flow_runner_spec.has_mq
        if keda_enabled and has_mq:
            manifests.extend(keda_manager.build_rabbitmq_auth_manifests(ctx.namespace))
        max_replica = min(settings.keda_max_replica_cap, settings.keda_max_replica_cap)
        manifests.extend(render_flow_runner_manifests(
            flow_runner_spec, ctx,
            max_replica=max_replica,
            msgs_per_replica=settings.keda_msgs_per_replica,
            keda_enabled=keda_enabled,
        ))
        return manifests

    # block_mode：原有路径
    if keda_enabled and flow_consumer_specs:
        manifests.extend(keda_manager.build_rabbitmq_auth_manifests(ctx.namespace))
    for spec in specs:
        manifests.extend(render_block_manifests(spec, ctx, keda_enabled=keda_enabled))
    for fc in flow_consumer_specs:
        max_replica = settings.keda_max_replica_cap
        manifests.extend(render_flow_consumer_manifests(
            fc, ctx, max_replica=max_replica,
            msgs_per_replica=settings.keda_msgs_per_replica, keda_enabled=keda_enabled,
        ))
    return manifests


async def deploy(session: AsyncSession, deployment: FlowDeployment) -> dict[str, Any]:
    """执行一键部署（block_mode 或 flow_mode）。"""
    from app.observability.metrics import K8S_DEPLOY

    is_flow_mode = getattr(deployment, "deployment_type", "block_mode") == "flow_mode"
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

    keda_ok = await deployment_manager.keda_available()
    warnings: list[str] = []

    if is_flow_mode:
        # flow_mode：整流单 Pod
        # 合并所有块的 requirements，构建含所有块依赖的统一镜像（避免 base 镜像缺依赖）
        flow_runner_image = await _resolve_flow_runner_image(specs)
        flow_runner_spec = await build_flow_runner_spec(
            session, deployment, ctx, specs, image=flow_runner_image
        )
        if not keda_ok and flow_runner_spec.has_mq:
            warnings.append(
                "集群未安装 KEDA：FlowRunner 以固定副本(min=1)运行，未启用基于队列深度的自动扩缩。"
                "安装 KEDA 后重新部署即可恢复弹性伸缩。"
            )
        manifests = render_all_manifests(
            specs, ctx, keda_enabled=keda_ok, flow_runner_spec=flow_runner_spec
        )
    else:
        # block_mode：原有路径
        flow_consumer_specs = await build_flow_consumer_specs(session, deployment, ctx, specs)
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

    if is_flow_mode:
        block_statuses = await cluster_monitor.collect_flow_runner_status(flow_runner_spec, ctx)
    else:
        flow_consumer_specs = await build_flow_consumer_specs(session, deployment, ctx, specs)
        block_statuses = await cluster_monitor.collect_deployment_status(
            specs, ctx, flow_consumer_specs
        )
    deployment.status = cluster_monitor.aggregate_status(block_statuses)
    deployment.block_statuses = block_statuses
    await session.commit()
    K8S_DEPLOY.labels(action="deploy", result="ok").inc()
    logger.info(
        "flow_deployed",
        deployment_id=deployment.id,
        mode=getattr(deployment, "deployment_type", "block_mode"),
        blocks=len(specs),
        keda=keda_ok,
    )
    return {"status": deployment.status, "block_statuses": block_statuses, "warnings": warnings}


async def destroy(session: AsyncSession, deployment: FlowDeployment) -> dict[str, Any]:
    """销毁部署：删除全部 K8s 资源。"""
    from app.observability.metrics import K8S_DEPLOY

    is_flow_mode = getattr(deployment, "deployment_type", "block_mode") == "flow_mode"
    specs = await build_deployment_specs(session, deployment)
    ctx = _build_context(deployment)
    if is_flow_mode:
        flow_runner_spec = await build_flow_runner_spec(session, deployment, ctx, specs)
        manifests = render_all_manifests(specs, ctx, flow_runner_spec=flow_runner_spec)
    else:
        flow_consumer_specs = await build_flow_consumer_specs(session, deployment, ctx, specs)
        manifests = render_all_manifests(specs, ctx, flow_consumer_specs=flow_consumer_specs)
    await deployment_manager.delete_manifests(manifests, ctx.namespace)
    deployment.status = "stopped"
    deployment.block_statuses = []
    await session.commit()
    K8S_DEPLOY.labels(action="destroy", result="ok").inc()
    return {"status": "stopped"}


async def status(session: AsyncSession, deployment: FlowDeployment) -> dict[str, Any]:
    is_flow_mode = getattr(deployment, "deployment_type", "block_mode") == "flow_mode"
    specs = await build_specs(session, deployment.flow_id)
    ctx = _build_context(deployment)
    if is_flow_mode:
        flow_runner_spec = await build_flow_runner_spec(session, deployment, ctx, specs)
        block_statuses = await cluster_monitor.collect_flow_runner_status(flow_runner_spec, ctx)
    else:
        flow_consumer_specs = await build_flow_consumer_specs(session, deployment, ctx, specs)
        block_statuses = await cluster_monitor.collect_deployment_status(
            specs, ctx, flow_consumer_specs
        )
    agg = cluster_monitor.aggregate_status(block_statuses)
    deployment.status = agg
    deployment.block_statuses = block_statuses
    await session.commit()
    return {"status": agg, "block_statuses": block_statuses}
