"""FastAPI 入口。

lifespan 仅 dev local 启动单消费者（连本机 docker daemon 调试）；
生产队列由 Block Pod 消费，控制面不常驻消费（决策 3.1 模型 A）。
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    router_blocks,
    router_deployments,
    router_execution,
    router_flows,
    router_health,
    router_rbac,
    router_ws,
)
from app.api import router_api_portal, router_api_admin
from app.config import get_settings
from app.db import init_models
from app.errors import BusinessException, business_exception_handler
from app.observability.logging import configure_logging, get_logger
from app.observability.tracing import configure_tracing

settings = get_settings()
logger = get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info("pyflow_startup", mode=settings.deployment_mode)
    await init_models()
    # 生产队列由 Block Pod 消费；控制面仅 dev local 才按需启动单消费者（此处省略）
    yield
    logger.info("pyflow_shutdown")


app = FastAPI(
    title="PyFlowHub Control Plane",
    version="0.1.0",
    description="Python 可视化调用中台 — 控制面（编排/部署/拓扑生成）",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(BusinessException, business_exception_handler)

app.include_router(router_health.router)
app.include_router(router_blocks.router)
app.include_router(router_flows.router)
app.include_router(router_execution.router)
app.include_router(router_deployments.router)
app.include_router(router_rbac.router)
app.include_router(router_ws.router)
app.include_router(router_api_portal.router)
app.include_router(router_api_admin.router)

configure_tracing(app)


@app.get("/")
async def root():
    return {"service": "pyflow-hub", "version": "0.1.0", "mode": settings.deployment_mode}
