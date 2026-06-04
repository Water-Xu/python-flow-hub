"""请求级上下文中间件（决策 13：链路连续 + 结构化访问日志）。

为每个请求绑定 request_id / 方法 / 路径到 structlog contextvars，使该请求内所有日志
自动带同一 request_id；从上游 W3C traceparent 提取 trace_id 关联 Cloud Trace；
响应回写 X-Request-Id 便于端到端排障。
"""

from __future__ import annotations

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.observability.logging import get_logger

logger = get_logger("pyflow.access")

REQUEST_ID_HEADER = "X-Request-Id"
# 健康检查/指标不打访问日志，避免探针刷屏（对齐 API 规范"避免重复相似日志"）
_QUIET_PATHS = {"/health/live", "/health/ready", "/health/deps", "/metrics"}


def _extract_trace_id(traceparent: str | None) -> str | None:
    """从 W3C traceparent（version-traceid-spanid-flags）解析 trace_id。"""
    if not traceparent:
        return None
    parts = traceparent.split("-")
    if len(parts) >= 2 and len(parts[1]) == 32:
        return parts[1]
    return None


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        trace_id = _extract_trace_id(request.headers.get("traceparent"))

        structlog.contextvars.clear_contextvars()
        bind = {"request_id": request_id, "method": request.method,
                "path": request.url.path}
        if trace_id:
            bind["trace_id"] = trace_id
        structlog.contextvars.bind_contextvars(**bind)

        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            if request.url.path not in _QUIET_PATHS:
                logger.info(
                    "http_access",
                    status=status_code,
                    duration_ms=round((time.perf_counter() - start) * 1000, 1),
                )
            structlog.contextvars.clear_contextvars()
