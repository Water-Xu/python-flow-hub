"""dev 本地 Docker 沙箱执行（决策 1）。

控制面绝不在 Pod 内跑 Docker；本执行器仅 deployment_mode=local 成立，
由开发者本机 / 本地 Linux runner 的 Docker daemon 承载。复用 pyflow_runtime 执行内核与安全常量。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Callable

from pyflow_runtime.executor import execute_user_code
from pyflow_runtime.sandbox_config import build_docker_sandbox_config

from app.config import get_settings
from app.errors import PYFLOW_EXEC_SANDBOX_ERROR, PYFLOW_EXEC_TIMEOUT, BusinessException

settings = get_settings()

_RESULT_MARKER = "__PYFLOW_RESULT__"

# 容器内运行的引导脚本：读 stdin {code, inputs} → 执行 → stdout 末行输出结果
_BOOTSTRAP = (
    "import sys,json\n"
    "from pyflow_runtime.executor import execute_user_code\n"
    "p=json.loads(sys.stdin.read())\n"
    "r=execute_user_code(p['code'],p.get('inputs',{}))\n"
    "sys.stdout.write('\\n" + _RESULT_MARKER + "'+json.dumps(r,default=str))\n"
)


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
    payload = json.dumps({"code": code, "inputs": inputs}, default=str)

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


async def execute_in_process(code: str, inputs: dict[str, Any]) -> ExecutionOutput:
    """⚠️ 仅 dev 无 Docker 时的降级（无隔离，绝不用于生产）。"""
    result = await asyncio.to_thread(execute_user_code, code, inputs)
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
    allow_in_process_fallback: bool = True,
    timeout: int | None = None,
) -> ExecutionOutput:
    """优先 Docker 沙箱；本机无 Docker 且允许时降级 in-process（仅 dev 调试）。"""
    docker = _try_import_docker()
    if docker is not None:
        try:
            return await execute_in_docker(code, inputs, timeout=timeout)
        except BusinessException:
            if not allow_in_process_fallback:
                raise
    if allow_in_process_fallback and settings.deployment_mode == "local":
        return await execute_in_process(code, inputs)
    raise BusinessException(PYFLOW_EXEC_SANDBOX_ERROR, "no sandbox runtime available")
