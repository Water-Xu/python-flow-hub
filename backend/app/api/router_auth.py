"""/api/auth — 当前用户信息 + dev-login bypass（Phase 1b）。

- /api/auth/me：返回当前 loginId 及其在 PyFlowHub 中的最高角色（已登录态）
- /api/auth/dev-login：仅 auth_enabled=false 时有效，直接返回 dev 用户 token 伪造（前端 dev bypass）
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import Role, current_login_id, get_user_roles
from app.config import get_settings
from app.db import get_session
from app.models.rbac import PyFlowUserRole

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()

_ROLE_NAME = {Role.VIEWER: "viewer", Role.EDITOR: "editor",
              Role.DEPLOYER: "deployer", Role.ADMIN: "admin"}


@router.get("/me")
async def get_me(
    login_id: str = Depends(current_login_id),
    session: AsyncSession = Depends(get_session),
):
    """返回当前用户 loginId 及在 PyFlowHub 中的最高角色。"""
    roles = await get_user_roles(login_id, session)
    highest = max(roles) if roles else Role.VIEWER
    return {
        "login_id": login_id,
        "username": login_id,
        "role": _ROLE_NAME.get(highest, "viewer"),
        "is_admin": highest >= Role.ADMIN,
        "auth_enabled": settings.auth_enabled,
    }


@router.post("/dev-login")
async def dev_login(body: dict = None):
    """dev bypass：auth_enabled=false 时返回虚假 token 供前端跳过真实登录。"""
    if settings.auth_enabled:
        from app.errors import PYFLOW_AUTH_UNAUTHORIZED, BusinessException
        raise BusinessException(PYFLOW_AUTH_UNAUTHORIZED, "dev-login only available when auth_enabled=false")
    username = (body or {}).get("username", settings.dev_default_login_id)
    return {
        "code": 200,
        "message": "dev bypass login success",
        "data": {
            "tokenHead": "dev-",
            "tokenValue": f"devtoken-{username}",
            "loginId": username,
        },
    }
