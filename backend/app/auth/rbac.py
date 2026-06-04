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


def require_resource_access(resource_type: str, access: str):
    """生成资源级 ACL 校验依赖（决策 15）。

    放行条件：平台级 ADMIN OR owner 本人 OR resource_grant 表命中。
    用法：router 参数 owner_login_id 需从路径/DB 查到，由调用方在依赖外自行校验。
    本函数提供"检查 resource_grant 表"的工具函数，供 router 复合使用。
    """
    from app.errors import PYFLOW_FORBIDDEN_RESOURCE, BusinessException as BE
    from app.models.rbac import PyFlowResourceGrant

    async def _check(
        resource_id: str,
        login_id: str,
        session: AsyncSession,
        owner_login_id: str | None = None,
    ) -> bool:
        """返回是否有权限；无权则抛 BusinessException。"""
        roles = await get_user_roles(login_id, session)
        if max(roles) >= Role.ADMIN:
            return True
        if owner_login_id and login_id == owner_login_id:
            return True
        grant = (await session.execute(
            select(PyFlowResourceGrant).where(
                PyFlowResourceGrant.resource_type == resource_type,
                PyFlowResourceGrant.resource_id == resource_id,
                PyFlowResourceGrant.login_id == login_id,
                PyFlowResourceGrant.access == access,
            )
        )).scalars().first()
        if grant:
            return True
        raise BE(PYFLOW_FORBIDDEN_RESOURCE, f"{resource_type}/{resource_id} access={access} denied")

    return _check
