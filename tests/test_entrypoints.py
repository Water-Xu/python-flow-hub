"""一脚本多入口函数单测（AIR：全自动 / 独立 / 可重复，零外部服务）。

覆盖：
- discover_entrypoints 静态扫描多函数 / 过滤私有函数 / 语法错误兜底；
- execute_user_code 指定 entrypoint 调用正确函数、默认 run 兼容、缺失入口报错；
- flow_runner 经节点 config.entrypoint 透传到 node_executor。
"""

from __future__ import annotations

import pytest

from pyflow_runtime.executor import (
    BlockExecutionError,
    discover_entrypoints,
    execute_user_code,
)

from app.core.flow.flow_runner import run_flow

_MULTI_FN_CODE = (
    "def run(inputs):\n"
    "    return {'who': 'run', 'v': inputs.get('v', 0)}\n"
    "\n"
    "def double(inputs):\n"
    "    '''把 v 翻倍。'''\n"
    "    return {'who': 'double', 'v': inputs.get('v', 0) * 2}\n"
    "\n"
    "def _helper(x):\n"
    "    return x\n"
)


# ── discover_entrypoints ──────────────────────────────────────────────────────

def test_discover_lists_public_functions_with_params():
    eps = discover_entrypoints(_MULTI_FN_CODE)
    names = [e["name"] for e in eps]
    assert names == ["run", "double"]  # run 置顶；_helper 被过滤
    double = next(e for e in eps if e["name"] == "double")
    assert double["params"] == ["inputs"]
    assert "翻倍" in double["docstring"]


def test_discover_filters_private_and_zero_arg():
    code = (
        "def _private(inputs):\n    return inputs\n"
        "def no_args():\n    return 1\n"
        "def good(inputs):\n    return inputs\n"
    )
    names = [e["name"] for e in discover_entrypoints(code)]
    assert names == ["good"]


def test_discover_syntax_error_returns_empty():
    assert discover_entrypoints("def broken(:\n  pass") == []


# ── execute_user_code entrypoint ──────────────────────────────────────────────

def test_execute_default_entrypoint_run():
    result = execute_user_code(_MULTI_FN_CODE, {"v": 3})
    assert result["error"] is None
    assert result["output"] == {"who": "run", "v": 3}


def test_execute_named_entrypoint():
    result = execute_user_code(_MULTI_FN_CODE, {"v": 3}, entrypoint="double")
    assert result["error"] is None
    assert result["output"] == {"who": "double", "v": 6}


def test_execute_missing_entrypoint_raises():
    with pytest.raises(BlockExecutionError) as exc:
        execute_user_code(_MULTI_FN_CODE, {}, entrypoint="not_exist")
    assert "not_exist" in str(exc.value)


# ── flow_runner 透传 entrypoint ───────────────────────────────────────────────

async def test_flow_runner_passes_entrypoint_from_config():
    nodes = [
        {"id": "a", "node_type": "block", "block_id": "b1", "config": {"entrypoint": "double"}},
        {"id": "b", "node_type": "block", "block_id": "b1", "config": {}},
    ]
    edges = []
    seen: dict[str, str] = {}

    async def node_executor(node, inputs):
        seen[node["id"]] = (node.get("config") or {}).get("entrypoint") or "run"
        return {"ok": True}

    await run_flow(nodes, edges, {}, node_executor)
    assert seen == {"a": "double", "b": "run"}
