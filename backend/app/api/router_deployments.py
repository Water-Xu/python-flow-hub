"""/api/deployments — FlowDeployment（Phase 4a K8s 编排，此处提供 CRUD 骨架）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import Role, require_role
from app.db import get_session
from app.models.deployment import FlowDeployment

router = APIRouter(prefix="/api/deployments", tags=["deployments"])


class DeploymentCreateRequest(BaseModel):
    flow_id: str
    name: str
    environment: str = "local"  # local | k8s


@router.get("")
async def list_deployments(
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    rows = (await session.execute(
        select(FlowDeployment).order_by(FlowDeployment.created_at.desc())
    )).scalars().all()
    return [
        {"id": d.id, "flow_id": d.flow_id, "name": d.name,
         "environment": d.environment, "status": d.status,
         "resource_prefix": d.resource_prefix}
        for d in rows
    ]


@router.post("")
async def create_deployment(
    req: DeploymentCreateRequest,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.DEPLOYER)),
):
    """创建部署记录。K8s 实际编排（镜像构建/apply/KEDA）在 Phase 4a 接入。"""
    prefix = f"flow-{req.flow_id[:8]}-{req.name}"
    dep = FlowDeployment(
        flow_id=req.flow_id, name=req.name, environment=req.environment,
        resource_prefix=prefix, status="stopped",
        entry_endpoint=f"/flow/{req.flow_id}/invoke",
    )
    session.add(dep)
    await session.commit()
    await session.refresh(dep)
    return {"id": dep.id, "resource_prefix": dep.resource_prefix, "status": dep.status}
