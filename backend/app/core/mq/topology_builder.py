"""RabbitMQ 队列/交换机拓扑声明（决策 6/10）。

控制面侧：只做拓扑生成 + 声明，不常驻消费生产队列（决策 3.1 模型 A）。
dev-local 模式：在启动消费者前调用 declare_block_topology 声明队列。
prod（Phase 4）：manifest_generator 生成 binding 配置，由 Block Deployment 自己声明。
"""

from __future__ import annotations

from typing import Any

import aio_pika


async def declare_block_topology(
    channel: aio_pika.abc.AbstractChannel,
    block_id: str,
    retry_delay_ms: int = 5000,
) -> dict[str, Any]:
    """声明一个 Block 的完整队列拓扑：主队列 + DLQ + 退避队列 + 死信归档队列。

    返回声明的队列名称映射，供消费者绑定。
    """
    from pyflow_runtime.backoff_queue import (
        dead_queue,
        dlq_arguments,
        dlq_queue,
        main_queue,
        queue_arguments,
    )
    from pyflow_runtime.backoff_queue import backoff_queue as backoff_q
    from pyflow_runtime.backoff_queue import backoff_arguments

    main_q = main_queue(block_id)
    dlq_q = dlq_queue(block_id)
    backoff_q_name = backoff_q(block_id)
    dead_q = dead_queue(block_id)

    # 主队列：失败 nack → DLX → DLQ
    await channel.declare_queue(
        main_q,
        durable=True,
        arguments=queue_arguments(block_id, retry_delay_ms),
    )
    # DLQ：TTL 后重回主队列
    await channel.declare_queue(
        dlq_q,
        durable=True,
        arguments=dlq_arguments(block_id, retry_delay_ms),
    )
    # 退避队列：短 TTL 后重回主队列（防 KEDA 抖动，决策 6）
    await channel.declare_queue(
        backoff_q_name,
        durable=True,
        arguments=backoff_arguments(block_id),
    )
    # 死信归档：超过 max_retry 后路由到此，永久保留
    await channel.declare_queue(dead_q, durable=True)

    return {
        "main": main_q,
        "dlq": dlq_q,
        "backoff": backoff_q_name,
        "dead": dead_q,
    }


async def publish_message(
    channel: aio_pika.abc.AbstractChannel,
    block_id: str,
    payload: dict[str, Any],
    snowflake_id: str | None = None,
    retry_count: int = 0,
) -> None:
    """向 block 主队列发布一条消息（含协议头）。"""
    import json
    from pyflow_runtime import RUNTIME_PROTOCOL_VERSION
    from pyflow_runtime.backoff_queue import main_queue

    headers: dict[str, Any] = {
        "x-retry-count": str(retry_count),
        "pyflow-protocol": RUNTIME_PROTOCOL_VERSION,
    }
    if snowflake_id:
        if "header" not in payload:
            payload = {"header": {"snowflakeId": snowflake_id}, **payload}

    message = aio_pika.Message(
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        content_type="application/json",
        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        headers=headers,
    )
    await channel.default_exchange.publish(message, routing_key=main_queue(block_id))
