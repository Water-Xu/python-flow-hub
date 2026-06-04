"""平台级角色校验（决策 2）+ 资源级访问校验（决策 15）。

提供 FastAPI 依赖：require_role(MIN_ROLE) / require_resource_access(resource, access)。
"""

from __future__ import annotations

from enum import IntEnum

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.sa_token_client import resolve_login_id
from app.config import get_settings
from app.db import get_session
from app.errors import PYFLOW_AUTH_FORBIDDEN, BusinessException
from app.models.rbac import PyFlowUserRole

settings = get_settings()


class Role(IntEnum):
    VIEWER = 1
    EDITOR = 2
    DEPLOYER = 3
    ADMIN = 4


_ROLE_MAP = {"viewer": Role.VIEWER, "editor": Role.EDITOR,
             "deployer": Role.DEPLOYER, "admin": Role.ADMIN}


async def current_login_id(authorization: str | None = Header(default=None)) -> str:
    token = authorization.removeprefix("Bearer ").strip() if authorization else None
    return await resolve_login_id(token)


async def get_user_roles(login_id: str, session: AsyncSession) -> set[Role]:
    # bootstrap admin：环境变量指定的首个 ADMIN
    roles: set[Role] = set()
    if login_id == settings.bootstrap_admin:
        roles.add(Role.ADMIN)
    rows = (await session.execute(
        select(PyFlowUserRole.role).where(PyFlowUserRole.login_id == login_id)
    )).scalars().all()
    for r in rows:
        if r in _ROLE_MAP:
            roles.add(_ROLE_MAP[r])
    # 1a：鉴权关闭时，dev 默认用户视为 ADMIN，便于本地端到端
    if not settings.auth_enabled:
        roles.add(Role.ADMIN)
    return roles or {Role.VIEWER}


def require_role(min_role: Role):
    """生成校验最低角色的依赖。"""

    async def _dep(
        login_id: str = Depends(current_login_id),
        session: AsyncSession = Depends(get_session),
    ) -> str:
        roles = await get_user_roles(login_id, session)
        if max(roles) < min_role:
            raise BusinessException(PYFLOW_AUTH_FORBIDDEN, f"need role >= {min_role.name}")
        return login_id

    return _dep
