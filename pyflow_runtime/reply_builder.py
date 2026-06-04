"""回复构造（决策 6/7）。

carry_fields 透传 + 回复至少一次/下游去重键。跨 Block 传递只认原始业务 ID（snowflakeId），
不携带任何一段的 retry-count（决策 7 点 6）。
"""

from __future__ import annotations

from typing import Any

from pyflow_runtime.condition_engine import extract_path


def build_reply(
    result: dict[str, Any],
    source_payload: dict[str, Any],
    carry_fields: list[dict[str, Any]] | None,
    dedup_business_id: str | None = None,
) -> dict[str, Any]:
    """构造回复消息。

    :param result: 块执行输出
    :param source_payload: 原始入站消息（用于 carry_fields 透传）
    :param carry_fields: [{source_path, target_field, required}]
    :param dedup_business_id: 透传的去重键（原始 snowflakeId），供下游"至少一次"去重
    :raises ValueError: required 字段缺失
    """
    reply: dict[str, Any] = {"result": result}
    for rule in carry_fields or []:
        source_path = rule["source_path"]
        target_field = rule["target_field"]
        required = rule.get("required", True)
        value = extract_path(source_path, source_payload)
        if value is None and required:
            raise ValueError(f"required carry field missing: {source_path}")
        reply[target_field] = value

    # 跨块去重键：原样透传业务 ID，不带 retry-count（决策 7 点 6）
    if dedup_business_id is not None:
        reply.setdefault("snowflakeId", dedup_business_id)
    return reply
