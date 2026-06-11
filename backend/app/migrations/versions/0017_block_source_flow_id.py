"""新增 pyflow_block.source_flow_id 字段，用于标记 zip 导入时的来源 Flow，支持分组展示与级联删除。

Revision ID: 0017_block_source_flow_id
Revises: 0016_deployment_type
Create Date: 2026-06-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_block_source_flow_id"
down_revision = "0016_deployment_type"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_column("pyflow_block", "source_flow_id"):
        op.add_column(
            "pyflow_block",
            sa.Column("source_flow_id", sa.String(length=36), nullable=True),
        )
        op.create_index("ix_pyflow_block_source_flow_id", "pyflow_block", ["source_flow_id"])


def downgrade() -> None:
    if _has_column("pyflow_block", "source_flow_id"):
        op.drop_index("ix_pyflow_block_source_flow_id", table_name="pyflow_block")
        op.drop_column("pyflow_block", "source_flow_id")
