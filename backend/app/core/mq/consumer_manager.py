"""dev-local 消费者管理器（决策 3.1 模型 A）。

生产环境：消费者 = Block Pod 内 pyflow_runtime.consumer，由 KEDA 扩缩。
dev-local：控制面启动轻量 aio-pika 消费者，通过 docker_executor 在本机 Docker 执行代码。
           lifespan 启动/停止，逐块管理，不常驻消费生产队列（只 dev 调试用）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

import aio_pika

from app.config import get_settings
from app.core.mq.topology_builder import declare_block_topology

logger = logging.getLogger("pyflow.mq")
POD_NAME = os.getenv("HOSTNAME", "local-runner")


@dataclass
class ConsumerStatus:
    block_id: str
    block_name: str
    status: str = "stopped"           # stopped | connecting | running | error
    queue_depth: int = 0
    dlq_depth: int = 0
    processed: int = 0
    errors: int = 0
    last_error: str | None = None
    started_at: float | None = None
    error_detail: str | None = None


class ConsumerManager:
    """管理 dev-local 下各 async_mq Block 的 aio-pika 消费者生命周期。"""

    def __init__(self) -> None:
        self._consumers: dict[str, ConsumerStatus] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._connection: aio_pika.abc.AbstractRobustConnection | None = None
        self._channel: aio_pika.abc.AbstractChannel | None = None
        self._redis: Any = None
        self._settings = get_settings()
        self._running = False

    # ── 连接管理 ─────────────────────────────────────────────────────────────

    async def connect(self) -> bool:
        """建立 RabbitMQ + Redis 连接；连接失败只记日志不崩溃（dev 可选）。"""
        try:
            self._connection = await aio_pika.connect_robust(self._settings.rabbitmq_url)
            self._channel = await self._connection.channel()
            await self._channel.set_qos(prefetch_count=1)
            logger.info("mq_connected", url=self._settings.rabbitmq_url[:40])
        except Exception as exc:
            logger.warning("mq_connect_failed", exc=str(exc))
            return False

        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(
                self._settings.redis_url, decode_responses=True,
                socket_connect_timeout=3,
            )
            await self._redis.ping()
            logger.info("redis_connected")
        except Exception as exc:
            logger.warning("redis_connect_failed_idempotency_disabled", exc=str(exc))
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
            await self._redis.aclose()
        logger.info("mq_disconnected")

    # ── 消费者生命周期 ────────────────────────────────────────────────────────

    def get_status(self, block_id: str) -> ConsumerStatus | None:
        return self._consumers.get(block_id)

    def all_statuses(self) -> list[dict]:
        return [
            {
                "block_id": s.block_id,
                "block_name": s.block_name,
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
        block_id: str,
        block_name: str,
        block_code: str,
        mq_config: dict[str, Any],
    ) -> bool:
        """启动指定 Block 的消费者（已运行则重启）。"""
        await self.stop_consumer(block_id)

        if not self._connection or self._connection.is_closed:
            ok = await self.connect()
            if not ok:
                return False

        status = ConsumerStatus(block_id=block_id, block_name=block_name, status="connecting")
        self._consumers[block_id] = status

        task = asyncio.create_task(
            self._consume_loop(block_id, block_code, mq_config, status),
            name=f"consumer-{block_id}",
        )
        self._tasks[block_id] = task
        return True

    async def stop_consumer(self, block_id: str) -> None:
        task = self._tasks.pop(block_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if block_id in self._consumers:
            self._consumers[block_id].status = "stopped"

    # ── 核心消费循环 ──────────────────────────────────────────────────────────

    async def _consume_loop(
        self,
        block_id: str,
        block_code: str,
        mq_config: dict[str, Any],
        status: ConsumerStatus,
    ) -> None:
        from pyflow_runtime.consumer import consume_with_idempotency
        from pyflow_runtime.idempotency import IdempotencyStore

        retry_delay_ms = int(mq_config.get("retry_delay_ms", 5000))
        block_cfg = {"mq_config": mq_config, "compute_config": {}}

        try:
            channel = await self._connection.channel()
            await channel.set_qos(prefetch_count=1)

            topology = await declare_block_topology(channel, block_id, retry_delay_ms)
            queue = await channel.get_queue(topology["main"])

            store: IdempotencyStore | None = None
            if self._redis:
                store = IdempotencyStore(self._redis, POD_NAME)

            status.status = "running"
            status.started_at = time.time()
            logger.info("consumer_started", block_id=block_id)

            async with queue.iterator() as iter_:
                async for message in iter_:
                    async with message.process(requeue=False, ignore_processed=True):
                        await self._handle_message(
                            message, block_id, block_code, block_cfg, store, status, channel
                        )

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            status.status = "error"
            status.error_detail = str(exc)
            logger.error("consumer_error", block_id=block_id, exc=str(exc))

    async def _handle_message(
        self,
        message: aio_pika.abc.AbstractIncomingMessage,
        block_id: str,
        block_code: str,
        block_cfg: dict,
        store: Any,
        status: ConsumerStatus,
        channel: aio_pika.abc.AbstractChannel,
    ) -> None:
        from pyflow_runtime.consumer import consume_with_idempotency
        from pyflow_runtime.idempotency import IdempotencyStore
        from pyflow_runtime.backoff_queue import backoff_queue as backoff_q
        from app.core.mq.topology_builder import publish_message

        try:
            body = json.loads(message.body.decode("utf-8"))
        except Exception:
            body = {}

        headers = dict(message.headers or {})
        retry_count = int(headers.get("x-retry-count", 0))
        max_retry = int((block_cfg.get("mq_config") or {}).get("max_retry", 3))

        if store:
            action = await consume_with_idempotency(
                message_body=body,
                headers=headers,
                block=block_cfg,
                store=store,
                execute_fn=lambda inputs: self._exec_block(block_code, inputs),
                message_id=message.message_id,
            )
        else:
            # Redis 不可用：直接执行，不做幂等
            try:
                mq_cfg = block_cfg.get("mq_config") or {}
                action = await self._exec_block_with_result(body, block_code, mq_cfg)
            except Exception as exc:
                action = "nack"
                status.last_error = str(exc)[:200]

        if action == "ack":
            await message.ack()
            status.processed += 1
        elif action == "backoff":
            await message.nack(requeue=False)
            await self._publish_backoff(channel, block_id, message, headers)
        else:  # nack → DLQ → TTL+DLX 重试
            if retry_count >= max_retry:
                # 超过最大重试，路由到死信归档
                await message.nack(requeue=False)
            else:
                headers["x-retry-count"] = str(retry_count + 1)
                await message.nack(requeue=False)
            status.errors += 1

    async def _exec_block(self, code: str, inputs: dict) -> dict:
        """通过 docker_executor 执行代码（dev-local Docker 沙箱）。"""
        from app.core.sandbox.docker_executor import run_in_docker
        result = await run_in_docker(code=code, inputs=inputs, timeout=300)
        if result.get("error"):
            raise RuntimeError(result["error"])
        return result.get("output") or {}

    async def _exec_block_with_result(self, body: dict, code: str, mq_cfg: dict) -> str:
        from pyflow_runtime.input_mapper import map_inputs
        inputs = map_inputs(body, mq_cfg.get("input_mapping"))
        await self._exec_block(code, inputs)
        return "ack"

    async def _publish_backoff(
        self,
        channel: aio_pika.abc.AbstractChannel,
        block_id: str,
        message: aio_pika.abc.AbstractIncomingMessage,
        headers: dict,
    ) -> None:
        from pyflow_runtime.backoff_queue import backoff_queue as backoff_q
        backoff_msg = aio_pika.Message(
            body=message.body,
            headers=headers,
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )
        await channel.default_exchange.publish(backoff_msg, routing_key=backoff_q(block_id))

    # ── 队列深度查询 ──────────────────────────────────────────────────────────

    async def fetch_queue_depth(self, block_id: str) -> dict[str, int]:
        """通过 RabbitMQ Management HTTP API 查询队列深度。"""
        import httpx
        from pyflow_runtime.backoff_queue import main_queue, dlq_queue

        settings = self._settings
        # 从 AMQP URL 解析 Management API base
        mgmt_base = _amqp_to_mgmt(settings.rabbitmq_url)
        if not mgmt_base:
            return {"main": 0, "dlq": 0}

        vhost = _extract_vhost(settings.rabbitmq_url)
        auth = _extract_auth(settings.rabbitmq_url)

        async with httpx.AsyncClient(timeout=5) as client:
            depths: dict[str, int] = {}
            for qname_key, queue_fn in [("main", main_queue), ("dlq", dlq_queue)]:
                qname = queue_fn(block_id)
                try:
                    url = f"{mgmt_base}/api/queues/{vhost}/{qname}"
                    resp = await client.get(url, auth=auth)
                    if resp.status_code == 200:
                        data = resp.json()
                        depths[qname_key] = data.get("messages_ready", 0)
                    else:
                        depths[qname_key] = -1
                except Exception:
                    depths[qname_key] = -1
            return depths


def _amqp_to_mgmt(amqp_url: str) -> str | None:
    """将 amqp://user:pass@host:5672/vhost 转为 http://host:15672"""
    try:
        import urllib.parse
        parsed = urllib.parse.urlparse(amqp_url)
        host = parsed.hostname or "localhost"
        return f"http://{host}:15672"
    except Exception:
        return None


def _extract_vhost(amqp_url: str) -> str:
    """从 AMQP URL 提取 vhost（URL 编码）。"""
    import urllib.parse
    try:
        parsed = urllib.parse.urlparse(amqp_url)
        raw = parsed.path.lstrip("/") or "%2F"
        return urllib.parse.quote(urllib.parse.unquote(raw), safe="")
    except Exception:
        return "%2F"


def _extract_auth(amqp_url: str) -> tuple[str, str]:
    """从 AMQP URL 提取 (user, password)。"""
    import urllib.parse
    try:
        parsed = urllib.parse.urlparse(amqp_url)
        return (parsed.username or "guest", parsed.password or "guest")
    except Exception:
        return ("guest", "guest")


# 全局单例（由 lifespan 管理生命周期）
_manager: ConsumerManager | None = None


def get_consumer_manager() -> ConsumerManager:
    global _manager
    if _manager is None:
        _manager = ConsumerManager()
    return _manager
