"""/api/deployments — FlowDeployment（Phase 4a K8s 编排：部署/销毁/状态/预检）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
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


def _dep_dict(d: FlowDeployment) -> dict:
    return {
        "id": d.id, "flow_id": d.flow_id, "flow_version_id": d.flow_version_id,
        "name": d.name, "environment": d.environment, "status": d.status,
        "resource_prefix": d.resource_prefix, "entry_endpoint": d.entry_endpoint,
        "block_statuses": d.block_statuses or [], "created_at": d.created_at,
        "env_vars": d.env_vars or {}, "secret_refs": d.secret_refs or {},
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


@router.get("/{deployment_id}/precheck")
async def precheck_deployment(
    deployment_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.DEPLOYER)),
):
    """容量 + GPU + scope 预检（不部署）。"""
    dep = await _get(session, deployment_id)
    specs = await orchestrator.build_specs(session, dep.flow_id)
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
