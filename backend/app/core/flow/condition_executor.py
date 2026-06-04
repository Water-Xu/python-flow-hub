"""分支节点路径激活逻辑（同步编排，决策 10）。

控制面在内存求值后只激活命中路径；复用 pyflow_runtime.condition_engine 保证语义一致。
"""

from __future__ import annotations

from typing import Any

from pyflow_runtime.condition_engine import evaluate_condition, extract_path


def resolve_branch(node_config: dict[str, Any], payload: dict[str, Any]) -> str:
    """对条件分支节点求值，返回命中的输出端口名。"""
    subtype = node_config.get("subtype", "if_else")
    language = node_config.get("condition_language", "jmespath")

    if subtype == "if_else":
        expr = node_config.get("condition_expression", "")
        hit = evaluate_condition(expr, language, payload)
        return node_config.get("true_port" if hit else "false_port", "")

    # switch_case
    switch_field = node_config.get("switch_field", "")
    value = extract_path(switch_field, payload, language)
    for case in node_config.get("branches", []):
        if str(case.get("value")) == str(value):
            return case.get("port", "")
    return node_config.get("default_port", "")
