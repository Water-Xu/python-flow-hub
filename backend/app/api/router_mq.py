"""/api/mq — MQ 消费者管理（dev-local 控制面消费者 + 队列深度 + 测试发布）。

Phase 2：RabbitMQ aio-pika 消费者 + TTL+DLX 重试 + Redis 幂等 + MQ 配置面板。
prod（Phase 4+）：消费者 = Block Pod，此路由仅提供统计和测试入口。
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import Role, require_role
from app.config import get_settings
from app.core.mq.consumer_manager import get_consumer_manager
from app.core.mq.topology_builder import publish_message
from app.db import get_session
from app.errors import PYFLOW_BLOCK_NOT_FOUND, BusinessException
from app.models.block import Block

router = APIRouter(prefix="/api/mq", tags=["mq"])
settings = get_settings()


async def _get_block(session: AsyncSession, block_id: str) -> Block:
    block = await session.get(Block, block_id)
    if block is None:
        raise BusinessException(PYFLOW_BLOCK_NOT_FOUND, block_id)
    return block


# ── 消费者状态 ─────────────────────────────────────────────────────────────────

@router.get("/status")
async def list_consumers(
    _: str = Depends(require_role(Role.VIEWER)),
):
    """列出所有已注册消费者及其状态。"""
    mgr = get_consumer_manager()
    return {
        "mode": settings.deployment_mode,
        "consumers": mgr.all_statuses(),
    }


@router.get("/blocks/{block_id}/status")
async def get_consumer_status(
    block_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    block = await _get_block(session, block_id)
    mgr = get_consumer_manager()
    status = mgr.get_status(block_id)
    depths: dict[str, int] = {"main": 0, "dlq": 0}
    try:
        depths = await mgr.fetch_queue_depth(block_id)
    except Exception:
        pass
    return {
        "block_id": block_id,
        "block_name": block.name,
        "execution_mode": block.execution_mode,
        "consumer": status.__dict__ if status else None,
        "queue_depth": depths,
        "mq_config": block.mq_config,
    }


@router.get("/blocks/{block_id}/depth")
async def get_queue_depth(
    block_id: str,
    _: str = Depends(require_role(Role.VIEWER)),
):
    mgr = get_consumer_manager()
    try:
        depths = await mgr.fetch_queue_depth(block_id)
    except Exception as exc:
        return {"error": str(exc), "main": -1, "dlq": -1}
    return depths


# ── 消费者生命周期 ─────────────────────────────────────────────────────────────

@router.post("/blocks/{block_id}/start")
async def start_consumer(
    block_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.EDITOR)),
):
    """启动 dev-local 消费者（仅本地模式有效；prod 消费者 = Block Pod）。"""
    if settings.deployment_mode != "local":
        return {"message": "prod 模式下消费者由 Block Pod 承载，无需手动启动"}

    block = await _get_block(session, block_id)
    if block.execution_mode not in ("async_mq", "both"):
        return {"message": f"块执行模式为 {block.execution_mode}，无需 MQ 消费者"}

    mq_config = block.mq_config or {}
    mgr = get_consumer_manager()
    ok = await mgr.start_consumer(
        block_id=block_id,
        block_name=block.name,
        block_code=block.draft_code or "",
        mq_config=mq_config,
        compute_config=block.compute_config or {},
    )
    return {"started": ok, "block_id": block_id, "block_name": block.name}


@router.post("/blocks/{block_id}/stop")
async def stop_consumer(
    block_id: str,
    _: str = Depends(require_role(Role.EDITOR)),
):
    mgr = get_consumer_manager()
    await mgr.stop_consumer(block_id)
    return {"stopped": True, "block_id": block_id}


@router.post("/blocks/{block_id}/restart")
async def restart_consumer(
    block_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.EDITOR)),
):
    """重启消费者（代码更新后调用）。"""
    block = await _get_block(session, block_id)
    mgr = get_consumer_manager()
    await mgr.stop_consumer(block_id)
    ok = await mgr.start_consumer(
        block_id=block_id,
        block_name=block.name,
        block_code=block.draft_code or "",
        mq_config=block.mq_config or {},
        compute_config=block.compute_config or {},
    )
    return {"restarted": ok, "block_id": block_id}


# ── 测试发布 ───────────────────────────────────────────────────────────────────

class PublishTestRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    snowflake_id: str | None = None
    # 调用脚本中的哪个入口函数（默认 run，支持一脚本多函数）
    entrypoint: str | None = None


@router.post("/blocks/{block_id}/test-run")
async def test_run_block(
    block_id: str,
    req: PublishTestRequest,
    session: AsyncSession = Depends(get_session),
    login_id: str = Depends(require_role(Role.EDITOR)),
):
    """用 MQ payload 直接同步执行块代码，记录执行历史并返回结果（兼容 local/k8s 模式）。

    执行逻辑与消费者一致：先经 input_mapping 提取 inputs，再调用 execution_service。
    结果实时返回，并在执行历史中可查。
    """
    from app.core.execution_service import execute_block

    block = await _get_block(session, block_id)
    snowflake_id = req.snowflake_id or str(uuid.uuid4()).replace("-", "")
    payload = req.payload

    # 与消费者保持一致：用 input_mapping 从消息体中提取 inputs
    mq_cfg = block.mq_config or {}
    try:
        from pyflow_runtime.input_mapper import map_inputs
        inputs = map_inputs(payload, mq_cfg.get("input_mapping"))
    except Exception:
        inputs = payload  # mapping 失败则把整个 payload 当 inputs

    record = await execute_block(
        session,
        block_id=block.id,
        code=block.draft_code or "",
        inputs=inputs,
        login_id=login_id,
        entrypoint=req.entrypoint or "run",
    )

    return {
        "execution_id": record.id,
        "status": record.status,
        "output": record.output,
        "stdout": record.stdout,
        "stderr": record.stderr,
        "duration_ms": record.duration_ms,
        "inputs_used": inputs,
        "snowflake_id": snowflake_id,
    }


@router.post("/blocks/{block_id}/publish")
async def publish_test_message(
    block_id: str,
    req: PublishTestRequest,
    _: str = Depends(require_role(Role.EDITOR)),
):
    """向块主队列发布一条 MQ 消息（需要 RabbitMQ 已连接且消费者正在运行）。"""
    mgr = get_consumer_manager()
    if not mgr._connection or mgr._connection.is_closed:
        ok = await mgr.connect()
        if not ok:
            return {"error": "RabbitMQ 连接失败，请检查配置"}

    snowflake_id = req.snowflake_id or str(uuid.uuid4()).replace("-", "")
    payload = req.payload
    if "header" not in payload:
        payload = {"header": {"snowflakeId": snowflake_id}, **payload}

    try:
        channel = mgr._channel
        if not channel or channel.is_closed:
            channel = await mgr._connection.channel()
        await publish_message(
            channel=channel,
            block_id=block_id,
            payload=payload,
            snowflake_id=snowflake_id,
        )
        return {"published": True, "snowflake_id": snowflake_id, "queue": f"block.{block_id}.queue"}
    except Exception as exc:
        return {"error": str(exc)}


# ── DLQ 运维（查看 / 重投 / 清空死信，生产级 MQ 运维）─────────────────────────

@router.get("/blocks/{block_id}/dlq")
async def peek_dlq(
    block_id: str,
    limit: int = 10,
    _: str = Depends(require_role(Role.VIEWER)),
):
    """预览 DLQ 死信样本（不消费，requeue=true）。"""
    mgr = get_consumer_manager()
    try:
        messages = await mgr.peek_dlq(block_id, min(max(limit, 1), 50))
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "messages": []}
    return {"block_id": block_id, "count": len(messages), "messages": messages}


@router.post("/blocks/{block_id}/dlq/requeue")
async def requeue_dlq(
    block_id: str,
    _: str = Depends(require_role(Role.DEPLOYER)),
):
    """把 DLQ 死信全部重投回主队列并重置 x-retry-count（DEPLOYER 人工干预）。"""
    mgr = get_consumer_manager()
    moved = await mgr.requeue_dlq(block_id)
    return {"requeued": moved, "block_id": block_id}


@router.post("/blocks/{block_id}/dlq/purge")
async def purge_dlq(
    block_id: str,
    _: str = Depends(require_role(Role.DEPLOYER)),
):
    """清空 DLQ（确认死信无需保留时，DEPLOYER）。"""
    mgr = get_consumer_manager()
    purged = await mgr.purge_dlq(block_id)
    return {"purged": purged, "block_id": block_id}


# ── 批量操作（按 async_mq blocks 自动启停） ──────────────────────────────────

@router.post("/start-all")
async def start_all_consumers(
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.EDITOR)),
):
    """启动所有 async_mq / both 块的消费者（dev-local 一键启动）。"""
    if settings.deployment_mode != "local":
        return {"message": "prod 模式无需手动启动"}

    rows = (await session.execute(
        select(Block).where(Block.execution_mode.in_(["async_mq", "both"]))
    )).scalars().all()

    mgr = get_consumer_manager()
    results = []
    for block in rows:
        ok = await mgr.start_consumer(
            block_id=block.id,
            block_name=block.name,
            block_code=block.draft_code or "",
            mq_config=block.mq_config or {},
            compute_config=block.compute_config or {},
        )
        results.append({"block_id": block.id, "block_name": block.name, "started": ok})

    return {"results": results, "total": len(results)}


@router.post("/stop-all")
async def stop_all_consumers(
    _: str = Depends(require_role(Role.EDITOR)),
):
    mgr = get_consumer_manager()
    for block_id in list(mgr._tasks.keys()):
        await mgr.stop_consumer(block_id)
    return {"stopped": True}
