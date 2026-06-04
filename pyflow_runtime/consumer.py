"""aio-pika 消费者（在 Block Pod 内运行，决策 3.1 模型 A）。

消费 block.{block_id}.queue，按决策 7 幂等状态机执行用户代码，
失败走 TTL+DLX 重试（决策 6），owner 存活/接管失败走退避重入。

prod：打进 runner 镜像，KEDA 据队列 ready 深度扩缩本 Deployment。
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Awaitable

from pyflow_runtime import backoff_queue
from pyflow_runtime.condition_engine import evaluate_condition
from pyflow_runtime.idempotency import (
    IdempotencyStore,
    build_idempotency_id,
    extract_business_id,
)
from pyflow_runtime.input_mapper import map_inputs
from pyflow_runtime.reply_builder import build_reply

POD_NAME = os.getenv("HOSTNAME", "local-runner")
DEFAULT_LEASE_TTL = 30
DLQ_TOTAL_RETRY_WINDOW = 60

ExecuteFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def max_execution_time(block_config: dict[str, Any]) -> int:
    return int((block_config.get("compute_config") or {}).get("max_execution_time", 3600))


async def consume_with_idempotency(
    message_body: dict[str, Any],
    headers: dict[str, Any],
    block: dict[str, Any],
    store: IdempotencyStore,
    execute_fn: ExecuteFn,
    *,
    message_id: str | None = None,
) -> str:
    """处理单条消息，返回处置动作：ack / backoff / nack。

    execute_fn(inputs) 由调用方注入（容器内即 pyflow_runtime.executor）。
    """
    retry_count = int(headers.get("x-retry-count", 0))
    business_id = extract_business_id(message_body, message_id)
    idem_id = build_idempotency_id(business_id, retry_count)
    state_ttl = max_execution_time(block) + DLQ_TOTAL_RETRY_WINDOW + 300

    claim = await store.claim(idem_id, DEFAULT_LEASE_TTL, state_ttl)
    if not claim.claimed:
        if claim.existing_status == "SUCCESS":
            return "ack"  # 真重复：复用已有结果（回复至少一次，下游去重）
        return "backoff"  # owner 存活或接管失败 → 退避重入

    fence_token = claim.fence_token

    mq_config = block.get("mq_config") or {}
    expression = mq_config.get("condition_expression")
    if expression:
        language = mq_config.get("condition_language", "jmespath")
        if not evaluate_condition(expression, language, message_body):
            await store.set_terminal(idem_id, fence_token, "SUCCESS", {"skipped": True}, state_ttl)
            return "ack"  # 条件不满足，跳过

    inputs = map_inputs(message_body, mq_config.get("input_mapping"))
    try:
        result = await execute_fn(inputs)
    except Exception:  # noqa: BLE001
        await store.set_terminal(idem_id, fence_token, "FAILED", None, state_ttl)
        return "nack"  # 走 TTL+DLX 重试

    if await store.set_terminal(idem_id, fence_token, "SUCCESS", result, state_ttl):
        if mq_config.get("reply_enabled"):
            _ = build_reply(
                result, message_body, mq_config.get("carry_fields"),
                dedup_business_id=business_id,
            )
            # 实际 publish 由调用方在返回 "ack" 后据 mq_config 完成
        return "ack"
    # token 失配：已被接管，静默退出
    return "ack"


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
