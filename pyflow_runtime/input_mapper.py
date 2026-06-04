"""消息字段 → Block input_ports 映射（决策 3.1）。"""

from __future__ import annotations

from typing import Any

from pyflow_runtime.condition_engine import extract_path


def map_inputs(
    payload: dict[str, Any],
    input_mapping: dict[str, str] | None,
    language: str = "jsonpath",
) -> dict[str, Any]:
    """按 input_mapping（目标字段名 → 源路径）从 payload 抽取输入。

    无映射时直接返回原 payload，使最简单的块零配置可用。
    """
    if not input_mapping:
        return dict(payload)
    result: dict[str, Any] = {}
    for target_field, source_path in input_mapping.items():
        result[target_field] = extract_path(source_path, payload, language)
    return result
