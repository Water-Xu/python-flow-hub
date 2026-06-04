"""接口文档 — MQ 调用方式信息生成（决策 3.1/6）。

接口门户 / 接口管理在展示 HTTP 调用参数之外，还需说明流程内支持 MQ 异步触发的块
（execution_mode 为 async_mq / both）该如何通过消息队列调用：队列 / 交换机 / 路由键、
消息体格式、input_mapping 提取规则、条件订阅、回复与重试策略，并提供可直接 Mock 测试的
示例消息体。该模块从 Block.mq_config 与 input_ports 生成只读文档片段，供前端渲染与测试预填。
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


def build_mq_invocation(block: Any) -> dict[str, Any] | None:
    """为单个调用块生成 MQ 调用方式文档；非 MQ 块返回 None。

    :param block: Block ORM 实例（需含 id / execution_mode / mq_config / input_ports）。
    :return: MQ 调用信息字典（队列拓扑、消息格式、映射规则、重试/回复策略、示例消息体），
             块非 async_mq/both 时返回 None。
    """
    if getattr(block, "execution_mode", "sync_http") not in ("async_mq", "both"):
        return None

    # 延迟导入，与控制面对 pyflow_runtime 的统一约定一致（避免导入顺序耦合）
    from pyflow_runtime.backoff_queue import dlq_queue, main_queue

    cfg = block.mq_config or {}
    queue = cfg.get("queue") or main_queue(block.id)
    exchange = (cfg.get("exchange") or "").strip()
    routing_key = (cfg.get("routing_key") or "").strip() or queue
    input_mapping = cfg.get("input_mapping") or {}

    # 生成示例消息体：header（含幂等键）+ 各输入端口占位值（零配置直通场景）
    body: dict[str, Any] = {
        "header": {"snowflakeId": "雪花ID（幂等键，留空自动生成）"},
    }
    for port in block.input_ports or []:
        name = _port_name(port)
        if name:
            body[name] = _sample_for(port)

    return {
        "block_id": block.id,
        "block_name": block.name,
        "execution_mode": block.execution_mode,
        # ── 队列拓扑 ──
        "queue": queue,
        "exchange": exchange or "(default exchange)",
        "routing_key": routing_key,
        "dlq_queue": dlq_queue(block.id),
        # ── 条件订阅 ──
        "condition_language": cfg.get("condition_language") or "jmespath",
        "condition_expression": cfg.get("condition_expression") or "",
        # ── 字段映射（消息字段 → 块输入）──
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
