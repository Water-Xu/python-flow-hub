"""OpenTelemetry Python SDK 接入（决策 13）。

入站续接上游 W3C/B3 traceparent；OTLP HTTP → 同一个 otel-collector:4318。
"""

from __future__ import annotations

from app.config import get_settings

settings = get_settings()


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

    provider = TracerProvider(resource=Resource.create({"service.name": "pyflow-hub"}))
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{settings.otlp_endpoint}/v1/traces"))
    )
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
