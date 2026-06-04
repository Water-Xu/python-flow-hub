"""flow 增加压缩包导入相关列：source / tree / resources

Revision ID: 0002_flow_import
Revises: 0001_init
Create Date: 2026-06-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_flow_import"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pyflow_flow",
        sa.Column("source", sa.String(length=16), nullable=False, server_default="blank"),
    )
    op.add_column("pyflow_flow", sa.Column("tree", sa.JSON(), nullable=True))
    op.add_column("pyflow_flow", sa.Column("resources", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("pyflow_flow", "resources")
    op.drop_column("pyflow_flow", "tree")
    op.drop_column("pyflow_flow", "source")
