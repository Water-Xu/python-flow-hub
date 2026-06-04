"""OpenTelemetry Python SDK 接入（决策 13）。

入站续接上游 W3C/B3 traceparent；OTLP HTTP → 同一个 otel-collector:4318。
"""

from __future__ import annotations

import logging

from app.config import get_settings

settings = get_settings()

# OTLP 导出是 best-effort 遥测：collector 不可达时 SDK 会按 ERROR + 堆栈反复刷日志，
# 经 stdout 进入 Cloud Error Reporting 形成误报噪声。这里把导出器/批处理器的内部
# 连接错误降噪到 CRITICAL（仅静默重复的传输失败，不影响真实业务错误上报）。
_NOISY_OTEL_LOGGERS = (
    "opentelemetry.exporter.otlp.proto.http.trace_exporter",
    "opentelemetry.sdk.trace.export",
)


def _silence_exporter_noise() -> None:
    for name in _NOISY_OTEL_LOGGERS:
        logging.getLogger(name).setLevel(logging.CRITICAL)


def configure_tracing(app) -> None:
    """配置 OTel；未设 OTLP endpoint 时跳过（dev 本地）。"""
    if not settings.otlp_endpoint:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        return

    _silence_exporter_noise()

    provider = TracerProvider(resource=Resource.create({"service.name": "pyflow-hub"}))
    # 显式 timeout：导出失败快速放弃，避免请求/批处理线程长时间堆积
    exporter = OTLPSpanExporter(endpoint=f"{settings.otlp_endpoint}/v1/traces", timeout=5)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
