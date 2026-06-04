"""Jupyter Kernel 管理（决策 9：仅 dev local 模式）。

Jupyter Kernel 有状态、易内存泄漏、绑定单进程，与"无状态 Pod + scale-to-zero"不兼容，
因此只在 deployment_mode=local 开启，生产 K8s Pod 不启动 Kernel。
按 block_id 维护内核实例（进程内注册表，单实例 dev 足够）。
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.config import get_settings
from app.errors import PYFLOW_EXEC_SANDBOX_ERROR, BusinessException
from app.observability.logging import get_logger

logger = get_logger("pyflow.jupyter")
settings = get_settings()

EXECUTE_TIMEOUT = 60


def _assert_local() -> None:
    if settings.deployment_mode != "local":
        raise BusinessException(
            PYFLOW_EXEC_SANDBOX_ERROR, "Jupyter 仅在 local 开发模式可用（决策 9）"
        )


class KernelSession:
    def __init__(self, block_id: str) -> None:
        self.block_id = block_id
        self._km: Any = None
        self._kc: Any = None

    async def start(self) -> None:
        try:
            from jupyter_client.manager import AsyncKernelManager  # type: ignore
        except ImportError as exc:
            raise BusinessException(PYFLOW_EXEC_SANDBOX_ERROR, "jupyter_client not installed") from exc
        self._km = AsyncKernelManager()
        await self._km.start_kernel()
        self._kc = self._km.client()
        self._kc.start_channels()
        await self._kc.wait_for_ready(timeout=30)
        logger.info("kernel_started", block_id=self.block_id)

    @property
    def alive(self) -> bool:
        return self._kc is not None and self._km is not None

    async def execute(self, code: str) -> dict[str, Any]:
        if not self.alive:
            await self.start()
        kc = self._kc
        msg_id = kc.execute(code)
        stdout: list[str] = []
        stderr: list[str] = []
        result: list[str] = []
        error: dict[str, Any] | None = None

        while True:
            try:
                msg = await kc.get_iopub_msg(timeout=EXECUTE_TIMEOUT)
            except Exception:  # noqa: BLE001 队列超时
                break
            if msg.get("parent_header", {}).get("msg_id") != msg_id:
                continue
            msg_type = msg["msg_type"]
            content = msg["content"]
            if msg_type == "stream":
                (stdout if content["name"] == "stdout" else stderr).append(content["text"])
            elif msg_type in ("execute_result", "display_data"):
                data = content.get("data", {})
                if "text/plain" in data:
                    result.append(data["text/plain"])
            elif msg_type == "error":
                error = {
                    "ename": content.get("ename"),
                    "evalue": content.get("evalue"),
                    "traceback": content.get("traceback", []),
                }
            elif msg_type == "status" and content.get("execution_state") == "idle":
                break

        return {
            "stdout": "".join(stdout),
            "stderr": "".join(stderr),
            "result": "\n".join(result),
            "error": error,
        }

    async def interrupt(self) -> None:
        if self._km is not None:
            await self._km.interrupt_kernel()

    async def shutdown(self) -> None:
        try:
            if self._kc is not None:
                self._kc.stop_channels()
            if self._km is not None:
                await self._km.shutdown_kernel(now=True)
        finally:
            self._kc = None
            self._km = None
            logger.info("kernel_shutdown", block_id=self.block_id)


class KernelRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, KernelSession] = {}
        self._lock = asyncio.Lock()

    async def get_or_start(self, block_id: str) -> KernelSession:
        _assert_local()
        async with self._lock:
            sess = self._sessions.get(block_id)
            if sess is None or not sess.alive:
                sess = KernelSession(block_id)
                await sess.start()
                self._sessions[block_id] = sess
            return sess

    async def execute(self, block_id: str, code: str) -> dict[str, Any]:
        sess = await self.get_or_start(block_id)
        return await sess.execute(code)

    async def interrupt(self, block_id: str) -> None:
        _assert_local()
        sess = self._sessions.get(block_id)
        if sess:
            await sess.interrupt()

    async def shutdown(self, block_id: str) -> None:
        _assert_local()
        sess = self._sessions.pop(block_id, None)
        if sess:
            await sess.shutdown()

    def status(self, block_id: str) -> dict[str, Any]:
        sess = self._sessions.get(block_id)
        return {"running": bool(sess and sess.alive), "enabled": settings.deployment_mode == "local"}

    async def shutdown_all(self) -> None:
        for block_id in list(self._sessions.keys()):
            try:
                await self.shutdown(block_id)
            except Exception:  # noqa: BLE001
                pass


_registry: KernelRegistry | None = None


def get_registry() -> KernelRegistry:
    global _registry
    if _registry is None:
        _registry = KernelRegistry()
    return _registry
