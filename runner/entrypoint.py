"""runner 镜像入口（决策 3.1 模型 A / 决策 11）。

两种角色（由环境变量 PYFLOW_RUNNER_ROLE 决定）：
- consumer：常驻 Block Deployment，自消费 block.{block_id}.queue（异步编舞）；
- invoke：暴露 /invoke 的常驻同步服务（min_replicas≥1）。

Block 代码不烧进镜像：启动时由 runner 从 MinIO 拉取对应 version_id 的 code_path 注入（决策 11）。
"""

from __future__ import annotations

import asyncio
import json
import os

from pyflow_runtime import RUNTIME_PROTOCOL_VERSION
from pyflow_runtime.executor import BlockExecutionError, execute_user_code

ROLE = os.getenv("PYFLOW_RUNNER_ROLE", "consumer")
BLOCK_ID = os.getenv("PYFLOW_BLOCK_ID", "")


def load_block_code() -> str:
    """从 MinIO 拉取 Block 代码（启动注入）。本地/降级用 PYFLOW_BLOCK_CODE 环境变量。"""
    inline = os.getenv("PYFLOW_BLOCK_CODE")
    if inline:
        return inline
    code_path = os.getenv("PYFLOW_CODE_PATH", "")
    if code_path and os.path.exists(code_path):
        with open(code_path, encoding="utf-8") as f:
            return f.read()
    return "def run(inputs):\n    return {'ok': True, 'inputs': inputs}\n"


def load_mq_config() -> dict:
    """从环境变量加载本 Block 的 mq_config（决策 14：敏感值走 Secret，此处仅非敏感配置）。"""
    raw = os.getenv("PYFLOW_MQ_CONFIG", "")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


async def make_execute_fn(code: str):
    """执行函数：返回用户 output dict，失败抛异常（由 pyflow_runtime 捕获写 FAILED）。

    与控制面 dev-local docker_executor 的契约一致，杜绝两侧结果形态分叉。
    """
    async def _execute(inputs: dict) -> dict:
        result = await asyncio.to_thread(execute_user_code, code, inputs)
        if result.get("error"):
            raise BlockExecutionError(result["error"])
        output = result.get("output")
        if isinstance(output, dict):
            return output
        return {"value": output} if output is not None else {}

    return _execute


async def run_consumer() -> None:
    """常驻消费者：消费本 Block 队列并执行（幂等/退避/重试/回复由 pyflow_runtime 提供）。

    决策 3.1 模型 A：本进程即 KEDA 扩缩对象；决策 6/7 的处置语义与 dev-local 控制面消费者一致。
    """
    import aio_pika
    import redis.asyncio as aioredis

    from pyflow_runtime.backoff_queue import backoff_queue, dead_queue, dlq_queue
    from pyflow_runtime.consumer import (
        consume_with_idempotency,
        protocol_compatible,
        queue_topology,
    )
    from pyflow_runtime.idempotency import IdempotencyStore
    from pyflow_runtime.reply_builder import render_reply_routing_key

    code = load_block_code()
    mq_config = load_mq_config()
    execute_fn = await make_execute_fn(code)
    redis = aioredis.from_url(os.getenv("PYFLOW_REDIS_URL", "redis://localhost:6379/0"),
                             decode_responses=True)
    store = IdempotencyStore(redis, os.getenv("HOSTNAME", "runner"))

    conn = await aio_pika.connect_robust(
        os.getenv("PYFLOW_RABBITMQ_URL", "amqp://pyflow:pyflow@localhost:5672//lhy-styon")
    )
    channel = await conn.channel()
    await channel.set_qos(prefetch_count=1)

    retry_delay_ms = int(mq_config.get("retry_delay_ms", 5000))
    max_retry = int(mq_config.get("max_retry", 3))
    topo = queue_topology(BLOCK_ID, retry_delay_ms=retry_delay_ms)
    main_q = await channel.declare_queue(
        topo["main"]["name"], durable=True, arguments=topo["main"]["arguments"]
    )
    await channel.declare_queue(topo["dlq"]["name"], durable=True, arguments=topo["dlq"]["arguments"])
    await channel.declare_queue(topo["backoff"]["name"], durable=True,
                                arguments=topo["backoff"]["arguments"])
    await channel.declare_queue(topo["dead"]["name"], durable=True)

    block_meta = {"compute_config": load_compute_config(), "mq_config": mq_config}
    persistent = aio_pika.DeliveryMode.PERSISTENT

    async def _republish(routing_key: str, body: bytes, headers: dict) -> None:
        await channel.default_exchange.publish(
            aio_pika.Message(body=body, headers=headers, content_type="application/json",
                             delivery_mode=persistent),
            routing_key=routing_key,
        )

    async def reply_publisher(reply: dict, cfg: dict) -> None:
        exchange_name = (cfg.get("reply_exchange") or "").strip()
        routing_key = render_reply_routing_key(
            cfg.get("reply_routing_key_template"), reply, BLOCK_ID
        )
        msg = aio_pika.Message(
            body=json.dumps(reply, ensure_ascii=False).encode("utf-8"),
            content_type="application/json", delivery_mode=persistent,
            headers={"pyflow-protocol": RUNTIME_PROTOCOL_VERSION},
        )
        if exchange_name:
            exchange = await channel.declare_exchange(
                exchange_name, aio_pika.ExchangeType.TOPIC, durable=True
            )
            await exchange.publish(msg, routing_key=routing_key or "#")
        else:
            await channel.default_exchange.publish(msg, routing_key=routing_key)

    async def on_message(message: "aio_pika.IncomingMessage") -> None:
        headers = dict(message.headers or {})
        # 协议版本校验（决策 3.1 点 5）：不兼容直接转死信归档
        if not protocol_compatible(headers):
            await _republish(dead_queue(BLOCK_ID), message.body, headers)
            await message.ack()
            return

        try:
            body = json.loads(message.body.decode("utf-8"))
        except json.JSONDecodeError:
            body = {}

        try:
            action = await consume_with_idempotency(
                body, headers, block_meta, store, execute_fn,
                message_id=message.message_id, reply_publisher=reply_publisher,
            )
        except Exception as exc:  # noqa: BLE001 - 兜底重投，绝不让 Pod 因单条消息崩
            print(f"[runner] handle_error block={BLOCK_ID} err={exc}", flush=True)
            action = "nack"

        retry_count = int(headers.get("x-retry-count", 0) or 0)
        if action == "ack":
            await message.ack()
        elif action == "backoff":
            await _republish(backoff_queue(BLOCK_ID), message.body, headers)
            await message.ack()
        else:  # nack → 递增 x-retry-count 重投 DLQ（TTL 延迟）；超限转死信归档
            if retry_count >= max_retry:
                await _republish(dead_queue(BLOCK_ID), message.body, headers)
            else:
                new_headers = dict(headers)
                new_headers["x-retry-count"] = str(retry_count + 1)
                await _republish(dlq_queue(BLOCK_ID), message.body, new_headers)
            await message.ack()

    print(f"[runner] consumer up block={BLOCK_ID} protocol={RUNTIME_PROTOCOL_VERSION}", flush=True)
    await main_q.consume(on_message)
    await asyncio.Future()


def load_compute_config() -> dict:
    """从环境变量加载 compute_config（用于 state_ttl 计算，长任务须显式声明 max_execution_time）。"""
    raw = os.getenv("PYFLOW_COMPUTE_CONFIG", "")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def run_invoke_server() -> None:
    """常驻同步服务：暴露 /invoke（min_replicas≥1，决策 4）。"""
    from fastapi import FastAPI
    import uvicorn

    code = load_block_code()
    app = FastAPI(title=f"pyflow-runner-{BLOCK_ID}")

    @app.get("/health/live")
    async def live():
        return {"status": "alive", "protocol": RUNTIME_PROTOCOL_VERSION}

    @app.post("/invoke")
    async def invoke(payload: dict):
        result = await asyncio.to_thread(execute_user_code, code, payload.get("inputs", {}))
        return result

    uvicorn.run(app, host="0.0.0.0", port=8000)


def main() -> None:
    if ROLE == "invoke":
        run_invoke_server()
    else:
        asyncio.run(run_consumer())


if __name__ == "__main__":
    main()
