"""structlog JSON 日志（stdout → Cloud Logging，决策 13）。

含 logging.googleapis.com/trace 关联字段，实现 Cloud Logging ↔ Cloud Trace 跨产品跳转。
"""

from __future__ import annotations

import logging

import structlog

from app.config import get_settings

settings = get_settings()


def configure_logging() -> None:
    logging.basicConfig(format="%(message)s", level=logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _inject_trace,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _inject_trace(_: object, __: str, event_dict: dict) -> dict:
    trace_id = event_dict.pop("trace_id", None)
    if trace_id:
        event_dict["logging.googleapis.com/trace"] = (
            f"projects/{settings.gcp_project}/traces/{trace_id}"
        )
    return event_dict


def get_logger(name: str = "pyflow"):
    return structlog.get_logger(name)
