"""版本快照模型（决策 8：大字段存 MinIO，DB 只存指针 + sha 对账）。"""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base_mixin import TimestampMixin, UUIDMixin


class BlockVersion(Base, UUIDMixin, TimestampMixin):
    """Block 代码版本快照。大字段（code/notebook/requirements）存 MinIO。"""

    __tablename__ = "pyflow_block_version"

    block_id: Mapped[str] = mapped_column(String(36), index=True)
    version_tag: Mapped[str] = mapped_column(String(64), default="")
    commit_message: Mapped[str] = mapped_column(Text, default="")
    is_stable: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(64), default="")

    # MinIO 指针（minio://bucket/{block_id}/{version_id}/code.py 等）
    code_path: Mapped[str] = mapped_column(String(512), default="")
    notebook_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    requirements_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # 小字段直接存 DB（列表展示 / diff 元数据）
    input_ports: Mapped[list] = mapped_column(JSON, default=list)
    output_ports: Mapped[list] = mapped_column(JSON, default=list)
    requirements_hash: Mapped[str] = mapped_column(String(64), default="")
    # MinIO 对象内容校验，写入后比对，读路径据此判损坏（对账依据）
    content_sha256: Mapped[str] = mapped_column(String(64), default="")


class FlowVersion(Base, UUIDMixin, TimestampMixin):
    """Flow 版本快照：所有节点 + 边 + 分支配置的完整 JSON 存 MinIO。"""

    __tablename__ = "pyflow_flow_version"

    flow_id: Mapped[str] = mapped_column(String(36), index=True)
    version_tag: Mapped[str] = mapped_column(String(64), default="")
    commit_message: Mapped[str] = mapped_column(Text, default="")
    is_stable: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(64), default="")

    snapshot_path: Mapped[str] = mapped_column(String(512), default="")
    content_sha256: Mapped[str] = mapped_column(String(64), default="")

    node_count: Mapped[int] = mapped_column(Integer, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, default=0)
