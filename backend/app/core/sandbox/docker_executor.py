"""dev 本地 Docker 沙箱执行（决策 1）。

控制面绝不在 Pod 内跑 Docker；本执行器仅 deployment_mode=local 成立，
由开发者本机 / 本地 Linux runner 的 Docker daemon 承载。复用 pyflow_runtime 执行内核与安全常量。
"""

from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable

from pyflow_runtime.executor import execute_user_code, execute_user_code_stream
from pyflow_runtime.sandbox_config import build_docker_sandbox_config

from app.config import get_settings
from app.errors import PYFLOW_EXEC_SANDBOX_ERROR, PYFLOW_EXEC_TIMEOUT, BusinessException
from app.observability.logging import get_logger

settings = get_settings()
logger = get_logger()

_RESULT_MARKER = "__PYFLOW_RESULT__"
_CHUNK_MARKER = "__PYFLOW_CHUNK__"

# 容器内运行的引导脚本：读 stdin {code, inputs, entrypoint} → 执行 → stdout 末行输出结果
_BOOTSTRAP = (
    "import sys,json\n"
    "from pyflow_runtime.executor import execute_user_code\n"
    "p=json.loads(sys.stdin.read())\n"
    "r=execute_user_code(p['code'],p.get('inputs',{}),p.get('entrypoint','run'))\n"
    "sys.stdout.write('\\n" + _RESULT_MARKER + "'+json.dumps(r,default=str))\n"
)

# 流式引导脚本（docker tty + k8s job 共用）：payload 经 env 注入，逐 chunk/result 行输出并 flush。
# 每个 chunk 一行 `__PYFLOW_CHUNK__<json>`，最终 `__PYFLOW_RESULT__<json>`，由控制面逐行解析。
_STREAMING_BOOTSTRAP = (
    "import os,sys,json,base64\n"
    "from pyflow_runtime.executor import execute_user_code_stream\n"
    "p=json.loads(base64.b64decode(os.environ['PYFLOW_EXEC_PAYLOAD_B64']))\n"
    "for _ev in execute_user_code_stream(p['code'],p.get('inputs',{}),p.get('entrypoint','run')):\n"
    "    if _ev.get('type')=='chunk':\n"
    "        sys.stdout.write('" + _CHUNK_MARKER
    + "'+json.dumps(_ev.get('data'),ensure_ascii=False,default=str)+'\\n')\n"
    "    else:\n"
    "        sys.stdout.write('" + _RESULT_MARKER
    + "'+json.dumps(_ev,ensure_ascii=False,default=str)+'\\n')\n"
    "    sys.stdout.flush()\n"
)


def parse_stream_line(line: str) -> dict[str, Any] | None:
    """解析流式输出的一行：识别 chunk / result 标记行，其余行（用户残留 stdout）忽略。

    tty 输出行尾可能带 ``\\r``；JSON 解析容忍尾部空白，标记前缀判断不受影响。
    """
    s = line.rstrip("\r")
    if s.startswith(_CHUNK_MARKER):
        raw = s[len(_CHUNK_MARKER):]
        try:
            data = json.loads(raw)
        except Exception:  # noqa: BLE001
            data = raw
        return {"type": "chunk", "data": data}
    if s.startswith(_RESULT_MARKER):
        raw = s[len(_RESULT_MARKER):]
        try:
            result = json.loads(raw)
        except Exception:  # noqa: BLE001
            return None
        return {"type": "result", **result}
    return None


@dataclass
class ExecutionOutput:
    output: Any
    stdout: str
    stderr: str
    error: str | None


def _try_import_docker():
    try:
        import docker  # type: ignore

        return docker
    except ImportError:
        return None


async def execute_in_docker(
    code: str,
    inputs: dict[str, Any],
    *,
    entrypoint: str = "run",
    on_log: Callable[[str], Any] | None = None,
    timeout: int | None = None,
) -> ExecutionOutput:
    """在 Docker 沙箱内执行用户代码。

    若本机无 Docker（如 Windows 无 Docker Desktop），抛 PYFLOW_EXEC_SANDBOX_ERROR；
    可通过 in-process 降级（仅 dev 调试）由 run_block 决定。
    """
    docker = _try_import_docker()
    if docker is None:
        raise BusinessException(PYFLOW_EXEC_SANDBOX_ERROR, "docker SDK not available")

    timeout = timeout or settings.execution_timeout
    cfg = build_docker_sandbox_config(prefer_gvisor=settings.sandbox_gvisor)
    payload = json.dumps(
        {"code": code, "inputs": inputs, "entrypoint": entrypoint}, default=str
    )

    def _run() -> ExecutionOutput:
        client = docker.from_env()
        container = client.containers.create(
            image=settings.docker_base_image,
            command=["python", "-c", _BOOTSTRAP],
            stdin_open=True,
            detach=True,
            **cfg,
        )
        try:
            container.start()
            sock = container.attach_socket(params={"stdin": 1, "stream": 1})
            sock._sock.sendall(payload.encode("utf-8"))  # noqa: SLF001
            sock._sock.shutdown(1)  # noqa: SLF001
            res = container.wait(timeout=timeout)
            logs = container.logs(stdout=True, stderr=True).decode("utf-8", "replace")
            return _parse_logs(logs, res.get("StatusCode", 0))
        finally:
            try:
                container.remove(force=True)
            except Exception:  # noqa: BLE001
                pass

    try:
        return await asyncio.wait_for(asyncio.to_thread(_run), timeout=timeout + 10)
    except asyncio.TimeoutError as exc:
        raise BusinessException(PYFLOW_EXEC_TIMEOUT, "docker execution timeout") from exc


def _parse_logs(logs: str, status_code: int) -> ExecutionOutput:
    marker_idx = logs.rfind(_RESULT_MARKER)
    if marker_idx == -1:
        return ExecutionOutput(None, logs, "", f"no result marker (exit={status_code})")
    head = logs[:marker_idx]
    result = json.loads(logs[marker_idx + len(_RESULT_MARKER):])
    return ExecutionOutput(
        output=result.get("output"),
        stdout=head + (result.get("stdout") or ""),
        stderr=result.get("stderr") or "",
        error=result.get("error"),
    )


async def execute_in_process(
    code: str, inputs: dict[str, Any], entrypoint: str = "run"
) -> ExecutionOutput:
    """⚠️ 仅 dev 无 Docker 时的降级（无隔离，绝不用于生产）。"""
    result = await asyncio.to_thread(execute_user_code, code, inputs, entrypoint)
    return ExecutionOutput(
        output=result.get("output"),
        stdout=result.get("stdout") or "",
        stderr=result.get("stderr") or "",
        error=result.get("error"),
    )


async def run_block(
    code: str,
    inputs: dict[str, Any],
    *,
    entrypoint: str = "run",
    allow_in_process_fallback: bool = True,
    timeout: int | None = None,
    invoke_service: str | None = None,
) -> ExecutionOutput:
    """local：Docker 沙箱（可降级 in-process）；k8s：K8s Job + runner 镜像，不走 Docker。

    :param invoke_service: 该块已部署的常驻 invoke Service 名（仅 k8s 模式有效）。
        传入时优先复用常驻 Pod（稳定版本代码，无冷启动）；调用失败自动回退一次性 Job（draft 代码）。
    """
    if settings.deployment_mode == "k8s":
        from app.core.sandbox.k8s_executor import execute_in_k8s_job

        # 命中已部署的常驻 invoke Service：复用 warm Pod，消除每块 Job 冷启动
        if invoke_service:
            from app.core.sandbox.k8s_executor import execute_via_invoke_service

            try:
                return await execute_via_invoke_service(
                    invoke_service, inputs, entrypoint=entrypoint, timeout=timeout
                )
            except BusinessException as exc:
                # invoke Service 不可达/异常：回退一次性 Job，保证可用性不被优化破坏
                logger.warning(
                    "invoke_service_fallback_job",
                    service=invoke_service,
                    error=str(exc.detail or "")[:200],
                )
        return await execute_in_k8s_job(code, inputs, entrypoint=entrypoint, timeout=timeout)

    docker = _try_import_docker()
    if docker is not None:
        try:
            return await execute_in_docker(code, inputs, entrypoint=entrypoint, timeout=timeout)
        except BusinessException:
            if not allow_in_process_fallback:
                raise
        except Exception as exc:
            # Windows 未启动 Docker Desktop 时 from_env() 常抛 Connection aborted / FileNotFoundError
            if not allow_in_process_fallback:
                raise BusinessException(
                    PYFLOW_EXEC_SANDBOX_ERROR,
                    "docker daemon unavailable; start Docker Desktop or use deployment_mode=local",
                ) from exc
            logger.warning("docker_sandbox_unavailable", error=str(exc)[:200])
    if allow_in_process_fallback and settings.deployment_mode == "local":
        logger.info("sandbox_fallback_in_process", mode=settings.deployment_mode)
        return await execute_in_process(code, inputs, entrypoint)
    raise BusinessException(PYFLOW_EXEC_SANDBOX_ERROR, "no sandbox runtime available")


# ── 流式执行（真流式：用户代码 yield → 逐 chunk 实时穿透）────────────────────────

async def _docker_available() -> bool:
    """探测本机 Docker daemon 是否可用（不可用时降级 in-process 流式，仅 dev）。"""
    docker = _try_import_docker()
    if docker is None:
        return False

    def _ping() -> bool:
        try:
            docker.from_env().ping()
            return True
        except Exception:  # noqa: BLE001
            return False

    return await asyncio.to_thread(_ping)


async def execute_in_docker_stream(
    code: str,
    inputs: dict[str, Any],
    *,
    entrypoint: str = "run",
    timeout: int | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """在 Docker 沙箱内流式执行：tty 模式取干净（非多路复用）stdout，逐行解析 chunk/result。

    payload 经 env（base64）注入，避免 stdin socket 复杂度；``PYTHONUNBUFFERED`` 保证即时 flush。
    日志读取在线程内进行，经 ``asyncio.Queue`` 回送事件循环，避免阻塞。
    """
    docker = _try_import_docker()
    if docker is None:
        raise BusinessException(PYFLOW_EXEC_SANDBOX_ERROR, "docker SDK not available")

    timeout = timeout or settings.execution_timeout
    cfg = build_docker_sandbox_config(prefer_gvisor=settings.sandbox_gvisor)
    payload = json.dumps(
        {"code": code, "inputs": inputs, "entrypoint": entrypoint}, default=str
    )
    payload_b64 = base64.b64encode(payload.encode("utf-8")).decode("ascii")

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
    holder: dict[str, Any] = {"container": None}

    def _worker() -> None:
        try:
            client = docker.from_env()
            container = client.containers.create(
                image=settings.docker_base_image,
                command=["python", "-c", _STREAMING_BOOTSTRAP],
                environment={
                    "PYFLOW_EXEC_PAYLOAD_B64": payload_b64,
                    "PYTHONUNBUFFERED": "1",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                tty=True,
                detach=True,
                **cfg,
            )
            holder["container"] = container
            container.start()
            buf = ""
            for raw in container.logs(stream=True, follow=True):
                text = (
                    raw.decode("utf-8", "replace")
                    if isinstance(raw, (bytes, bytearray))
                    else str(raw)
                )
                buf += text
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    loop.call_soon_threadsafe(queue.put_nowait, ("line", line))
            if buf.strip():
                loop.call_soon_threadsafe(queue.put_nowait, ("line", buf))
        except Exception as exc:  # noqa: BLE001
            loop.call_soon_threadsafe(queue.put_nowait, ("error", str(exc)[:300]))
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, ("end", None))

    worker = asyncio.create_task(asyncio.to_thread(_worker))
    deadline = loop.time() + timeout
    try:
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise BusinessException(PYFLOW_EXEC_TIMEOUT, "docker stream timeout")
            try:
                kind, val = await asyncio.wait_for(queue.get(), timeout=remaining)
            except asyncio.TimeoutError as exc:
                raise BusinessException(PYFLOW_EXEC_TIMEOUT, "docker stream timeout") from exc
            if kind == "end":
                break
            if kind == "error":
                raise BusinessException(PYFLOW_EXEC_SANDBOX_ERROR, str(val))
            event = parse_stream_line(val)
            if event is not None:
                yield event
    finally:
        container = holder.get("container")
        if container is not None:
            try:
                await asyncio.to_thread(container.remove, force=True)
            except Exception:  # noqa: BLE001
                pass
        worker.cancel()


async def _stream_in_process(
    code: str, inputs: dict[str, Any], entrypoint: str
) -> AsyncIterator[dict[str, Any]]:
    """⚠️ 仅 dev 无 Docker 时降级：在线程内逐步推进同步生成器，避免阻塞事件循环。"""
    gen = execute_user_code_stream(code, inputs, entrypoint)
    sentinel = object()

    def _next() -> Any:
        try:
            return next(gen)
        except StopIteration:
            return sentinel

    while True:
        event = await asyncio.to_thread(_next)
        if event is sentinel:
            break
        yield event


async def run_block_stream(
    code: str,
    inputs: dict[str, Any],
    *,
    entrypoint: str = "run",
    allow_in_process_fallback: bool = True,
    timeout: int | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """流式执行入口：k8s 走 Job + pod 日志跟随；local 走 Docker tty（可降级 in-process）。"""
    if settings.deployment_mode == "k8s":
        from app.core.sandbox.k8s_executor import execute_in_k8s_job_stream

        async for event in execute_in_k8s_job_stream(
            code, inputs, entrypoint=entrypoint, timeout=timeout
        ):
            yield event
        return

    if await _docker_available():
        async for event in execute_in_docker_stream(
            code, inputs, entrypoint=entrypoint, timeout=timeout
        ):
            yield event
        return

    if allow_in_process_fallback and settings.deployment_mode == "local":
        logger.info("sandbox_stream_fallback_in_process", mode=settings.deployment_mode)
        async for event in _stream_in_process(code, inputs, entrypoint):
            yield event
        return

    raise BusinessException(PYFLOW_EXEC_SANDBOX_ERROR, "no sandbox runtime available")
