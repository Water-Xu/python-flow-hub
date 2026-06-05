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


def _has_column(table: str, column: str) -> bool:
    """探测列是否已存在，使迁移可重入（历史环境可能已手工/部分执行过本变更）。"""
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_column("pyflow_published_api", "entrypoint"):
        op.add_column(
            "pyflow_published_api",
            sa.Column("entrypoint", sa.String(128), nullable=True),
        )


def downgrade() -> None:
    if _has_column("pyflow_published_api", "entrypoint"):
        op.drop_column("pyflow_published_api", "entrypoint")
