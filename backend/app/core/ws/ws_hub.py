"""WebSocket + Redis PubSub 多副本路由（决策 5）。

执行输出通过 Redis Pub/Sub 跨副本路由，而非进程内广播。
握手流程：accept 前校验 token → 解析 loginId → 校验 execution_id 可见性 → subscribe channel。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import redis.asyncio as aioredis
from fastapi import WebSocket

from app.config import get_settings

settings = get_settings()


def output_channel(execution_id: str) -> str:
    return f"pyflow:exec:output:{execution_id}"


class WSHub:
    """管理本副本的 WS 连接与 Redis 订阅。"""

    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None
        self._pub: aioredis.Redis | None = None

    async def _ensure_redis(self) -> None:
        if self._redis is None:
            self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
            self._pub = aioredis.from_url(settings.redis_url, decode_responses=True)

    async def publish_output(self, execution_id: str, line: str, stream: str = "stdout") -> None:
        """执行进程写输出 → publish 到 Redis channel，由持有 WS 的副本推送。"""
        await self._ensure_redis()
        assert self._pub is not None
        await self._pub.publish(
            output_channel(execution_id),
            json.dumps({"stream": stream, "line": line}),
        )

    async def serve(self, websocket: WebSocket, execution_id: str) -> None:
        """订阅该 execution 的输出 channel 并推送给前端（独立连接，避免阻塞命令连接）。"""
        await self._ensure_redis()
        sub_conn = aioredis.from_url(settings.redis_url, decode_responses=True)
        pubsub = sub_conn.pubsub()
        await pubsub.subscribe(output_channel(execution_id))
        try:
            ping_task = asyncio.create_task(self._heartbeat(websocket))
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                await websocket.send_text(msg["data"])
        finally:
            ping_task.cancel()
            await pubsub.unsubscribe(output_channel(execution_id))
            await sub_conn.aclose()

    @staticmethod
    async def _heartbeat(websocket: WebSocket) -> None:
        """应用层 30s ping 保活（中间层静默断开防护）。"""
        try:
            while True:
                await asyncio.sleep(30)
                await websocket.send_text(json.dumps({"stream": "ping", "line": ""}))
        except Exception:  # noqa: BLE001
            return


hub = WSHub()
