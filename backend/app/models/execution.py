"""执行态模型：FlowRun（同步编排续跑）+ ExecutionRecord（执行历史）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base_mixin import TimestampMixin, UUIDMixin


class FlowRun(Base, UUIDMixin, TimestampMixin):
    """同步编排执行态（决策 10，控制面重启续跑）。"""

    __tablename__ = "pyflow_flow_run"

    flow_deployment_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    flow_id: Mapped[str] = mapped_column(String(36), index=True)
    dag_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    # running | succeeded | failed | canceled
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)
    # {node_id: {status, output_pointer, error}}
    node_states: Mapped[dict] = mapped_column(JSON, default=dict)
    # 多副本续跑（4a）：lease + fence
    owner_pod: Mapped[str | None] = mapped_column(String(128), nullable=True)
    fence_token: Mapped[int] = mapped_column(Integer, default=0)
    lease_expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 调用来源追踪（dashboard 展示用）
    api_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # http | mq | manual | stream
    trigger_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ExecutionRecord(Base, UUIDMixin, TimestampMixin):
    """单块执行历史与日志。"""

    __tablename__ = "pyflow_execution"

    block_id: Mapped[str] = mapped_column(String(36), index=True)
    flow_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    login_id: Mapped[str] = mapped_column(String(64), index=True)
    # pending | running | success | failed | timeout
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    stdout: Mapped[str] = mapped_column(Text, default="")
    stderr: Mapped[str] = mapped_column(Text, default="")
    error_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
