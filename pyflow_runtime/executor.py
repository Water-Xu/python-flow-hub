"""用户代码执行框架（在沙箱容器 / runner Pod 内运行）。

约定：用户 Block 代码须定义至少一个入口函数 `def 函数名(inputs: dict) -> dict`，
默认入口为 `run`；一个脚本可暴露多个入口函数，由调用方通过 entrypoint 选择。
本模块负责注入输入、调用、捕获输出与异常，构成 docker_executor / k8s job / 常驻消费者三处的统一执行内核。
"""

from __future__ import annotations

import ast
import inspect
import io
import json
import sys
import traceback
from collections.abc import Iterator
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


def execute_user_code_stream(
    code: str,
    inputs: dict[str, Any],
    entrypoint: str = DEFAULT_ENTRYPOINT,
) -> Iterator[dict[str, Any]]:
    """流式执行用户代码：入口函数为生成器（``yield``）时实时产出每个 chunk。

    与 :func:`execute_user_code` 的区别：入口函数用 ``yield`` 逐段返回（如 LLM token 流）时，
    本生成器逐个产出 ``{"type": "chunk", "data": <yield 值>}``；非生成器入口则等价于一次性执行。
    无论哪种情形，最后都产出一个 ``{"type": "result", ...}`` 终止事件（结构同 ``execute_user_code`` 返回值）。

    捕获 stdout/stderr 仅在用户代码推进期间生效（每次 ``next`` 进出 redirect 上下文），
    确保事件之间控制权回到调用方时不会误吞调用方写入真实 stdout 的协议行。

    :param code: 用户 Block 脚本源码
    :param inputs: 注入入口函数的输入字典
    :param entrypoint: 要调用的入口函数名（默认 ``run``）
    :return: 事件迭代器：``{"type": "chunk", "data": ...}`` 若干 + 末尾 ``{"type": "result", ...}``
    """
    entrypoint = entrypoint or DEFAULT_ENTRYPOINT
    namespace: dict[str, Any] = {}
    stdout_buf, stderr_buf = io.StringIO(), io.StringIO()

    try:
        compiled = compile(code, "<block>", "exec")
    except SyntaxError as exc:
        yield {
            "type": "result",
            "output": None,
            "stdout": "",
            "stderr": "",
            "error": f"block code syntax error: {exc}",
        }
        return

    # 编译执行模块体 + 取入口函数（此阶段 stdout 全程重定向到缓冲）
    try:
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            exec(compiled, namespace)  # noqa: S102 - 隔离沙箱内执行
            entry_fn = namespace.get(entrypoint)
            if not callable(entry_fn):
                raise BlockExecutionError(
                    f"block code must define `def {entrypoint}(inputs): ...`"
                )
    except Exception as exc:  # noqa: BLE001
        yield {
            "type": "result",
            "output": None,
            "stdout": stdout_buf.getvalue(),
            "stderr": stderr_buf.getvalue() + traceback.format_exc(),
            "error": str(exc),
        }
        return

    # 生成器入口：逐 yield 产出 chunk；普通入口：一次执行，若返回生成器同样按流处理
    if inspect.isgeneratorfunction(entry_fn):
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            gen = entry_fn(inputs)
        yield from _stream_from_generator(gen, stdout_buf, stderr_buf)
        return

    try:
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            output = entry_fn(inputs)
    except Exception as exc:  # noqa: BLE001
        yield {
            "type": "result",
            "output": None,
            "stdout": stdout_buf.getvalue(),
            "stderr": stderr_buf.getvalue() + traceback.format_exc(),
            "error": str(exc),
        }
        return

    if inspect.isgenerator(output):
        yield from _stream_from_generator(output, stdout_buf, stderr_buf)
        return

    yield {
        "type": "result",
        "output": output,
        "stdout": stdout_buf.getvalue(),
        "stderr": stderr_buf.getvalue(),
        "error": None,
    }


def _stream_from_generator(
    gen: Iterator[Any], stdout_buf: io.StringIO, stderr_buf: io.StringIO
) -> Iterator[dict[str, Any]]:
    """驱动用户生成器：每次 ``next`` 在 redirect 上下文内推进，逐 chunk 产出；末尾产出 result。

    生成器的 ``return`` 值（``StopIteration.value``）作为最终 output（多数纯流场景为 None）。
    """
    final_output: Any = None
    while True:
        try:
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                chunk = next(gen)
        except StopIteration as stop:
            final_output = stop.value
            break
        except Exception as exc:  # noqa: BLE001
            yield {
                "type": "result",
                "output": None,
                "stdout": stdout_buf.getvalue(),
                "stderr": stderr_buf.getvalue() + traceback.format_exc(),
                "error": str(exc),
            }
            return
        yield {"type": "chunk", "data": chunk}

    yield {
        "type": "result",
        "output": final_output,
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
