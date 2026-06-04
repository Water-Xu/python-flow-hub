"""aio-pika 消费者核心（在 Block Pod 内运行，决策 3.1 模型 A）。

消费 block.{block_id}.queue，按决策 7 幂等状态机执行用户代码：
- 抢占 / 接管：fence_token CAS，区分在跑 / 可接管 / 已终态；
- 执行期间后台心跳续租 lease，心跳失败（被接管）则主动 abort，绝不双跑（决策 7）；
- 失败走 TTL+DLX 重试（决策 6）；owner 存活 / 接管竞争失败走退避重入；
- 成功后按 carry_fields 构造回复并 publish（决策 6/7），重复投递补发回复（至少一次 + 下游去重）。

prod：打进 runner 镜像，KEDA 据队列 ready 深度扩缩本 Deployment；
dev local：控制面 consumer_manager 复用本函数（同一套幂等/条件/回复语义）。
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import suppress
from typing import Any, Awaitable, Callable

from pyflow_runtime import RUNTIME_PROTOCOL_VERSION
from pyflow_runtime import backoff_queue
from pyflow_runtime.condition_engine import ConditionError, evaluate_condition
from pyflow_runtime.idempotency import (
    IdempotencyStore,
    build_idempotency_id,
    extract_business_id,
)
from pyflow_runtime.input_mapper import map_inputs
from pyflow_runtime.reply_builder import build_reply

logger = logging.getLogger("pyflow.runtime.consumer")

POD_NAME = os.getenv("HOSTNAME", "local-runner")
DEFAULT_LEASE_TTL = 30
DLQ_TOTAL_RETRY_WINDOW = 60

# execute_fn(inputs) -> 用户输出 dict；失败应抛异常（由本模块捕获写 FAILED）
ExecuteFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
# reply_publisher(reply, mq_config) -> None；由调用方注入（dev=控制面 channel / prod=runner channel）
ReplyPublisher = Callable[[dict[str, Any], dict[str, Any]], Awaitable[None]]


class LeaseLostError(Exception):
    """执行期间 lease 被接管（fence_token 失配）：本副本必须放弃，不写任何结果（决策 7）。"""


def max_execution_time(block_config: dict[str, Any]) -> int:
    return int((block_config.get("compute_config") or {}).get("max_execution_time", 3600))


def protocol_compatible(headers: dict[str, Any]) -> bool:
    """决策 3.1 点 5：消息头协议版本须与本 runtime 一致。

    缺失 header 视为兼容（向后宽松，便于历史消息 / dev 手发）；显式不一致则拒绝。
    """
    proto = headers.get("pyflow-protocol")
    if proto is None:
        return True
    return str(proto) == str(RUNTIME_PROTOCOL_VERSION)


async def _execute_with_lease(
    store: IdempotencyStore,
    idem_id: str,
    fence_token: int,
    lease_ttl: int,
    state_ttl: int,
    coro: Awaitable[dict[str, Any]],
) -> dict[str, Any]:
    """执行用户代码，期间后台心跳续租；心跳 CAS 失败（被接管）则取消执行并抛 LeaseLostError。

    决策 7：长任务（如 GPU 训练）靠心跳持续续约，lease_ttl 远小于执行时间。
    """
    lost = asyncio.Event()

    async def _heartbeat_loop() -> None:
        interval = max(1, lease_ttl // 3)
        while True:
            await asyncio.sleep(interval)
            try:
                alive = await store.heartbeat(idem_id, fence_token, lease_ttl, state_ttl)
            except Exception:  # noqa: BLE001 - 心跳异常按失活处理，宁可放弃不双跑
                alive = False
            if not alive:
                lost.set()
                return

    hb_task = asyncio.create_task(_heartbeat_loop())
    work_task = asyncio.create_task(coro)  # type: ignore[arg-type]
    lost_waiter = asyncio.create_task(lost.wait())
    try:
        done, _ = await asyncio.wait(
            {work_task, lost_waiter}, return_when=asyncio.FIRST_COMPLETED
        )
        if work_task in done:
            return work_task.result()
        # lease 丢失先于执行完成 → 主动 abort 当前任务
        work_task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await work_task
        raise LeaseLostError(idem_id)
    finally:
        hb_task.cancel()
        lost_waiter.cancel()
        for task in (hb_task, lost_waiter):
            with suppress(asyncio.CancelledError):
                await task
        if not work_task.done():
            work_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await work_task


async def consume_with_idempotency(
    message_body: dict[str, Any],
    headers: dict[str, Any],
    block: dict[str, Any],
    store: IdempotencyStore,
    execute_fn: ExecuteFn,
    *,
    message_id: str | None = None,
    reply_publisher: ReplyPublisher | None = None,
) -> str:
    """处理单条消息，返回处置动作：ack / backoff / nack。

    - ack：成功 / 真重复跳过 / 条件不命中跳过 / 被接管静默退出；
    - backoff：owner 存活或接管竞争失败 → 退避重入（决策 6，绝不裸 requeue）；
    - nack：执行失败 → TTL+DLX 重试（决策 6）。
    """
    retry_count = int(headers.get("x-retry-count", 0) or 0)
    business_id = extract_business_id(message_body, message_id)
    idem_id = build_idempotency_id(business_id, retry_count)
    state_ttl = max_execution_time(block) + DLQ_TOTAL_RETRY_WINDOW + 300
    mq_config = block.get("mq_config") or {}

    claim = await store.claim(idem_id, DEFAULT_LEASE_TTL, state_ttl)
    if not claim.claimed:
        if claim.existing_status == "SUCCESS":
            # 真重复投递：回复"至少一次"，下游按 snowflakeId 去重（决策 6/7）
            await _republish_reply_if_needed(
                store, idem_id, claim.existing_result, message_body,
                mq_config, business_id, reply_publisher, state_ttl,
            )
            return "ack"
        return "backoff"  # owner 存活 / 接管竞争失败 → 退避重入

    fence_token = claim.fence_token
    assert fence_token is not None

    # 条件求值（仅 jmespath/jsonpath，决策 1/10；非法表达式视为不命中，绝不 eval）
    expression = mq_config.get("condition_expression")
    if expression:
        language = mq_config.get("condition_language", "jmespath")
        try:
            satisfied = evaluate_condition(expression, language, message_body)
        except ConditionError:
            satisfied = False
        if not satisfied:
            await store.set_terminal(idem_id, fence_token, "SUCCESS", {"skipped": True}, state_ttl)
            return "ack"

    inputs = map_inputs(message_body, mq_config.get("input_mapping"))
    try:
        result = await _execute_with_lease(
            store, idem_id, fence_token, DEFAULT_LEASE_TTL, state_ttl, execute_fn(inputs)
        )
    except LeaseLostError:
        # 心跳 CAS 失败 = 已被接管：不写任何结果，退避重入（决策 6/7：绝不裸 requeue）
        return "backoff"
    except Exception:  # noqa: BLE001
        await store.set_terminal(idem_id, fence_token, "FAILED", None, state_ttl)
        return "nack"  # 走 TTL+DLX 重试（决策 6）

    # 写 SUCCESS 也 CAS 校验 fence_token；token 失配说明已被判死接管 → 丢弃自身结果（决策 7）
    if not await store.set_terminal(idem_id, fence_token, "SUCCESS", result, state_ttl):
        return "ack"

    if mq_config.get("reply_enabled") and reply_publisher is not None:
        reply = build_reply(
            result, message_body, mq_config.get("carry_fields"),
            dedup_business_id=business_id,
        )
        try:
            await reply_publisher(reply, mq_config)
            await store.mark_reply_sent(idem_id, fence_token, state_ttl)
        except Exception:  # noqa: BLE001 - 回复失败不回滚执行，靠重投/下游去重兜底
            logger.warning("reply_publish_failed idem_id=%s", idem_id)
    return "ack"


async def _republish_reply_if_needed(
    store: IdempotencyStore,
    idem_id: str,
    existing_result: Any,
    message_body: dict[str, Any],
    mq_config: dict[str, Any],
    business_id: str,
    reply_publisher: ReplyPublisher | None,
    state_ttl: int,
) -> None:
    """重复投递命中 SUCCESS 时补发回复（决策 6：回复至少一次，最终以下游去重为准）。"""
    if not mq_config.get("reply_enabled") or reply_publisher is None:
        return
    state = await store.get_state(idem_id)
    if state and state.get("reply_sent"):
        return  # 已发过，降重
    result = existing_result if existing_result is not None else (state or {}).get("result")
    if result is None or (isinstance(result, dict) and result.get("skipped")):
        return
    reply = build_reply(
        result, message_body, mq_config.get("carry_fields"),
        dedup_business_id=business_id,
    )
    with suppress(Exception):
        await reply_publisher(reply, mq_config)
        fence_token = (state or {}).get("fence_token")
        if fence_token is not None:
            await store.mark_reply_sent(idem_id, int(fence_token), state_ttl)


def queue_topology(block_id: str, retry_delay_ms: int) -> dict[str, Any]:
    """返回该 block 的完整队列拓扑声明（供部署时声明 / 本地消费者建队列）。"""
    return {
        "main": {"name": backoff_queue.main_queue(block_id),
                 "arguments": backoff_queue.queue_arguments(block_id, retry_delay_ms)},
        "dlq": {"name": backoff_queue.dlq_queue(block_id),
                "arguments": backoff_queue.dlq_arguments(block_id, retry_delay_ms)},
        "backoff": {"name": backoff_queue.backoff_queue(block_id),
                    "arguments": backoff_queue.backoff_arguments(block_id)},
        "dead": {"name": backoff_queue.dead_queue(block_id), "arguments": {}},
    }
