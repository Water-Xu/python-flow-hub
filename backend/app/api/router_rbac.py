"""/api/rbac — grant/revoke（仅 ADMIN，含审计，决策 2）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import Role, require_role
from app.db import get_session
from app.models.rbac import PyFlowUserRole
from app.observability.logging import get_logger

router = APIRouter(prefix="/api/rbac", tags=["rbac"])
logger = get_logger("pyflow.rbac")


class GrantRequest(BaseModel):
    login_id: str
    role: str  # viewer | editor | deployer | admin


@router.get("/roles/{login_id}")
async def list_roles(
    login_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.ADMIN)),
):
    rows = (await session.execute(
        select(PyFlowUserRole).where(PyFlowUserRole.login_id == login_id)
    )).scalars().all()
    return [{"role": r.role, "granted_by": r.granted_by, "granted_at": r.created_at} for r in rows]


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
            PyFlowUserRole.login_id == req.login_id, PyFlowUserRole.role == req.role
        )
    )
    await session.commit()
    logger.info("rbac_revoke", login_id=req.login_id, role=req.role, granted_by=operator)
    return {"revoked": req.login_id, "role": req.role}
