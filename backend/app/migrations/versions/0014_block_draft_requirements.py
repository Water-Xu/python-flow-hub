"""新增 pyflow_block.draft_requirements 字段，保存块 pip 依赖草稿。

Revision ID: 0014_block_draft_requirements
Revises: 0013_flow_entry_node
Create Date: 2026-06-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_block_draft_requirements"
down_revision = "0013_flow_entry_node"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_column("pyflow_block", "draft_requirements"):
        op.add_column(
            "pyflow_block",
            sa.Column("draft_requirements", sa.Text(), nullable=False, server_default=""),
        )


def downgrade() -> None:
    if _has_column("pyflow_block", "draft_requirements"):
        op.drop_column("pyflow_block", "draft_requirements")
