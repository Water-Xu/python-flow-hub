"""新增 pyflow_published_api.entrypoint 字段，支持 API 级入口函数绑定。

Revision ID: 0010_api_entrypoint
Revises: 0009_flow_level_mq
Create Date: 2026-06-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_api_entrypoint"
down_revision = "0009_flow_level_mq"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pyflow_published_api",
        sa.Column("entrypoint", sa.String(128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pyflow_published_api", "entrypoint")
