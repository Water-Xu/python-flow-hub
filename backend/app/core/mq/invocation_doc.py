"""接口文档 — MQ 调用方式信息生成（决策 3.1/6，Flow 级触发）。

接口门户 / 接口管理在展示 HTTP 调用参数之外，还需说明触发方式为 mq / both 的接口
该如何通过消息队列触发整条 Flow：队列 / 交换机 / 路由键、消息体格式、input_mapping
提取规则、条件订阅、回复与重试策略，并提供可直接 Mock 测试的示例消息体。
该模块从 PublishedApi.mq_config 与流程入口端口生成只读文档片段，供前端渲染与测试预填。
"""

from __future__ import annotations

from typing import Any

# 端口类型 → 示例值（用于生成 Mock 消息体占位）
_TYPE_SAMPLES: dict[str, Any] = {
    "string": "示例文本",
    "str": "示例文本",
    "text": "示例文本",
    "int": 0,
    "integer": 0,
    "number": 0,
    "float": 0.0,
    "double": 0.0,
    "bool": True,
    "boolean": True,
    "list": [],
    "array": [],
    "dict": {},
    "object": {},
    "json": {},
}


def _port_name(port: Any) -> str | None:
    """端口可能是 dict（JSON 列）或 Port 对象，统一取 name。"""
    if isinstance(port, dict):
        return port.get("name")
    return getattr(port, "name", None)


def _port_type(port: Any) -> str:
    if isinstance(port, dict):
        return port.get("type") or "any"
    return getattr(port, "type", "any") or "any"


def _sample_for(port: Any) -> Any:
    return _TYPE_SAMPLES.get(_port_type(port).lower(), "...")


def build_mq_invocation(
    api: Any,
    entry_input_ports: list[Any] | None = None,
) -> dict[str, Any] | None:
    """为接口生成 MQ 触发方式文档；纯 http 触发返回 None。

    :param api: PublishedApi ORM 实例（需含 id / trigger_type / mq_config）。
    :param entry_input_ports: 流程入口块的 input_ports，用于生成示例消息体（可选）。
    :return: MQ 触发信息字典（队列拓扑、消息格式、映射规则、重试/回复策略、示例消息体），
             接口触发方式非 mq/both 时返回 None。
    """
    if getattr(api, "trigger_type", "http") not in ("mq", "both"):
        return None

    # 延迟导入，与控制面对 pyflow_runtime 的统一约定一致（避免导入顺序耦合）
    from pyflow_runtime.backoff_queue import dlq_queue, main_queue

    cfg = api.mq_config or {}
    queue = cfg.get("queue") or main_queue(api.id)
    exchange = (cfg.get("exchange") or "").strip()
    routing_key = (cfg.get("routing_key") or "").strip() or queue
    input_mapping = cfg.get("input_mapping") or {}

    # 生成示例消息体：header（含幂等键）+ 流程入口端口占位值（零配置直通场景）
    body: dict[str, Any] = {
        "header": {"snowflakeId": "雪花ID（幂等键，留空自动生成）"},
    }
    for port in entry_input_ports or []:
        name = _port_name(port)
        if name:
            body[name] = _sample_for(port)

    return {
        "api_id": api.id,
        "api_name": api.name,
        "trigger_type": api.trigger_type,
        # ── 队列拓扑 ──
        "queue": queue,
        "exchange": exchange or "(default exchange)",
        "routing_key": routing_key,
        "dlq_queue": dlq_queue(api.id),
        # ── 条件订阅 ──
        "condition_language": cfg.get("condition_language") or "jmespath",
        "condition_expression": cfg.get("condition_expression") or "",
        # ── 字段映射（消息字段 → 流程输入）──
        "input_mapping": input_mapping,
        # ── 回复 ──
        "reply_enabled": bool(cfg.get("reply_enabled")),
        "reply_exchange": cfg.get("reply_exchange") or "",
        "reply_routing_key_template": cfg.get("reply_routing_key_template") or "",
        # ── 重试 ──
        "max_retry": cfg.get("max_retry", 3),
        "retry_delay_ms": cfg.get("retry_delay_ms", 5000),
        # ── Mock 示例消息体 ──
        "message_example": body,
    }
