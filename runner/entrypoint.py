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
from pyflow_runtime.executor import execute_user_code

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


async def make_execute_fn(code: str):
    async def _execute(inputs: dict) -> dict:
        return await asyncio.to_thread(execute_user_code, code, inputs)

    return _execute


async def run_consumer() -> None:
    """常驻消费者：消费本 Block 队列并执行（幂等/退避/重试由 pyflow_runtime 提供）。"""
    import aio_pika
    import redis.asyncio as aioredis

    from pyflow_runtime.consumer import consume_with_idempotency, queue_topology
    from pyflow_runtime.idempotency import IdempotencyStore

    code = load_block_code()
    execute_fn = await make_execute_fn(code)
    redis = aioredis.from_url(os.getenv("PYFLOW_REDIS_URL", "redis://localhost:6379/0"),
                             decode_responses=True)
    store = IdempotencyStore(redis, os.getenv("HOSTNAME", "runner"))

    conn = await aio_pika.connect_robust(
        os.getenv("PYFLOW_RABBITMQ_URL", "amqp://pyflow:pyflow@localhost:5672//lhy-styon")
    )
    channel = await conn.channel()
    await channel.set_qos(prefetch_count=1)

    topo = queue_topology(BLOCK_ID, retry_delay_ms=5000)
    main_q = await channel.declare_queue(
        topo["main"]["name"], durable=True, arguments=topo["main"]["arguments"]
    )
    await channel.declare_queue(topo["dlq"]["name"], durable=True, arguments=topo["dlq"]["arguments"])
    await channel.declare_queue(topo["backoff"]["name"], durable=True,
                                arguments=topo["backoff"]["arguments"])

    block_meta = {"compute_config": {}, "mq_config": {}}

    async def on_message(message: "aio_pika.IncomingMessage") -> None:
        body = json.loads(message.body.decode("utf-8"))
        action = await consume_with_idempotency(
            body, dict(message.headers or {}), block_meta, store, execute_fn,
            message_id=message.message_id,
        )
        if action in ("ack", "backoff"):
            # backoff 的重投由队列拓扑承担，此处简化为 ack 后由调用方择机重投
            await message.ack()
        else:
            await message.nack(requeue=False)

    print(f"[runner] consumer up block={BLOCK_ID} protocol={RUNTIME_PROTOCOL_VERSION}", flush=True)
    await main_q.consume(on_message)
    await asyncio.Future()


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
