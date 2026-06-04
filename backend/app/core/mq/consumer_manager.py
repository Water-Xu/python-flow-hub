"""dev-local 消费者管理器（决策 3.1 重写为 Flow 级模型 A）。

生产环境：消费者 = Flow-Consumer Pod 内 pyflow_runtime.consumer，由 KEDA 按 flow.{api_id}.queue 扩缩。
dev-local：控制面按已发布接口（PublishedApi）启动轻量 aio-pika 消费者，
           收到消息后驱动整条 Flow 编排（run_flow + docker_executor），落 FlowRun。
           lifespan 启动/停止，逐接口管理，不常驻消费生产队列（只 dev 调试用）。

与 runner 镜像（prod）共用同一套 pyflow_runtime 幂等/条件/回复/退避语义，杜绝逻辑分叉。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import aio_pika

from app.config import get_settings
from app.core.mq.topology_builder import declare_flow_topology, publish_reply
from app.observability.logging import get_logger
from app.observability.metrics import MQ_CONSUMED, MQ_QUEUE_DEPTH, MQ_REPLY_PUBLISHED

logger = get_logger("pyflow.mq")
POD_NAME = os.getenv("HOSTNAME", "local-runner")
_PERSISTENT = aio_pika.DeliveryMode.PERSISTENT


@dataclass
class ConsumerStatus:
    api_id: str
    api_name: str
    status: str = "stopped"           # stopped | connecting | running | error
    queue_depth: int = 0
    dlq_depth: int = 0
    processed: int = 0
    errors: int = 0
    last_error: str | None = None
    started_at: float | None = None
    error_detail: str | None = None


class ConsumerManager:
    """管理 dev-local 下各 mq/both 接口的 aio-pika 消费者生命周期。"""

    def __init__(self) -> None:
        self._consumers: dict[str, ConsumerStatus] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._api_cfgs: dict[str, dict[str, Any]] = {}
        self._connection: aio_pika.abc.AbstractRobustConnection | None = None
        self._channel: aio_pika.abc.AbstractChannel | None = None
        self._redis: Any = None
        self._settings = get_settings()
        self._running = False
        # 复用单个 HTTP 客户端 + 缓存解析后的 Management 连接信息，避免每次轮询队列深度都重建连接池
        self._http: Any = None
        self._mgmt_conn: tuple[str | None, str, tuple[str, str]] | None = None

    # ── 连接管理 ─────────────────────────────────────────────────────────────

    async def connect(self) -> bool:
        """建立 RabbitMQ + Redis 连接；连接失败只记日志不崩溃（dev 可选）。"""
        try:
            self._connection = await aio_pika.connect_robust(self._settings.rabbitmq_url)
            self._channel = await self._connection.channel()
            await self._channel.set_qos(prefetch_count=1)
            logger.info("mq_connected", url=self._settings.rabbitmq_url[:40])
        except Exception as exc:  # noqa: BLE001
            logger.warning("mq_connect_failed", error=str(exc)[:200])
            return False

        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(
                self._settings.redis_url, decode_responses=True,
                socket_connect_timeout=3,
            )
            await self._redis.ping()
            logger.info("redis_connected")
        except Exception as exc:  # noqa: BLE001
            logger.warning("redis_connect_failed_idempotency_disabled", error=str(exc)[:200])
            self._redis = None

        self._running = True
        return True

    async def disconnect(self) -> None:
        self._running = False
        for task in list(self._tasks.values()):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        if self._connection and not self._connection.is_closed:
            await self._connection.close()
        if self._redis:
            with suppress(Exception):
                await self._redis.aclose()
        if self._http is not None:
            with suppress(Exception):
                await self._http.aclose()
            self._http = None
        logger.info("mq_disconnected")

    def _mgmt(self) -> tuple[str | None, str, tuple[str, str]]:
        """惰性解析并缓存 RabbitMQ Management API 连接信息 (base_url, vhost, auth)。"""
        if self._mgmt_conn is None:
            url = self._settings.rabbitmq_url
            self._mgmt_conn = (_amqp_to_mgmt(url), _extract_vhost(url), _extract_auth(url))
        return self._mgmt_conn

    def _http_client(self) -> Any:
        """惰性创建并复用单个 httpx.AsyncClient（连接池复用，省去每次轮询的握手）。"""
        import httpx
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=5)
        return self._http

    # ── 消费者生命周期 ────────────────────────────────────────────────────────

    def get_status(self, api_id: str) -> ConsumerStatus | None:
        return self._consumers.get(api_id)

    def all_statuses(self) -> list[dict]:
        return [
            {
                "api_id": s.api_id,
                "api_name": s.api_name,
                "status": s.status,
                "queue_depth": s.queue_depth,
                "dlq_depth": s.dlq_depth,
                "processed": s.processed,
                "errors": s.errors,
                "last_error": s.last_error,
                "started_at": s.started_at,
            }
            for s in self._consumers.values()
        ]

    async def start_consumer(
        self,
        api_id: str,
        api_name: str,
        mq_config: dict[str, Any],
    ) -> bool:
        """启动指定接口的 Flow 级消费者（已运行则重启）。"""
        await self.stop_consumer(api_id)

        if not self._connection or self._connection.is_closed:
            ok = await self.connect()
            if not ok:
                return False

        status = ConsumerStatus(api_id=api_id, api_name=api_name, status="connecting")
        self._consumers[api_id] = status
        api_cfg = {"mq_config": mq_config or {}, "compute_config": {}}
        self._api_cfgs[api_id] = api_cfg

        task = asyncio.create_task(
            self._consume_loop(api_id, api_cfg, status),
            name=f"consumer-{api_id}",
        )
        self._tasks[api_id] = task
        return True

    async def stop_consumer(self, api_id: str) -> None:
        task = self._tasks.pop(api_id, None)
        if task and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if api_id in self._consumers:
            self._consumers[api_id].status = "stopped"

    # ── 核心消费循环 ──────────────────────────────────────────────────────────

    async def _consume_loop(
        self,
        api_id: str,
        api_cfg: dict[str, Any],
        status: ConsumerStatus,
    ) -> None:
        from pyflow_runtime.idempotency import IdempotencyStore

        retry_delay_ms = int((api_cfg.get("mq_config") or {}).get("retry_delay_ms", 5000))

        try:
            channel = await self._connection.channel()
            await channel.set_qos(prefetch_count=1)

            topology = await declare_flow_topology(channel, api_id, retry_delay_ms)
            queue = await channel.get_queue(topology["main"])

            store: IdempotencyStore | None = None
            if self._redis:
                store = IdempotencyStore(self._redis, POD_NAME)

            status.status = "running"
            status.started_at = time.time()
            logger.info("consumer_started", api_id=api_id, idempotency=bool(store))

            async with queue.iterator() as iter_:
                async for message in iter_:
                    try:
                        await self._handle_message(
                            message, api_id, api_cfg, store, status, channel
                        )
                    except Exception as exc:  # noqa: BLE001 - 处理器兜底，绝不让循环崩
                        status.errors += 1
                        status.last_error = str(exc)[:200]
                        logger.error("message_handle_error", api_id=api_id,
                                     error=str(exc)[:200])
                        await self._safety_retry(channel, api_id, message, api_cfg)

        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            status.status = "error"
            status.error_detail = str(exc)[:300]
            logger.error("consumer_error", api_id=api_id, error=str(exc)[:200])

    async def _handle_message(
        self,
        message: aio_pika.abc.AbstractIncomingMessage,
        api_id: str,
        api_cfg: dict[str, Any],
        store: Any,
        status: ConsumerStatus,
        channel: aio_pika.abc.AbstractChannel,
    ) -> None:
        from pyflow_runtime.consumer import consume_with_idempotency, protocol_compatible

        try:
            body = json.loads(message.body.decode("utf-8"))
        except Exception:  # noqa: BLE001
            body = {}

        headers = dict(message.headers or {})
        mq_cfg = api_cfg.get("mq_config") or {}
        retry_count = int(headers.get("x-retry-count", 0) or 0)
        max_retry = int(mq_cfg.get("max_retry", 3))

        # 协议版本校验（决策 3.1 点 5）：不兼容直接转死信归档，绝不按旧契约执行
        if not protocol_compatible(headers):
            await self._publish_dead(channel, api_id, message, headers)
            await message.ack()
            status.errors += 1
            status.last_error = "protocol mismatch"
            MQ_CONSUMED.labels(block_id=api_id, action="protocol_reject").inc()
            return

        reply_publisher = self._make_reply_publisher(channel, api_id)

        if store:
            # consume_with_idempotency 与执行单元无关：execute_fn 驱动整条 Flow
            action = await consume_with_idempotency(
                message_body=body,
                headers=headers,
                block=api_cfg,
                store=store,
                execute_fn=lambda inputs: self._execute_flow(api_id, inputs),
                message_id=message.message_id,
                reply_publisher=reply_publisher,
            )
        else:
            action = await self._exec_without_idempotency(
                body, api_id, mq_cfg, message.message_id, reply_publisher, status
            )

        if action == "ack":
            await message.ack()
            status.processed += 1
        elif action == "backoff":
            await self._publish_backoff(channel, api_id, message, headers)
            await message.ack()
        else:  # nack → 递增 x-retry-count 重投 DLQ（TTL 延迟回主队列），超限转死信归档
            if retry_count >= max_retry:
                await self._publish_dead(channel, api_id, message, headers)
            else:
                await self._publish_retry(channel, api_id, message, headers, retry_count + 1)
            await message.ack()
            status.errors += 1
        MQ_CONSUMED.labels(block_id=api_id, action=action).inc()

    async def _exec_without_idempotency(
        self, body: dict, api_id: str, mq_cfg: dict,
        message_id: str | None, reply_publisher: Any, status: ConsumerStatus,
    ) -> str:
        """Redis 不可用时的降级路径：条件过滤 + 映射 + 整流执行 + 手动回复（无幂等去重，靠下游兜底）。"""
        from pyflow_runtime.condition_engine import ConditionError, evaluate_condition
        from pyflow_runtime.idempotency import extract_business_id
        from pyflow_runtime.input_mapper import map_inputs
        from pyflow_runtime.reply_builder import build_reply

        expression = mq_cfg.get("condition_expression")
        if expression:
            try:
                if not evaluate_condition(expression, mq_cfg.get("condition_language", "jmespath"), body):
                    return "ack"
            except ConditionError:
                return "ack"
        try:
            inputs = map_inputs(body, mq_cfg.get("input_mapping"))
            result = await self._execute_flow(api_id, inputs)
            if mq_cfg.get("reply_enabled") and reply_publisher is not None:
                bid = extract_business_id(body, message_id)
                reply = build_reply(result, body, mq_cfg.get("carry_fields"), dedup_business_id=bid)
                await reply_publisher(reply, mq_cfg)
            return "ack"
        except Exception as exc:  # noqa: BLE001
            status.last_error = str(exc)[:200]
            return "nack"

    def _make_reply_publisher(self, channel: aio_pika.abc.AbstractChannel, api_id: str):
        async def _publish(reply: dict[str, Any], mq_config: dict[str, Any]) -> None:
            await publish_reply(channel, mq_config, reply, api_id=api_id)
            MQ_REPLY_PUBLISHED.labels(block_id=api_id).inc()

        return _publish

    async def run_flow_for_api(self, api_id: str, inputs: dict) -> dict:
        """对外暴露：用给定 inputs 同步驱动接口对应 Flow（供 Mock 测试 test-run 复用）。"""
        return await self._execute_flow(api_id, inputs)

    async def _execute_flow(self, api_id: str, inputs: dict) -> dict:
        """收到一条 MQ 消息后驱动整条 Flow 编排（dev-local：control plane docker_executor）。

        每次取接口 active_flow_id 的最新 DAG，落 FlowRun，按拓扑序内存传递 output→input，
        返回 {node_id: output}（作为回复 result）。
        """
        from app.core.execution_service import execute_block
        from app.core.flow.flow_runner import run_flow
        from app.db import get_session_factory
        from app.errors import (
            PYFLOW_BLOCK_NOT_FOUND,
            PYFLOW_EXEC_INPUT_INVALID,
            PYFLOW_EXEC_SANDBOX_ERROR,
            BusinessException,
        )
        from app.models.api_portal import PublishedApi
        from app.models.block import Block
        from app.models.execution import FlowRun
        from app.models.flow import FlowEdge, FlowNode
        from sqlalchemy import select

        async with get_session_factory()() as session:
            api = await session.get(PublishedApi, api_id)
            if api is None:
                raise RuntimeError(f"published api not found: {api_id}")
            flow_id = api.active_flow_id or api.flow_id

            nodes = [
                {"id": n.id, "node_type": n.node_type, "block_id": n.block_id,
                 "config": n.config, "position": n.position}
                for n in (await session.execute(
                    select(FlowNode).where(FlowNode.flow_id == flow_id)
                )).scalars().all()
            ]
            edges = [
                {"id": e.id, "source_node_id": e.source_node_id,
                 "target_node_id": e.target_node_id,
                 "source_port": e.source_port, "target_port": e.target_port}
                for e in (await session.execute(
                    select(FlowEdge).where(FlowEdge.flow_id == flow_id)
                )).scalars().all()
            ]

            flow_run = FlowRun(
                flow_id=flow_id, status="running",
                dag_snapshot={"nodes": nodes, "edges": edges}, node_states={},
            )
            session.add(flow_run)
            await session.commit()
            await session.refresh(flow_run)

            # 一次 IN 查询批量装载所有块，避免按节点 N+1 逐个 session.get
            block_ids = {n["block_id"] for n in nodes if n.get("block_id")}
            block_cache: dict[str, Block] = {}
            if block_ids:
                rows = (await session.execute(
                    select(Block).where(Block.id.in_(block_ids))
                )).scalars().all()
                block_cache = {b.id: b for b in rows}
                missing = block_ids - block_cache.keys()
                if missing:
                    raise BusinessException(PYFLOW_BLOCK_NOT_FOUND, next(iter(missing)))

            async def node_executor(node: dict, node_inputs: dict) -> dict:
                bid = node.get("block_id")
                if not bid:
                    raise BusinessException(
                        PYFLOW_EXEC_INPUT_INVALID, f"node {node.get('id')} missing block_id"
                    )
                block = block_cache[bid]
                entrypoint = (node.get("config") or {}).get("entrypoint") or "run"
                record = await execute_block(
                    session, block_id=block.id, code=block.draft_code or "",
                    inputs=node_inputs, login_id=api.owner_login_id,
                    flow_run_id=flow_run.id, entrypoint=entrypoint,
                )
                if record.status != "success":
                    detail = (record.stderr or "block execution failed").strip()[:500]
                    raise BusinessException(PYFLOW_EXEC_SANDBOX_ERROR, detail)
                return record.output if isinstance(record.output, dict) else {"value": record.output}

            async def checkpoint(node_id: str, status: str, output: dict) -> None:
                states = dict(flow_run.node_states)
                states[node_id] = {"status": status}
                flow_run.node_states = states
                await session.commit()

            try:
                outputs = await run_flow(nodes, edges, inputs, node_executor, checkpoint)
                flow_run.status = "succeeded"
                await session.commit()
            except Exception:
                flow_run.status = "failed"
                await session.commit()
                raise
            return outputs

    # ── 重投 / 退避 / 死信发布 ──────────────────────────────────────────────────

    @staticmethod
    def _copy_message(body: bytes, headers: dict) -> aio_pika.Message:
        return aio_pika.Message(
            body=body,
            headers=headers,
            content_type="application/json",
            delivery_mode=_PERSISTENT,
        )

    async def _publish_retry(
        self, channel: aio_pika.abc.AbstractChannel, api_id: str,
        message: aio_pika.abc.AbstractIncomingMessage, headers: dict, new_retry_count: int,
    ) -> None:
        """重投到 DLQ（带 TTL，到期 DLX 回主队列）并递增 x-retry-count。

        手动 republish 而非依赖 nack→DLX：死信路由不会修改自定义 header，
        裸 nack 会导致 x-retry-count 永远为 0、max_retry 永不触发、死信归档永不命中（决策 6）。
        """
        from pyflow_runtime.backoff_queue import dlq_queue

        new_headers = dict(headers)
        new_headers["x-retry-count"] = str(new_retry_count)
        await channel.default_exchange.publish(
            self._copy_message(message.body, new_headers), routing_key=dlq_queue(api_id)
        )

    async def _publish_dead(
        self, channel: aio_pika.abc.AbstractChannel, api_id: str,
        message: aio_pika.abc.AbstractIncomingMessage, headers: dict,
    ) -> None:
        """超过 max_retry / 协议不兼容 → 路由到死信归档队列，永久保留供排查（决策 6）。"""
        from pyflow_runtime.backoff_queue import dead_queue

        await channel.default_exchange.publish(
            self._copy_message(message.body, dict(headers)), routing_key=dead_queue(api_id)
        )

    async def _publish_backoff(
        self, channel: aio_pika.abc.AbstractChannel, api_id: str,
        message: aio_pika.abc.AbstractIncomingMessage, headers: dict,
    ) -> None:
        """owner 存活 / 接管竞争失败 → 退避重入（短 TTL，不计入主队列 ready 深度，防 KEDA 抖动）。"""
        from pyflow_runtime.backoff_queue import backoff_queue as backoff_q

        await channel.default_exchange.publish(
            self._copy_message(message.body, dict(headers)), routing_key=backoff_q(api_id)
        )

    async def _safety_retry(
        self, channel: aio_pika.abc.AbstractChannel, api_id: str,
        message: aio_pika.abc.AbstractIncomingMessage, api_cfg: dict,
    ) -> None:
        """处理器自身异常时的兜底重投，保证消息不丢、不无限堆积。"""
        with suppress(Exception):
            headers = dict(message.headers or {})
            retry_count = int(headers.get("x-retry-count", 0) or 0)
            max_retry = int((api_cfg.get("mq_config") or {}).get("max_retry", 3))
            if retry_count >= max_retry:
                await self._publish_dead(channel, api_id, message, headers)
            else:
                await self._publish_retry(channel, api_id, message, headers, retry_count + 1)
            await message.ack()

    # ── 队列深度查询 ──────────────────────────────────────────────────────────

    async def fetch_queue_depth(self, api_id: str) -> dict[str, int]:
        """通过 RabbitMQ Management HTTP API 查询队列深度。"""
        from pyflow_runtime.backoff_queue import dlq_queue, main_queue

        mgmt_base, vhost, auth = self._mgmt()
        if not mgmt_base:
            return {"main": 0, "dlq": 0}

        client = self._http_client()
        depths: dict[str, int] = {}
        for qname_key, queue_fn in [("main", main_queue), ("dlq", dlq_queue)]:
            qname = queue_fn(api_id)
            try:
                url = f"{mgmt_base}/api/queues/{vhost}/{qname}"
                resp = await client.get(url, auth=auth)
                if resp.status_code == 200:
                    depth = resp.json().get("messages_ready", 0)
                    depths[qname_key] = depth
                    # 同步 Prometheus gauge（决策 13，供 Grafana/KEDA 观测）
                    MQ_QUEUE_DEPTH.labels(block_id=api_id, queue=qname_key).set(depth)
                else:
                    depths[qname_key] = -1
            except Exception:  # noqa: BLE001
                depths[qname_key] = -1
        return depths

    # ── DLQ 运维（生产级 MQ 运维：查看 / 重投 / 清空死信）─────────────────────────

    async def peek_dlq(self, api_id: str, limit: int = 10) -> list[dict]:
        """通过 Management API 预览 DLQ 死信样本（requeue=true，不消费）。"""
        from pyflow_runtime.backoff_queue import dlq_queue

        mgmt_base, vhost, auth = self._mgmt()
        if not mgmt_base:
            return []
        url = f"{mgmt_base}/api/queues/{vhost}/{dlq_queue(api_id)}/get"
        payload = {"count": limit, "ackmode": "ack_requeue_true",
                   "encoding": "auto", "truncate": 50000}
        resp = await self._http_client().post(url, json=payload, auth=auth)
        if resp.status_code != 200:
            return []
        out = []
        for m in resp.json():
            out.append({
                "payload": m.get("payload", "")[:2000],
                "x_retry_count": (m.get("properties", {}).get("headers", {}) or {}).get("x-retry-count"),
                "redelivered": m.get("redelivered"),
            })
        return out

    async def requeue_dlq(self, api_id: str) -> int:
        """把 DLQ 死信全部重投回主队列并重置 x-retry-count（人工干预后重试）。"""
        from pyflow_runtime.backoff_queue import dlq_queue, main_queue

        if not self._connection or self._connection.is_closed:
            if not await self.connect():
                return 0
        channel = await self._connection.channel()
        moved = 0
        try:
            dlq = await channel.get_queue(dlq_queue(api_id))
            while True:
                message = await dlq.get(no_ack=False, fail=False)
                if message is None:
                    break
                headers = dict(message.headers or {})
                headers["x-retry-count"] = "0"  # 人工重投：重置重试计数
                await channel.default_exchange.publish(
                    self._copy_message(message.body, headers),
                    routing_key=main_queue(api_id),
                )
                await message.ack()
                moved += 1
        finally:
            await channel.close()
        return moved

    async def purge_dlq(self, api_id: str) -> int:
        """清空 DLQ（确认死信无需保留时）。"""
        from pyflow_runtime.backoff_queue import dlq_queue

        if not self._connection or self._connection.is_closed:
            if not await self.connect():
                return 0
        channel = await self._connection.channel()
        try:
            dlq = await channel.get_queue(dlq_queue(api_id))
            result = await dlq.purge()
            return int(getattr(result, "message_count", 0) or 0)
        finally:
            await channel.close()


def _amqp_to_mgmt(amqp_url: str) -> str | None:
    """将 amqp://user:pass@host:5672/vhost 转为 http://host:15672"""
    try:
        import urllib.parse
        parsed = urllib.parse.urlparse(amqp_url)
        host = parsed.hostname or "localhost"
        return f"http://{host}:15672"
    except Exception:  # noqa: BLE001
        return None


def _extract_vhost(amqp_url: str) -> str:
    """从 AMQP URL 提取 vhost（URL 编码）。"""
    import urllib.parse
    try:
        parsed = urllib.parse.urlparse(amqp_url)
        raw = parsed.path.lstrip("/") or "%2F"
        return urllib.parse.quote(urllib.parse.unquote(raw), safe="")
    except Exception:  # noqa: BLE001
        return "%2F"


def _extract_auth(amqp_url: str) -> tuple[str, str]:
    """从 AMQP URL 提取 (user, password)。"""
    import urllib.parse
    try:
        parsed = urllib.parse.urlparse(amqp_url)
        return (parsed.username or "guest", parsed.password or "guest")
    except Exception:  # noqa: BLE001
        return ("guest", "guest")


# 全局单例（由 lifespan 管理生命周期）
_manager: ConsumerManager | None = None


def get_consumer_manager() -> ConsumerManager:
    global _manager
    if _manager is None:
        _manager = ConsumerManager()
    return _manager
