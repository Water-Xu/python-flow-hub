"""健康检查（分级，避免级联失败，生产级保障）。"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from app.db import engine

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live():
    """只检查进程自身，不依赖外部中间件。"""
    return {"status": "alive"}


@router.get("/health/ready")
async def ready():
    """只硬依赖接收流量必需的 PostgreSQL；其余依赖抖动降级不影响就绪。"""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "not_ready", "detail": str(exc)}


@router.get("/health/deps")
async def deps():
    """各依赖连通性（仅诊断，不参与就绪判定）。"""
    result: dict[str, str] = {}
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        result["postgres"] = "up"
    except Exception:  # noqa: BLE001
        result["postgres"] = "down"
    return result


@router.get("/metrics")
async def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
