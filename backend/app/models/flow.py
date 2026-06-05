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
    # 来源：blank（手工编排）| zip_import（压缩包导入）
    source: Mapped[str] = mapped_column(String(16), default="blank")
    # 压缩包导入后的文件夹树：{name, kind: folder|block|resource, path, children?, block_id?, node_id?}
    tree: Mapped[dict] = mapped_column(JSON, default=dict)
    # 非 py 文件（资源）的文本内容：{相对路径: 文本}
    resources: Mapped[dict] = mapped_column(JSON, default=dict)


class FlowNode(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "pyflow_flow_node"

    flow_id: Mapped[str] = mapped_column(String(36), ForeignKey("pyflow_flow.id"), index=True)
    # block | condition_branch | input | note（纯视觉便签，不参与执行）
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
