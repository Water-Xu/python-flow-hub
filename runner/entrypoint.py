"""runner 镜像入口（决策 3.1 重写为 Flow 级模型 A / 决策 11）。

两种角色（由环境变量 PYFLOW_RUNNER_ROLE 决定）：
- invoke：暴露 /invoke 的常驻同步服务（min_replicas≥1），被 Flow 编排按 DAG 调用；
- flow_consumer：接口/Flow 级 MQ 消费者，消费 flow.{api_id}.queue，
  收到消息后用 pyflow_runtime.flow_dag 驱动整条 DAG（调各块 invoke Service），
  KEDA 按该队列深度扩缩本 Deployment。

Block 代码不烧进镜像：invoke 角色启动时由 runner 从 MinIO 拉取对应 version_id 的 code_path 注入（决策 11）。
"""

from __future__ import annotations

import asyncio
import json
import os

from pyflow_runtime import RUNTIME_PROTOCOL_VERSION
from pyflow_runtime.executor import BlockExecutionError, execute_user_code

ROLE = os.getenv("PYFLOW_RUNNER_ROLE", "invoke")
BLOCK_ID = os.getenv("PYFLOW_BLOCK_ID", "")
API_ID = os.getenv("PYFLOW_API_ID", "")
NAMESPACE = os.getenv("PYFLOW_NAMESPACE", "pyflow-blocks")
INVOKE_PORT = 8000


def _load_code_from_minio(code_path: str) -> str | None:
    """按对象 key 从 MinIO 拉取 Block 代码（决策 11：代码不烧进镜像，启动注入）。

    连接信息由中间件 Secret 经 envFrom 注入（MINIO_ENDPOINT/ACCESS_KEY/SECRET_KEY），
    bucket / secure 由控制面随 invoke Deployment 注入（PYFLOW_MINIO_BUCKET/PYFLOW_MINIO_SECURE）。
    任何失败返回 None，由调用方回落 stub（仅启动期，不影响已加载实例）。
    """
    endpoint = os.getenv("MINIO_ENDPOINT", "")
    if not endpoint:
        return None
    try:
        from minio import Minio

        client = Minio(
            endpoint,
            access_key=os.getenv("MINIO_ACCESS_KEY", ""),
            secret_key=os.getenv("MINIO_SECRET_KEY", ""),
            secure=os.getenv("PYFLOW_MINIO_SECURE", "false").lower() == "true",
        )
        bucket = os.getenv("PYFLOW_MINIO_BUCKET", "pyflow-versions")
        resp = client.get_object(bucket, code_path)
        try:
            return resp.read().decode("utf-8")
        finally:
            resp.close()
            resp.release_conn()
    except Exception as exc:  # noqa: BLE001 - 拉取失败回落 stub，并打印可诊断信息
        print(
            f"[runner] load_block_code from minio failed path={code_path} err={exc}",
            flush=True,
        )
        return None


def load_block_code() -> str:
    """加载 Block 代码：内联 env > 本地文件 > MinIO 对象 > stub 兜底（决策 11）。"""
    inline = os.getenv("PYFLOW_BLOCK_CODE")
    if inline:
        return inline
    code_path = os.getenv("PYFLOW_CODE_PATH", "")
    if code_path:
        # 本地文件（dev / 测试挂载）优先
        if os.path.exists(code_path):
            with open(code_path, encoding="utf-8") as f:
                return f.read()
        # 否则视为 MinIO 对象 key，从对象存储拉取真实代码
        code = _load_code_from_minio(code_path)
        if code is not None:
            return code
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
    支持一脚本多入口函数：每条消息可携带 entrypoint，未指定时默认 run。
    """
    async def _execute(inputs: dict, entrypoint: str = "run") -> dict:
        result = await asyncio.to_thread(execute_user_code, code, inputs, entrypoint or "run")
        if result.get("error"):
            raise BlockExecutionError(result["error"])
        output = result.get("output")
        if isinstance(output, dict):
            return output
        return {"value": output} if output is not None else {}

    return _execute


def load_flow_dag() -> dict:
    """从环境变量加载部署时内嵌的 DAG 快照（含每个块节点的 invoke Service 名）。"""
    raw = os.getenv("PYFLOW_FLOW_DAG", "")
    if not raw:
        return {"nodes": [], "edges": []}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"nodes": [], "edges": []}


async def _invoke_block_service(service: str, inputs: dict, entrypoint: str) -> dict:
    """调用某块的 invoke Service /invoke（同命名空间内 ClusterIP）。"""
    import httpx

    url = f"http://{service}.{NAMESPACE}:{INVOKE_PORT}/invoke"
    async with httpx.AsyncClient(timeout=3600) as client:
        resp = await client.post(url, json={"inputs": inputs, "entrypoint": entrypoint})
        resp.raise_for_status()
        data = resp.json()
    if data.get("error"):
        raise BlockExecutionError(data["error"])
    output = data.get("output")
    if isinstance(output, dict):
        return output
    return {"value": output} if output is not None else {}


def make_flow_execute_fn(dag: dict):
    """构造 execute_fn：一条 MQ 消息 → 驱动整条 DAG（调各块 invoke Service），返回 {node_id: output}。"""
    from pyflow_runtime.flow_dag import run_flow

    nodes = dag.get("nodes", [])
    edges = dag.get("edges", [])

    async def node_executor(node: dict, node_inputs: dict) -> dict:
        service = node.get("service")
        if not service:
            raise BlockExecutionError(f"node {node.get('id')} missing invoke service")
        entrypoint = (node.get("config") or {}).get("entrypoint") or "run"
        return await _invoke_block_service(service, node_inputs, entrypoint)

    async def _execute(inputs: dict) -> dict:
        return await run_flow(nodes, edges, inputs, node_executor)

    return _execute


async def run_flow_consumer() -> None:
    """接口/Flow 级消费者：消费 flow.{api_id}.queue，驱动整条 DAG（决策 3.1 重写为 Flow 级模型 A）。

    幂等/条件/映射/退避/重试/回复语义由 pyflow_runtime 提供，与 dev-local 控制面消费者完全一致；
    execute_fn 不再执行单块，而是用 pyflow_runtime.flow_dag.run_flow 驱动整条 DAG。
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

    mq_config = load_mq_config()
    dag = load_flow_dag()
    execute_fn = make_flow_execute_fn(dag)
    redis = aioredis.from_url(
        os.getenv("PYFLOW_REDIS_URL") or os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        decode_responses=True,
    )
    store = IdempotencyStore(redis, os.getenv("HOSTNAME", "flow-consumer"))

    conn = await aio_pika.connect_robust(
        os.getenv("PYFLOW_RABBITMQ_URL")
        or os.getenv("RABBITMQ_URL", "amqp://pyflow:pyflow@localhost:5672//lhy-styon")
    )
    channel = await conn.channel()
    await channel.set_qos(prefetch_count=1)

    retry_delay_ms = int(mq_config.get("retry_delay_ms", 5000))
    max_retry = int(mq_config.get("max_retry", 3))
    topo = queue_topology(API_ID, retry_delay_ms=retry_delay_ms)
    main_q = await channel.declare_queue(
        topo["main"]["name"], durable=True, arguments=topo["main"]["arguments"]
    )
    await channel.declare_queue(topo["dlq"]["name"], durable=True, arguments=topo["dlq"]["arguments"])
    await channel.declare_queue(topo["backoff"]["name"], durable=True,
                                arguments=topo["backoff"]["arguments"])
    await channel.declare_queue(topo["dead"]["name"], durable=True)

    # Flow 级 state_ttl：整流可能较长，给足窗口（compute_config 可显式抬高 max_execution_time）
    flow_meta = {"compute_config": load_compute_config(), "mq_config": mq_config}
    persistent = aio_pika.DeliveryMode.PERSISTENT

    async def _republish(routing_key: str, body: bytes, headers: dict) -> None:
        await channel.default_exchange.publish(
            aio_pika.Message(body=body, headers=headers, content_type="application/json",
                             delivery_mode=persistent),
            routing_key=routing_key,
        )

    # 缓存已声明的 reply exchange，避免每条回复都做一次 declare 往返
    _reply_exchanges: dict = {}

    async def reply_publisher(reply: dict, cfg: dict) -> None:
        exchange_name = (cfg.get("reply_exchange") or "").strip()
        routing_key = render_reply_routing_key(
            cfg.get("reply_routing_key_template"), reply, API_ID
        )
        msg = aio_pika.Message(
            body=json.dumps(reply, ensure_ascii=False).encode("utf-8"),
            content_type="application/json", delivery_mode=persistent,
            headers={"pyflow-protocol": RUNTIME_PROTOCOL_VERSION},
        )
        if exchange_name:
            exchange = _reply_exchanges.get(exchange_name)
            if exchange is None:
                exchange = await channel.declare_exchange(
                    exchange_name, aio_pika.ExchangeType.TOPIC, durable=True
                )
                _reply_exchanges[exchange_name] = exchange
            await exchange.publish(msg, routing_key=routing_key or "#")
        else:
            await channel.default_exchange.publish(msg, routing_key=routing_key)

    async def on_message(message: "aio_pika.IncomingMessage") -> None:
        headers = dict(message.headers or {})
        if not protocol_compatible(headers):
            await _republish(dead_queue(API_ID), message.body, headers)
            await message.ack()
            return

        try:
            body = json.loads(message.body.decode("utf-8"))
        except json.JSONDecodeError:
            body = {}

        try:
            action = await consume_with_idempotency(
                body, headers, flow_meta, store, execute_fn,
                message_id=message.message_id, reply_publisher=reply_publisher,
            )
        except Exception as exc:  # noqa: BLE001 - 兜底重投，绝不让 Pod 因单条消息崩
            print(f"[runner] flow_consumer handle_error api={API_ID} err={exc}", flush=True)
            action = "nack"

        retry_count = int(headers.get("x-retry-count", 0) or 0)
        if action == "ack":
            await message.ack()
        elif action == "backoff":
            await _republish(backoff_queue(API_ID), message.body, headers)
            await message.ack()
        else:  # nack → 递增 x-retry-count 重投 DLQ（TTL 延迟）；超限转死信归档
            if retry_count >= max_retry:
                await _republish(dead_queue(API_ID), message.body, headers)
            else:
                new_headers = dict(headers)
                new_headers["x-retry-count"] = str(retry_count + 1)
                await _republish(dlq_queue(API_ID), message.body, new_headers)
            await message.ack()

    print(f"[runner] flow_consumer up api={API_ID} protocol={RUNTIME_PROTOCOL_VERSION}", flush=True)
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
        result = await asyncio.to_thread(
            execute_user_code, code, payload.get("inputs", {}),
            payload.get("entrypoint", "run"),
        )
        return result

    uvicorn.run(app, host="0.0.0.0", port=8000)


def main() -> None:
    if ROLE == "flow_consumer":
        asyncio.run(run_flow_consumer())
    else:
        run_invoke_server()


if __name__ == "__main__":
    main()
