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
    """列出该部署各 Block 的 Pod 资源（块默认值 / 部署级覆盖 / 生效值）。"""
    dep = await _get(session, deployment_id)
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


@router.post("/{deployment_id}/resources/precheck")
async def precheck_deployment_resources(
    deployment_id: str,
    req: DeploymentResourceRequest,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    """对“尚未保存”的资源覆盖做实时容量/GPU/scope 预检（编辑时即时反馈，不落库）。"""
    dep = await _get(session, deployment_id)
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
