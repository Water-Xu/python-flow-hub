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
    # pip 依赖清单草稿；发布版本时写入 MinIO requirements.txt 并触发依赖层镜像构建（决策 11）
    draft_requirements: Mapped[str] = mapped_column(Text, default="")
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

    # 块在 Flow 内一律作为 HTTP invoke 服务被驱动；MQ 触发已上移到接口/Flow 级（PublishedApi.mq_config）
    compute_config: Mapped[dict] = mapped_column(JSON, default=dict)
