"""/api/platform — 平台级全局环境变量 + 中间件接入信息。

- 全局环境变量：注入所有 K8s 部署的调用块（优先级：全局 < 部署 < 块）；仅存非敏感配置；
- 中间件连接：展示块如何连到集群内 redis/mq/db/minio（脱敏，不返回密码明文）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import Role, require_role
from app.config import get_settings
from app.core.k8s import middleware
from app.db import get_session
from app.errors import PYFLOW_EXEC_INPUT_INVALID, BusinessException
from app.models.platform_env import PlatformEnv

router = APIRouter(prefix="/api/platform", tags=["platform"])
settings = get_settings()


class GlobalEnvRequest(BaseModel):
    env_key: str = Field(min_length=1, max_length=128)
    env_value: str = ""
    description: str = ""


def _env_dict(e: PlatformEnv) -> dict:
    return {
        "id": e.id, "env_key": e.env_key, "env_value": e.env_value,
        "description": e.description, "updated_by": e.updated_by,
        "updated_at": e.updated_at,
    }


@router.get("/env")
async def list_global_env(
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    rows = (await session.execute(
        select(PlatformEnv).order_by(PlatformEnv.env_key)
    )).scalars().all()
    return [_env_dict(e) for e in rows]


@router.post("/env")
async def upsert_global_env(
    req: GlobalEnvRequest,
    session: AsyncSession = Depends(get_session),
    login_id: str = Depends(require_role(Role.DEPLOYER)),
):
    """新增或更新全局环境变量（env_key 唯一）。"""
    key = req.env_key.strip()
    if not key.replace("_", "").isalnum():
        raise BusinessException(PYFLOW_EXEC_INPUT_INVALID, "env_key 仅允许字母/数字/下划线")
    existing = (await session.execute(
        select(PlatformEnv).where(PlatformEnv.env_key == key)
    )).scalar_one_or_none()
    if existing is None:
        existing = PlatformEnv(env_key=key)
        session.add(existing)
    existing.env_value = req.env_value
    existing.description = req.description
    existing.updated_by = login_id
    await session.commit()
    await session.refresh(existing)
    return _env_dict(existing)


@router.delete("/env/{env_id}")
async def delete_global_env(
    env_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.DEPLOYER)),
):
    row = await session.get(PlatformEnv, env_id)
    if row is not None:
        await session.delete(row)
        await session.commit()
    return {"deleted": True}


@router.get("/middleware")
async def get_middleware_info(
    _: str = Depends(require_role(Role.VIEWER)),
):
    """块中间件接入信息（脱敏）：连接串、egress 白名单、命名空间端口。"""
    return middleware.middleware_summary(settings)
