"""Flow / 节点 / 边 模型。"""

from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base_mixin import TimestampMixin, UUIDMixin


class Flow(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "pyflow_flow"

    name: Mapped[str] = mapped_column(String(128), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    owner_login_id: Mapped[str] = mapped_column(String(64), index=True)
    stable_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class FlowNode(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "pyflow_flow_node"

    flow_id: Mapped[str] = mapped_column(String(36), ForeignKey("pyflow_flow.id"), index=True)
    # block | condition_branch
    node_type: Mapped[str] = mapped_column(String(32), default="block")
    block_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # 画布坐标 / 分支配置等
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    position: Mapped[dict] = mapped_column(JSON, default=dict)


class FlowEdge(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "pyflow_flow_edge"

    flow_id: Mapped[str] = mapped_column(String(36), ForeignKey("pyflow_flow.id"), index=True)
    source_node_id: Mapped[str] = mapped_column(String(36))
    target_node_id: Mapped[str] = mapped_column(String(36))
    source_port: Mapped[str] = mapped_column(String(64), default="output")
    target_port: Mapped[str] = mapped_column(String(64), default="input")
