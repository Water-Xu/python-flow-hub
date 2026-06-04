"""Block（调用块）模型。"""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base_mixin import TimestampMixin, UUIDMixin


class Block(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "pyflow_block"

    name: Mapped[str] = mapped_column(String(128), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    # 资源属主（决策 15）
    owner_login_id: Mapped[str] = mapped_column(String(64), index=True)
    # script | notebook | gcp_bigquery | gcp_storage
    type: Mapped[str] = mapped_column(String(32), default="script")

    # 草稿（DB 内，未发布，不超过 100KB）
    draft_code: Mapped[str] = mapped_column(Text, default="")
    draft_notebook: Mapped[dict] = mapped_column(JSON, default=dict)

    stable_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    input_ports: Mapped[list] = mapped_column(JSON, default=list)
    output_ports: Mapped[list] = mapped_column(JSON, default=list)
    # 脚本暴露的入口函数清单：[{name, description, params}]，由 AST 扫描自动回填
    entrypoints: Mapped[list] = mapped_column(JSON, default=list)
    requirements_hash: Mapped[str] = mapped_column(String(64), default="")

    # 仅非敏感 env；敏感值走 secret_refs（决策 14/15）
    env_vars: Mapped[dict] = mapped_column(JSON, default=dict)
    secret_refs: Mapped[dict] = mapped_column(JSON, default=dict)
    gcp_resource_scope: Mapped[list] = mapped_column(JSON, default=list)

    # sync_http | async_mq | both
    execution_mode: Mapped[str] = mapped_column(String(16), default="sync_http")
    mq_config: Mapped[dict] = mapped_column(JSON, default=dict)
    compute_config: Mapped[dict] = mapped_column(JSON, default=dict)
