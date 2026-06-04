"""/api/rbac — grant/revoke（仅 ADMIN，含审计，决策 2）
              + 资源级 ACL（决策 15）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import Role, require_role, current_login_id
from app.db import get_session
from app.models.rbac import PyFlowUserRole, PyFlowResourceGrant
from app.observability.logging import get_logger

router = APIRouter(prefix="/api/rbac", tags=["rbac"])
logger = get_logger("pyflow.rbac")


class GrantRequest(BaseModel):
    login_id: str
    role: str  # viewer | editor | deployer | admin


class ResourceGrantRequest(BaseModel):
    resource_type: str   # block | flow
    resource_id: str
    login_id: str
    access: str          # view | edit | deploy


# ── 平台级角色 CRUD ────────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.ADMIN)),
):
    """列出所有已分配角色的用户（供 RbacAdmin.vue 展示）。"""
    rows = (await session.execute(
        select(PyFlowUserRole).order_by(PyFlowUserRole.created_at.desc())
    )).scalars().all()
    return [
        {
            "id": r.id,
            "login_id": r.login_id,
            "role": r.role,
            "granted_by": r.granted_by,
            "granted_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get("/roles/{login_id}")
async def list_roles(
    login_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.ADMIN)),
):
    rows = (await session.execute(
        select(PyFlowUserRole).where(PyFlowUserRole.login_id == login_id)
    )).scalars().all()
    return [
        {"role": r.role, "granted_by": r.granted_by, "granted_at": r.created_at}
        for r in rows
    ]


@router.post("/grant")
async def grant_role(
    req: GrantRequest,
    session: AsyncSession = Depends(get_session),
    operator: str = Depends(require_role(Role.ADMIN)),
):
    session.add(PyFlowUserRole(login_id=req.login_id, role=req.role, granted_by=operator))
    await session.commit()
    logger.info("rbac_grant", login_id=req.login_id, role=req.role, granted_by=operator)
    return {"granted": req.login_id, "role": req.role}


@router.post("/revoke")
async def revoke_role(
    req: GrantRequest,
    session: AsyncSession = Depends(get_session),
    operator: str = Depends(require_role(Role.ADMIN)),
):
    await session.execute(
        delete(PyFlowUserRole).where(
            PyFlowUserRole.login_id == req.login_id,
            PyFlowUserRole.role == req.role,
        )
    )
    await session.commit()
    logger.info("rbac_revoke", login_id=req.login_id, role=req.role, granted_by=operator)
    return {"revoked": req.login_id, "role": req.role}


# ── 资源级 ACL（决策 15）─────────────────────────────────────────────────────

@router.get("/resource/{resource_type}/{resource_id}/grants")
async def list_resource_grants(
    resource_type: str,
    resource_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.ADMIN)),
):
    rows = (await session.execute(
        select(PyFlowResourceGrant).where(
            PyFlowResourceGrant.resource_type == resource_type,
            PyFlowResourceGrant.resource_id == resource_id,
        )
    )).scalars().all()
    return [
        {
            "id": r.id,
            "login_id": r.login_id,
            "access": r.access,
            "granted_by": r.granted_by,
            "granted_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.post("/resource/grant")
async def grant_resource(
    req: ResourceGrantRequest,
    session: AsyncSession = Depends(get_session),
    operator: str = Depends(require_role(Role.ADMIN)),
):
    session.add(PyFlowResourceGrant(
        resource_type=req.resource_type,
        resource_id=req.resource_id,
        login_id=req.login_id,
        access=req.access,
        granted_by=operator,
    ))
    await session.commit()
    logger.info("rbac_resource_grant", **req.dict(), granted_by=operator)
    return {"granted": req.dict()}


@router.post("/resource/revoke")
async def revoke_resource(
    req: ResourceGrantRequest,
    session: AsyncSession = Depends(get_session),
    operator: str = Depends(require_role(Role.ADMIN)),
):
    await session.execute(
        delete(PyFlowResourceGrant).where(
            PyFlowResourceGrant.resource_type == req.resource_type,
            PyFlowResourceGrant.resource_id == req.resource_id,
            PyFlowResourceGrant.login_id == req.login_id,
            PyFlowResourceGrant.access == req.access,
        )
    )
    await session.commit()
    logger.info("rbac_resource_revoke", **req.dict(), granted_by=operator)
    return {"revoked": req.dict()}
