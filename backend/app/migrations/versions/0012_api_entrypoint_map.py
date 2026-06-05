"""新增 pyflow_published_api.entrypoint_map 字段，支持节点级入口函数绑定。

Revision ID: 0012_api_entrypoint_map
Revises: 0011_api_encryption
Create Date: 2026-06-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_api_entrypoint_map"
down_revision = "0011_api_encryption"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    """探测列是否已存在，使迁移可重入。"""
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_column("pyflow_published_api", "entrypoint_map"):
        op.add_column(
            "pyflow_published_api",
            sa.Column(
                "entrypoint_map",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )


def downgrade() -> None:
    if _has_column("pyflow_published_api", "entrypoint_map"):
        op.drop_column("pyflow_published_api", "entrypoint_map")
