"""健康检查（分级，避免级联失败，生产级保障 / 决策 13）。

- /health/live：只检查进程自身，不依赖任何外部中间件（liveness）。
- /health/ready：只硬依赖"接收流量必需"的 PostgreSQL；其余依赖抖动降级不影响就绪。
- /health/deps：全依赖连通性（PG/Redis/RabbitMQ/MinIO），仅诊断 + 写 Prometheus DEP_UP gauge。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from app.config import get_settings
from app.db import engine
from app.observability.metrics import DEP_UP

router = APIRouter(tags=["health"])
settings = get_settings()


@router.get("/health/live")
async def live():
    """只检查进程自身，不依赖外部中间件。"""
    return {"status": "alive"}


@router.get("/health/ready")
async def ready():
    """只硬依赖接收流量必需的 PostgreSQL；其余依赖抖动降级不影响就绪。"""
    if await _check_postgres():
        return {"status": "ready"}
    return JSONResponse(status_code=503, content={"status": "not_ready", "detail": "postgres unavailable"})


@router.get("/health/deps")
async def deps():
    """各依赖连通性（仅诊断，不参与就绪判定）；同步刷新 Prometheus DEP_UP gauge。"""
    pg, redis_ok, mq_ok, minio_ok = await asyncio.gather(
        _check_postgres(), _check_redis(), _check_rabbitmq(), _check_minio(),
    )
    result = {
        "postgres": _label(pg),
        "redis": _label(redis_ok),
        "rabbitmq": _label(mq_ok),
        "minio": _label(minio_ok),
    }
    for dep, ok in (("postgres", pg), ("redis", redis_ok),
                    ("rabbitmq", mq_ok), ("minio", minio_ok)):
        DEP_UP.labels(dependency=dep).set(1 if ok else 0)
    return result


def _label(ok: bool) -> str:
    return "up" if ok else "down"


async def _check_postgres() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        return False


async def _check_redis() -> bool:
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.redis_url, socket_connect_timeout=2)
        try:
            return bool(await asyncio.wait_for(r.ping(), timeout=2))
        finally:
            await r.aclose()
    except Exception:  # noqa: BLE001
        return False


async def _check_rabbitmq() -> bool:
    """两级探针：
    1. Management HTTP API（15672）aliveness-test，用配置的 vhost 和凭据。
       返回 200/204 → UP；其余状态（401/403/404 等）或任何异常 → 进入 fallback。
    2. AMQP 协议直连（5672）：建立真实连接后立即关闭，验证端口可达且凭据有效。
    """
    if await _check_rabbitmq_mgmt():
        return True
    return await _check_rabbitmq_amqp()


async def _check_rabbitmq_mgmt() -> bool:
    """通过 RabbitMQ Management HTTP API 探测。"""
    try:
        import httpx

        from app.core.mq.consumer_manager import _amqp_to_mgmt, _extract_auth, _extract_vhost
        mgmt = _amqp_to_mgmt(settings.rabbitmq_url)
        if not mgmt:
            return False
        vhost = _extract_vhost(settings.rabbitmq_url)
        auth = _extract_auth(settings.rabbitmq_url)
        async with httpx.AsyncClient(timeout=2) as client:
            resp = await client.get(f"{mgmt}/api/aliveness-test/{vhost}", auth=auth)
            return resp.status_code in (200, 204)
    except Exception:  # noqa: BLE001
        return False


async def _check_rabbitmq_amqp() -> bool:
    """Fallback：通过 AMQP 协议（5672）直连验证 RabbitMQ 可达且凭据有效。"""
    try:
        import aio_pika
        conn = await asyncio.wait_for(
            aio_pika.connect(settings.rabbitmq_url),
            timeout=3,
        )
        await conn.close()
        return True
    except Exception:  # noqa: BLE001
        return False


async def _check_minio() -> bool:
    try:
        import httpx
        scheme = "https" if settings.minio_secure else "http"
        async with httpx.AsyncClient(timeout=2) as client:
            resp = await client.get(f"{scheme}://{settings.minio_endpoint}/minio/health/live")
            return resp.status_code == 200
    except Exception:  # noqa: BLE001
        return False


@router.get("/metrics")
async def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
