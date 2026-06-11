"""新增 pyflow_published_api.entry_node_id 字段，支持同一 Flow 被多个接口以不同子图入口发布。

Revision ID: 0015_api_entry_node_id
Revises: 0014_block_draft_requirements
Create Date: 2026-06-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_api_entry_node_id"
down_revision = "0014_block_draft_requirements"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_column("pyflow_published_api", "entry_node_id"):
        op.add_column(
            "pyflow_published_api",
            sa.Column("entry_node_id", sa.String(length=36), nullable=True),
        )


def downgrade() -> None:
    if _has_column("pyflow_published_api", "entry_node_id"):
        op.drop_column("pyflow_published_api", "entry_node_id")
