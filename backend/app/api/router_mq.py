"""/api/mq — MQ 消费者管理（dev-local 控制面消费者 + 队列深度 + 测试发布）。

触发方式为 mq / both 的接口（PublishedApi）按接口维度消费 flow.{api_id}.queue，
收到消息驱动整条 Flow 编排（决策 3.1 重写为 Flow 级模型 A）。
prod（Phase 4+）：消费者 = Flow-Consumer Pod，此路由仅提供统计和测试入口。
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
from app.errors import PYFLOW_API_NOT_FOUND, BusinessException
from app.models.api_portal import PublishedApi

router = APIRouter(prefix="/api/mq", tags=["mq"])
settings = get_settings()


async def _get_api(session: AsyncSession, api_id: str) -> PublishedApi:
    api = await session.get(PublishedApi, api_id)
    if api is None:
        raise BusinessException(PYFLOW_API_NOT_FOUND, api_id)
    return api


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


@router.get("/apis/{api_id}/status")
async def get_consumer_status(
    api_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    api = await _get_api(session, api_id)
    mgr = get_consumer_manager()
    status = mgr.get_status(api_id)
    depths: dict[str, int] = {"main": 0, "dlq": 0}
    try:
        depths = await mgr.fetch_queue_depth(api_id)
    except Exception:
        pass
    return {
        "api_id": api_id,
        "api_name": api.name,
        "trigger_type": api.trigger_type,
        "consumer": status.__dict__ if status else None,
        "queue_depth": depths,
        "mq_config": api.mq_config,
    }


@router.get("/apis/{api_id}/depth")
async def get_queue_depth(
    api_id: str,
    _: str = Depends(require_role(Role.VIEWER)),
):
    mgr = get_consumer_manager()
    try:
        depths = await mgr.fetch_queue_depth(api_id)
    except Exception as exc:
        return {"error": str(exc), "main": -1, "dlq": -1}
    return depths


# ── 消费者生命周期 ─────────────────────────────────────────────────────────────

@router.post("/apis/{api_id}/start")
async def start_consumer(
    api_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.EDITOR)),
):
    """启动 dev-local 消费者（仅本地模式有效；prod 消费者 = Flow-Consumer Pod）。"""
    if settings.deployment_mode != "local":
        return {"message": "prod 模式下消费者由 Flow-Consumer Pod 承载，无需手动启动"}

    api = await _get_api(session, api_id)
    if api.trigger_type not in ("mq", "both"):
        return {"message": f"接口触发方式为 {api.trigger_type}，无需 MQ 消费者"}

    mgr = get_consumer_manager()
    ok = await mgr.start_consumer(
        api_id=api_id,
        api_name=api.name,
        mq_config=api.mq_config or {},
    )
    return {"started": ok, "api_id": api_id, "api_name": api.name}


@router.post("/apis/{api_id}/stop")
async def stop_consumer(
    api_id: str,
    _: str = Depends(require_role(Role.EDITOR)),
):
    mgr = get_consumer_manager()
    await mgr.stop_consumer(api_id)
    return {"stopped": True, "api_id": api_id}


@router.post("/apis/{api_id}/restart")
async def restart_consumer(
    api_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.EDITOR)),
):
    """重启消费者（配置/流程更新后调用）。"""
    api = await _get_api(session, api_id)
    mgr = get_consumer_manager()
    await mgr.stop_consumer(api_id)
    ok = await mgr.start_consumer(
        api_id=api_id,
        api_name=api.name,
        mq_config=api.mq_config or {},
    )
    return {"restarted": ok, "api_id": api_id}


# ── 测试发布 ───────────────────────────────────────────────────────────────────

class PublishTestRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    snowflake_id: str | None = None


@router.post("/apis/{api_id}/test-run")
async def test_run_api(
    api_id: str,
    req: PublishTestRequest,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.EDITOR)),
):
    """用 MQ payload 直接同步驱动接口对应 Flow，返回整流输出（兼容 local/k8s 模式）。

    执行逻辑与消费者一致：先经 input_mapping 提取 inputs，再驱动整条 Flow 编排。
    """
    api = await _get_api(session, api_id)
    snowflake_id = req.snowflake_id or str(uuid.uuid4()).replace("-", "")
    payload = req.payload

    # 与消费者保持一致：用 input_mapping 从消息体中提取 inputs
    mq_cfg = api.mq_config or {}
    try:
        from pyflow_runtime.input_mapper import map_inputs
        inputs = map_inputs(payload, mq_cfg.get("input_mapping"))
    except Exception:
        inputs = payload  # mapping 失败则把整个 payload 当 inputs

    mgr = get_consumer_manager()
    try:
        outputs = await mgr.run_flow_for_api(api_id, inputs)
        status = "succeeded"
    except BusinessException:
        raise
    except Exception as exc:  # noqa: BLE001
        outputs = {"error": str(exc)[:500]}
        status = "failed"

    return {
        "api_id": api_id,
        "status": status,
        "outputs": outputs,
        "inputs_used": inputs,
        "snowflake_id": snowflake_id,
    }


@router.post("/apis/{api_id}/publish")
async def publish_test_message(
    api_id: str,
    req: PublishTestRequest,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.EDITOR)),
):
    """向接口主队列发布一条 MQ 消息（需要 RabbitMQ 已连接且消费者正在运行）。"""
    await _get_api(session, api_id)
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
            api_id=api_id,
            payload=payload,
            snowflake_id=snowflake_id,
        )
        return {"published": True, "snowflake_id": snowflake_id, "queue": f"flow.{api_id}.queue"}
    except Exception as exc:
        return {"error": str(exc)}


# ── DLQ 运维（查看 / 重投 / 清空死信，生产级 MQ 运维）─────────────────────────

@router.get("/apis/{api_id}/dlq")
async def peek_dlq(
    api_id: str,
    limit: int = 10,
    _: str = Depends(require_role(Role.VIEWER)),
):
    """预览 DLQ 死信样本（不消费，requeue=true）。"""
    mgr = get_consumer_manager()
    try:
        messages = await mgr.peek_dlq(api_id, min(max(limit, 1), 50))
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "messages": []}
    return {"api_id": api_id, "count": len(messages), "messages": messages}


@router.post("/apis/{api_id}/dlq/requeue")
async def requeue_dlq(
    api_id: str,
    _: str = Depends(require_role(Role.DEPLOYER)),
):
    """把 DLQ 死信全部重投回主队列并重置 x-retry-count（DEPLOYER 人工干预）。"""
    mgr = get_consumer_manager()
    moved = await mgr.requeue_dlq(api_id)
    return {"requeued": moved, "api_id": api_id}


@router.post("/apis/{api_id}/dlq/purge")
async def purge_dlq(
    api_id: str,
    _: str = Depends(require_role(Role.DEPLOYER)),
):
    """清空 DLQ（确认死信无需保留时，DEPLOYER）。"""
    mgr = get_consumer_manager()
    purged = await mgr.purge_dlq(api_id)
    return {"purged": purged, "api_id": api_id}


# ── 批量操作（按 mq/both 接口自动启停） ──────────────────────────────────────

@router.post("/start-all")
async def start_all_consumers(
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.EDITOR)),
):
    """启动所有 mq / both 接口的消费者（dev-local 一键启动）。"""
    if settings.deployment_mode != "local":
        return {"message": "prod 模式无需手动启动"}

    rows = (await session.execute(
        select(PublishedApi).where(PublishedApi.trigger_type.in_(["mq", "both"]))
    )).scalars().all()

    mgr = get_consumer_manager()
    results = []
    for api in rows:
        ok = await mgr.start_consumer(
            api_id=api.id,
            api_name=api.name,
            mq_config=api.mq_config or {},
        )
        results.append({"api_id": api.id, "api_name": api.name, "started": ok})

    return {"results": results, "total": len(results)}


@router.post("/stop-all")
async def stop_all_consumers(
    _: str = Depends(require_role(Role.EDITOR)),
):
    mgr = get_consumer_manager()
    for api_id in list(mgr._tasks.keys()):
        await mgr.stop_consumer(api_id)
    return {"stopped": True}
