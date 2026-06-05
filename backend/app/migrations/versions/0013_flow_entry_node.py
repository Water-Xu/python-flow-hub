"""新增 pyflow_flow.entry_node_id 字段，支持一条 Flow 指定单一 API 入口节点。

Revision ID: 0013_flow_entry_node
Revises: 0012_api_entrypoint_map
Create Date: 2026-06-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_flow_entry_node"
down_revision = "0012_api_entrypoint_map"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    """探测列是否已存在，使迁移可重入。"""
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_column("pyflow_flow", "entry_node_id"):
        op.add_column(
            "pyflow_flow",
            sa.Column("entry_node_id", sa.String(length=36), nullable=True),
        )


def downgrade() -> None:
    if _has_column("pyflow_flow", "entry_node_id"):
        op.drop_column("pyflow_flow", "entry_node_id")
