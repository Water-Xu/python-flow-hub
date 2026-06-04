"""PublishedApi — 流程发布接口模型。

用户将 Flow 发布为可调用的 HTTP 接口；管理员可查看文档、监控流量、配置限流/负载/降级策略并锁定接口。
锁定后关联的 Block/Flow 只读，禁止任何修改，只允许创建副本/新版本。
"""

from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base_mixin import TimestampMixin, UUIDMixin


class PublishedApi(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "pyflow_published_api"

    # 基本信息
    name: Mapped[str] = mapped_column(String(128), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    # URL slug，唯一；调用路径为 /api/public/{path}
    path: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    # 接口标签（逗号分隔）
    tags: Mapped[str] = mapped_column(String(256), default="")

    # 关联流程
    # flow_id: 发布时绑定的原始流程（锁定后该流程只读）
    flow_id: Mapped[str] = mapped_column(String(36), index=True)
    # active_flow_id: 当前实际调用的流程（可与 flow_id 不同，用于平滑过渡）
    active_flow_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    owner_login_id: Mapped[str] = mapped_column(String(64), index=True)
    # active | paused | deprecated
    status: Mapped[str] = mapped_column(String(16), default="active")

    # ── 锁定（管理员操作） ──
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    lock_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    locked_at: Mapped[str | None] = mapped_column(String(32), nullable=True)  # ISO datetime string

    # ── 限流策略 ──
    rate_limit_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=60)

    # ── 负载均衡策略 ──
    # round_robin | least_conn | ip_hash（Phase 4+ K8s 实际生效）
    load_balance_strategy: Mapped[str] = mapped_column(String(32), default="round_robin")

    # ── 降级策略 ──
    degradation_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # 降级时返回的 fallback JSON
    degradation_fallback: Mapped[dict] = mapped_column(JSON, default=dict)

    # ── 流量统计（累计值；每次调用更新） ──
    total_calls: Mapped[int] = mapped_column(BigInteger, default=0)
    success_calls: Mapped[int] = mapped_column(BigInteger, default=0)
    error_calls: Mapped[int] = mapped_column(BigInteger, default=0)
    avg_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
