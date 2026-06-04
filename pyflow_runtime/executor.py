"""用户代码执行框架（在沙箱容器 / runner Pod 内运行）。

约定：用户 Block 代码必须定义 `def run(inputs: dict) -> dict`。
本模块负责注入输入、调用、捕获输出与异常，构成 docker_executor / k8s job / 常驻消费者三处的统一执行内核。
"""

from __future__ import annotations

import io
import json
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from typing import Any


class BlockExecutionError(RuntimeError):
    """用户代码执行失败。"""


def execute_user_code(code: str, inputs: dict[str, Any]) -> dict[str, Any]:
    """在当前进程内编译并执行用户代码（容器内已隔离）。

    返回 {"output": <run 返回值>, "stdout": str, "stderr": str}。
    """
    namespace: dict[str, Any] = {}
    stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
    try:
        compiled = compile(code, "<block>", "exec")
    except SyntaxError as exc:
        raise BlockExecutionError(f"block code syntax error: {exc}") from exc

    with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
        try:
            exec(compiled, namespace)  # noqa: S102 - 隔离沙箱内执行
            run_fn = namespace.get("run")
            if not callable(run_fn):
                raise BlockExecutionError("block code must define `def run(inputs): ...`")
            output = run_fn(inputs)
        except BlockExecutionError:
            raise
        except Exception as exc:  # noqa: BLE001
            tb = traceback.format_exc()
            return {
                "output": None,
                "stdout": stdout_buf.getvalue(),
                "stderr": stderr_buf.getvalue() + tb,
                "error": str(exc),
            }

    return {
        "output": output,
        "stdout": stdout_buf.getvalue(),
        "stderr": stderr_buf.getvalue(),
        "error": None,
    }


def _main() -> None:
    """容器入口：从 stdin 读 {"code", "inputs"}，结果写 stdout 末行 JSON。"""
    payload = json.loads(sys.stdin.read())
    result = execute_user_code(payload["code"], payload.get("inputs", {}))
    sys.stdout.write("\n__PYFLOW_RESULT__" + json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    _main()
