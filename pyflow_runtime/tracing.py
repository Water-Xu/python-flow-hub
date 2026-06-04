"""OTel 传播复用（决策 13）。

MQ publish 时把 traceparent 写入消息头透传给下游 Block；入站续接同一 trace。
pyflow_runtime 与控制面共用同一套传播逻辑。
"""

from __future__ import annotations

from typing import Any

try:
    from opentelemetry import propagate
    from opentelemetry.context import Context

    _OTEL_AVAILABLE = True
except ImportError:  # 容器内可能未装 otel，降级为 no-op
    _OTEL_AVAILABLE = False


def inject_trace_headers(headers: dict[str, Any]) -> dict[str, Any]:
    """把当前 trace 上下文注入消息头（W3C traceparent）。"""
    if not _OTEL_AVAILABLE:
        return headers
    propagate.inject(headers)
    return headers


def extract_trace_context(headers: dict[str, Any]) -> "Context | None":
    """从消息头解析上游 trace 上下文，用于续接同一 trace。"""
    if not _OTEL_AVAILABLE:
        return None
    return propagate.extract(headers)
