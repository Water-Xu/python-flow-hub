"""/api/deployments — FlowDeployment（Phase 4a K8s 编排：部署/销毁/状态/预检）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import Role, require_role
from app.core.k8s import orchestrator
from app.db import get_session
from app.errors import PYFLOW_FLOW_NOT_FOUND, BusinessException
from app.models.deployment import FlowDeployment

router = APIRouter(prefix="/api/deployments", tags=["deployments"])


class DeploymentCreateRequest(BaseModel):
    flow_id: str
    name: str
    environment: str = "local"  # local | k8s
    deployment_type: str = "block_mode"  # block_mode | flow_mode


class DeploymentEnvRequest(BaseModel):
    env_vars: dict[str, str] = {}
    secret_refs: dict[str, str] = {}


# CPU：'100m' / '0.5' / '2'；内存：'256Mi' / '1Gi' / '512M'
_CPU_PATTERN = r"^\d+(\.\d+)?m?$"
_MEM_PATTERN = r"^\d+(\.\d+)?(Ki|Mi|Gi|Ti|Pi|K|M|G|T|P)?$"
_GPU_TYPE_PATTERN = r"^[a-z0-9-]+$"


class BlockResourceSpec(BaseModel):
    """单个 Block 的 Pod 资源覆盖（仅作用于本部署；空字段表示沿用块默认值）。"""

    cpu_request: str | None = Field(default=None, pattern=_CPU_PATTERN)
    memory_request: str | None = Field(default=None, pattern=_MEM_PATTERN)
    cpu_limit: str | None = Field(default=None, pattern=_CPU_PATTERN)
    memory_limit: str | None = Field(default=None, pattern=_MEM_PATTERN)
    gpu_enabled: bool | None = None
    gpu_count: int | None = Field(default=None, ge=1, le=8)
    gpu_type: str | None = Field(default=None, pattern=_GPU_TYPE_PATTERN, max_length=64)


class DeploymentResourceRequest(BaseModel):
    """部署级 Pod 资源覆盖：{block_id: BlockResourceSpec}。"""

    resource_overrides: dict[str, BlockResourceSpec] = {}


def _dep_dict(d: FlowDeployment) -> dict:
    return {
        "id": d.id, "flow_id": d.flow_id, "flow_version_id": d.flow_version_id,
        "name": d.name, "environment": d.environment, "status": d.status,
        "deployment_type": getattr(d, "deployment_type", "block_mode"),
        "resource_prefix": d.resource_prefix, "entry_endpoint": d.entry_endpoint,
        "block_statuses": d.block_statuses or [], "created_at": d.created_at,
        "env_vars": d.env_vars or {}, "secret_refs": d.secret_refs or {},
        "resource_overrides": d.resource_overrides or {},
    }


async def _get(session: AsyncSession, deployment_id: str) -> FlowDeployment:
    dep = await session.get(FlowDeployment, deployment_id)
    if dep is None:
        raise BusinessException(PYFLOW_FLOW_NOT_FOUND, deployment_id)
    return dep


@router.get("")
async def list_deployments(
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    rows = (await session.execute(
        select(FlowDeployment).order_by(FlowDeployment.created_at.desc())
    )).scalars().all()
    return [_dep_dict(d) for d in rows]


@router.get("/{deployment_id}")
async def get_deployment(
    deployment_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    return _dep_dict(await _get(session, deployment_id))


@router.post("")
async def create_deployment(
    req: DeploymentCreateRequest,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.DEPLOYER)),
):
    prefix = f"flow-{req.flow_id[:8]}-{req.name}".lower().replace(" ", "-")[:63]
    dep = FlowDeployment(
        flow_id=req.flow_id, name=req.name, environment=req.environment,
        deployment_type=req.deployment_type,
        resource_prefix=prefix, status="stopped",
        entry_endpoint=f"/flow/{req.flow_id}/invoke",
    )
    session.add(dep)
    await session.commit()
    await session.refresh(dep)
    return _dep_dict(dep)


@router.put("/{deployment_id}/env")
async def update_deployment_env(
    deployment_id: str,
    req: DeploymentEnvRequest,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.DEPLOYER)),
):
    """配置部署级环境变量（注入该部署全部块；下次部署生效）。"""
    dep = await _get(session, deployment_id)
    dep.env_vars = req.env_vars or {}
    dep.secret_refs = req.secret_refs or {}
    await session.commit()
    return _dep_dict(dep)


@router.get("/{deployment_id}/resources")
async def list_deployment_resources(
    deployment_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    """列出该部署的 Pod 资源（flow_mode: 整流单 Pod；block_mode: 各块独立 Pod）。"""
    dep = await _get(session, deployment_id)
    if getattr(dep, "deployment_type", "block_mode") == "flow_mode":
        return orchestrator.list_flow_runner_resource(dep)
    return await orchestrator.list_block_resources(session, dep)


@router.put("/{deployment_id}/resources")
async def update_deployment_resources(
    deployment_id: str,
    req: DeploymentResourceRequest,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.DEPLOYER)),
):
    """配置部署级 Pod 资源覆盖（按 block_id 覆盖 CPU/内存/GPU；下次部署生效）。"""
    dep = await _get(session, deployment_id)
    overrides: dict[str, dict] = {}
    for block_id, spec in (req.resource_overrides or {}).items():
        # 仅保留显式设置的字段，空值不写入（沿用块默认）
        cleaned = {k: v for k, v in spec.model_dump().items() if v is not None}
        if cleaned:
            overrides[block_id] = cleaned
    dep.resource_overrides = overrides
    await session.commit()
    return _dep_dict(dep)


@router.get("/{deployment_id}/resource-summary")
async def deployment_resource_summary(
    deployment_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    """Flow 维度资源汇总（flow_mode: 整流单 Pod；block_mode: 各块独立 Pod 累加）。"""
    dep = await _get(session, deployment_id)
    if getattr(dep, "deployment_type", "block_mode") == "flow_mode":
        return orchestrator.flow_runner_resource_summary(dep)
    return await orchestrator.flow_resource_summary(session, dep)


@router.post("/{deployment_id}/resources/precheck")
async def precheck_deployment_resources(
    deployment_id: str,
    req: DeploymentResourceRequest,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    """对“尚未保存”的资源覆盖做实时容量/GPU/scope 预检（编辑时即时反馈，不落库）。"""
    dep = await _get(session, deployment_id)
    is_flow_mode = getattr(dep, "deployment_type", "block_mode") == "flow_mode"

    if is_flow_mode:
        from app.core.k8s.manifest_generator import BlockDeploySpec
        flow_spec_data = (req.resource_overrides or {}).get(orchestrator.FLOW_RUNNER_RESOURCE_KEY)
        override = {k: v for k, v in (flow_spec_data.model_dump() if flow_spec_data else {}).items() if v is not None}
        compute = {**orchestrator._FLOW_RUNNER_DEFAULT_COMPUTE, **override}
        synthetic = BlockDeploySpec(
            block_id=orchestrator.FLOW_RUNNER_RESOURCE_KEY,
            name="FlowRunner",
            compute_config=compute,
        )
        return orchestrator.run_prechecks([synthetic])

    specs = await orchestrator.build_specs(session, dep.flow_id)
    overrides: dict[str, dict] = {}
    for block_id, spec in (req.resource_overrides or {}).items():
        cleaned = {k: v for k, v in spec.model_dump().items() if v is not None}
        if cleaned:
            overrides[block_id] = cleaned
    orchestrator.merge_resource_overrides_into_specs(specs, overrides)
    return orchestrator.run_prechecks(specs)


@router.get("/{deployment_id}/precheck")
async def precheck_deployment(
    deployment_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.DEPLOYER)),
):
    """容量 + GPU + scope 预检（含部署级资源覆盖；不部署）。"""
    dep = await _get(session, deployment_id)
    specs = await orchestrator.build_deployment_specs(session, dep)
    return orchestrator.run_prechecks(specs)


@router.get("/{deployment_id}/manifests")
async def render_manifests(
    deployment_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.DEPLOYER)),
):
    """渲染 K8s manifest 预览（不 apply；含全局/部署级环境变量与中间件接入）。"""
    dep = await _get(session, deployment_id)
    specs = await orchestrator.build_deployment_specs(session, dep)
    ctx = orchestrator._build_context(dep)
    return {"manifests": orchestrator.render_all_manifests(specs, ctx)}


@router.post("/{deployment_id}/deploy")
async def deploy_deployment(
    deployment_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.DEPLOYER)),
):
    """一键部署到 K8s（构建/apply Deployment/Service/KEDA/NetworkPolicy）。"""
    dep = await _get(session, deployment_id)
    return await orchestrator.deploy(session, dep)


@router.get("/{deployment_id}/status")
async def deployment_status(
    deployment_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    """实时 K8s 状态（副本/Ready）。"""
    dep = await _get(session, deployment_id)
    if dep.environment != "k8s":
        return {"status": dep.status, "block_statuses": dep.block_statuses or []}
    return await orchestrator.status(session, dep)


@router.get("/{deployment_id}/pods")
async def list_deployment_pods(
    deployment_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    """列出该部署的全部 Pod（含状态/重启次数/节点）。"""
    dep = await _get(session, deployment_id)
    if dep.environment != "k8s":
        return []

    def _do():
        from kubernetes import client, config  # type: ignore
        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()
        v1 = client.CoreV1Api()
        namespace = "pyflow-blocks"
        label_selector = f"pyflow.deploy/prefix={dep.resource_prefix}"
        pods = v1.list_namespaced_pod(namespace, label_selector=label_selector)
        result = []
        for pod in pods.items:
            cs = pod.status.container_statuses or []
            restarts = sum(c.restart_count for c in cs) if cs else 0
            state = "unknown"
            if pod.status.phase:
                state = pod.status.phase.lower()
            if cs:
                st = cs[0].state
                if st.running:
                    state = "running"
                elif st.waiting:
                    state = f"waiting:{st.waiting.reason or ''}"
                elif st.terminated:
                    state = f"terminated:{st.terminated.reason or ''}"
            result.append({
                "name": pod.metadata.name,
                "node": pod.spec.node_name or "",
                "phase": pod.status.phase or "Unknown",
                "state": state,
                "restarts": restarts,
                "app": pod.metadata.labels.get("app", "") if pod.metadata.labels else "",
                "ready": all(c.ready for c in cs) if cs else False,
                "start_time": pod.status.start_time.isoformat() if pod.status.start_time else None,
            })
        return result

    import asyncio
    return await asyncio.to_thread(_do)


@router.get("/{deployment_id}/pods/{pod_name}/logs")
async def get_pod_logs(
    deployment_id: str,
    pod_name: str,
    container: str | None = None,
    tail_lines: int = 200,
    previous: bool = False,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    """获取指定 Pod 的运行日志（tail_lines 行，previous=true 看上次崩溃日志）。"""
    dep = await _get(session, deployment_id)
    if dep.environment != "k8s":
        return {"logs": ""}

    def _do():
        from kubernetes import client, config  # type: ignore
        from kubernetes.client.rest import ApiException  # type: ignore
        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()
        v1 = client.CoreV1Api()
        namespace = "pyflow-blocks"
        kwargs: dict = {
            "tail_lines": max(1, min(tail_lines, 2000)),
            "timestamps": True,
        }
        if container:
            kwargs["container"] = container
        if previous:
            kwargs["previous"] = True
        try:
            logs = v1.read_namespaced_pod_log(pod_name, namespace, **kwargs)
        except ApiException as e:
            if e.status == 400 and previous:
                logs = f"[无上次崩溃日志] HTTP {e.status}: {e.reason}"
            else:
                logs = f"[获取日志失败] HTTP {e.status}: {e.reason}"
        return {"logs": logs or "（暂无日志）"}

    import asyncio
    return await asyncio.to_thread(_do)


@router.delete("/{deployment_id}")
async def destroy_deployment(
    deployment_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.ADMIN)),
):
    """销毁部署（删除全部 K8s 资源，ADMIN）。"""
    dep = await _get(session, deployment_id)
    if dep.environment == "k8s":
        await orchestrator.destroy(session, dep)
    await session.delete(dep)
    await session.commit()
    return {"deleted": True}
