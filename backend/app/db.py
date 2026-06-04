"""异步数据库会话（独立 PostgreSQL 库，决策 8）。"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()


class Base(DeclarativeBase):
    pass


# 引擎/会话工厂延迟创建：避免在 import 阶段加载 DB driver（asyncpg），
# 提升纯逻辑模块的可测试性（AIR：单测不依赖外部服务）。
_engine = None
_session_local = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.db_dsn, pool_pre_ping=True, future=True)
    return _engine


def get_session_factory():
    global _session_local
    if _session_local is None:
        _session_local = async_sessionmaker(
            get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _session_local


def __getattr__(name: str) -> Any:
    """PEP 562：保持 `from app.db import engine / SessionLocal` 的兼容写法。"""
    if name == "engine":
        return get_engine()
    if name == "SessionLocal":
        return get_session_factory()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with get_session_factory()() as session:
        yield session


async def init_models() -> None:
    """dev 便捷建表；生产用 Alembic 迁移 Job（决策：迁移不放控制面 Pod）。"""
    from app import models  # noqa: F401 确保模型已导入

    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
