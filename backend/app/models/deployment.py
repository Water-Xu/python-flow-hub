"""FlowDeployment（Flow 部署实例）。"""

from __future__ import annotations

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base_mixin import TimestampMixin, UUIDMixin


class FlowDeployment(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "pyflow_flow_deployment"

    flow_id: Mapped[str] = mapped_column(String(36), index=True)
    flow_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    name: Mapped[str] = mapped_column(String(64))
    # local | k8s
    environment: Mapped[str] = mapped_column(String(16), default="local")
    # 所有部署共用固定 namespace=pyflow-blocks；隔离用资源名前缀 + label
    resource_prefix: Mapped[str] = mapped_column(String(64), default="")
    # building | deploying | running | partially_degraded | stopped
    status: Mapped[str] = mapped_column(String(24), default="stopped")
    entry_endpoint: Mapped[str] = mapped_column(String(256), default="")
    copied_from_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    block_statuses: Mapped[list] = mapped_column(JSON, default=list)
    # 部署级环境变量（注入该部署下全部块；非敏感；优先级：全局 < 部署 < 块）
    env_vars: Mapped[dict] = mapped_column(JSON, default=dict)
    # 部署级 secret 引用（env_name -> secret_key，敏感值走 K8s Secret）
    secret_refs: Mapped[dict] = mapped_column(JSON, default=dict)
    # 部署级 Pod 资源覆盖（按 block_id 维度覆盖 compute_config，
    # 形如 {block_id: {cpu_request, memory_request, cpu_limit, memory_limit, gpu_enabled, gpu_count, gpu_type}}；
    # 部署时合并到对应 block 的 compute_config，仅作用于该部署）
    resource_overrides: Mapped[dict] = mapped_column(JSON, default=dict)
