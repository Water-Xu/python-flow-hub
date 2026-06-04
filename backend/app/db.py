"""异步数据库会话（独立 PostgreSQL 库，决策 8）。"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.db_dsn, pool_pre_ping=True, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def init_models() -> None:
    """dev 便捷建表；生产用 Alembic 迁移 Job（决策：迁移不放控制面 Pod）。"""
    from app import models  # noqa: F401 确保模型已导入

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
