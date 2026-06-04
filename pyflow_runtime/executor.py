"""用户代码执行框架（在沙箱容器 / runner Pod 内运行）。

约定：用户 Block 代码须定义至少一个入口函数 `def 函数名(inputs: dict) -> dict`，
默认入口为 `run`；一个脚本可暴露多个入口函数，由调用方通过 entrypoint 选择。
本模块负责注入输入、调用、捕获输出与异常，构成 docker_executor / k8s job / 常驻消费者三处的统一执行内核。
"""

from __future__ import annotations

import ast
import io
import json
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

# 默认入口函数名（向后兼容：未指定 entrypoint 时调用 run）
DEFAULT_ENTRYPOINT = "run"


class BlockExecutionError(RuntimeError):
    """用户代码执行失败。"""


def execute_user_code(
    code: str,
    inputs: dict[str, Any],
    entrypoint: str = DEFAULT_ENTRYPOINT,
) -> dict[str, Any]:
    """在当前进程内编译并执行用户代码（容器内已隔离）。

    :param code: 用户 Block 脚本源码
    :param inputs: 注入入口函数的输入字典
    :param entrypoint: 要调用的入口函数名（默认 ``run``），支持同一脚本多函数
    :return: {"output": <入口函数返回值>, "stdout": str, "stderr": str, "error": str | None}
    """
    entrypoint = entrypoint or DEFAULT_ENTRYPOINT
    namespace: dict[str, Any] = {}
    stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
    try:
        compiled = compile(code, "<block>", "exec")
    except SyntaxError as exc:
        raise BlockExecutionError(f"block code syntax error: {exc}") from exc

    with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
        try:
            exec(compiled, namespace)  # noqa: S102 - 隔离沙箱内执行
            entry_fn = namespace.get(entrypoint)
            if not callable(entry_fn):
                raise BlockExecutionError(
                    f"block code must define `def {entrypoint}(inputs): ...`"
                )
            output = entry_fn(inputs)
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


def discover_entrypoints(code: str) -> list[dict[str, Any]]:
    """静态扫描脚本顶层函数定义，返回可作为入口的函数清单（不执行用户代码，安全）。

    入口候选 = 模块顶层、非下划线开头、至少接收一个位置参数（注入 inputs）的函数。
    返回 ``[{"name", "params", "docstring", "is_default"}]``，按出现顺序，``run`` 优先置顶。

    :param code: 用户 Block 脚本源码
    :return: 入口函数元信息列表；语法错误时返回空列表
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    entrypoints: list[dict[str, Any]] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith("_"):
            continue
        params = [arg.arg for arg in node.args.args]
        # 入口须能接收输入参数（无参的工具函数不作为入口暴露）
        if not params and not node.args.vararg and not node.args.kwonlyargs:
            continue
        entrypoints.append({
            "name": node.name,
            "params": params,
            "docstring": (ast.get_docstring(node) or "").strip()[:200],
            "is_default": node.name == DEFAULT_ENTRYPOINT,
        })

    entrypoints.sort(key=lambda e: (not e["is_default"]))
    return entrypoints


def _main() -> None:
    """容器入口：从 stdin 读 {"code", "inputs", "entrypoint"}，结果写 stdout 末行 JSON。"""
    payload = json.loads(sys.stdin.read())
    result = execute_user_code(
        payload["code"],
        payload.get("inputs", {}),
        payload.get("entrypoint", DEFAULT_ENTRYPOINT),
    )
    sys.stdout.write("\n__PYFLOW_RESULT__" + json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    _main()
