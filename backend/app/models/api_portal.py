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
    # API 级入口函数名称（None = 使用各节点 config.entrypoint 或默认 run）
    # 全局覆盖（保留向后兼容）：设置后覆盖流程内所有未在 entrypoint_map 指定的节点。
    entrypoint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 节点级入口函数映射 {node_id: entrypoint_name}：优先级高于全局 entrypoint。
    # 解决多个调用块含同名内置函数（如都含 run）时，需对每个块分别指定入口的场景。
    entrypoint_map: Mapped[dict] = mapped_column(JSON, default=dict)

    owner_login_id: Mapped[str] = mapped_column(String(64), index=True)
    # active | paused | deprecated
    status: Mapped[str] = mapped_column(String(16), default="active")

    # ── 触发方式（决策 3.1 模型 A 重写为 Flow/接口级） ──
    # http：仅同步 HTTP 调用；mq：仅 MQ 异步触发；both：两者皆可
    trigger_type: Mapped[str] = mapped_column(String(16), default="http")
    # MQ 触发配置（queue/exchange/routing_key/input_mapping/condition/reply/retry 等）；
    # 队列按接口 id 命名 flow.{api_id}.queue，消费者每条消息读 active_flow_id 跑整条 Flow。
    mq_config: Mapped[dict] = mapped_column(JSON, default=dict)

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

    # ── 加密保护（AES-256-GCM；每个接口独立开关与密钥） ──
    # 总开关：开启后服务端解密请求 inputs、加密响应 outputs
    encryption_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # 32 字节密钥的 hex 字符串（64 chars），首次开启时自动生成；密钥仅创建者可查看，禁止下发到公开文档
    encryption_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 是否强制要求调用方加密：为 True 时拒绝明文请求（PYFLOW_API_ENCRYPTION_REQUIRED）；
    # 为 False 时兼容明文与密文（密文按 encryption_key 解密，明文直接执行），便于灰度迁移
    require_encrypted_request: Mapped[bool] = mapped_column(Boolean, default=False)

    # ── 流量统计（累计值；每次调用更新） ──
    total_calls: Mapped[int] = mapped_column(BigInteger, default=0)
    success_calls: Mapped[int] = mapped_column(BigInteger, default=0)
    error_calls: Mapped[int] = mapped_column(BigInteger, default=0)
    avg_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
