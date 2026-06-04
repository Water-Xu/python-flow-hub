"""回复构造（决策 6/7）：carry_fields 透传 + 下游去重键 + 路由键渲染。"""

from __future__ import annotations

import pytest

from pyflow_runtime.reply_builder import build_reply, render_reply_routing_key


def test_build_reply_carries_fields_and_dedup_key():
    source = {"header": {"snowflakeId": "SF1", "type": "order"}}
    reply = build_reply(
        {"ok": True}, source,
        carry_fields=[{"source_path": "$.header.type", "target_field": "type", "required": True}],
        dedup_business_id="SF1",
    )
    assert reply["result"] == {"ok": True}
    assert reply["type"] == "order"
    # 跨块去重键：原样透传业务 ID，不带 retry-count（决策 7 点 6）
    assert reply["snowflakeId"] == "SF1"


def test_build_reply_required_missing_raises():
    with pytest.raises(ValueError):
        build_reply(
            {"ok": True}, {"header": {}},
            carry_fields=[{"source_path": "$.header.snowflakeId",
                           "target_field": "snowflakeId", "required": True}],
        )


def test_build_reply_optional_missing_is_none():
    reply = build_reply(
        {"ok": True}, {"header": {}},
        carry_fields=[{"source_path": "$.header.foo", "target_field": "foo", "required": False}],
    )
    assert reply["foo"] is None


def test_render_routing_key_substitutes_placeholders():
    reply = {"snowflakeId": "SF1"}
    # 接口/Flow 级占位符 {api_id}（决策 3.1 重写为 Flow 级模型 A）
    assert render_reply_routing_key("reply.{api_id}", reply, "api9") == "reply.api9"
    # 兼容旧模板占位符 {block_id}（同样取 scope_id=api_id）
    assert render_reply_routing_key("reply.{block_id}", reply, "api9") == "reply.api9"
    assert render_reply_routing_key("order.{snowflakeId}", reply) == "order.SF1"


def test_render_routing_key_missing_placeholder_is_blank():
    assert render_reply_routing_key("x.{missing}", {}) == "x."


def test_render_routing_key_empty_template():
    assert render_reply_routing_key("", {"a": 1}) == ""
    assert render_reply_routing_key(None, {"a": 1}) == ""
