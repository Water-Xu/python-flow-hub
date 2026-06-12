"""新增 pyflow_published_api 访问认证字段：auth_enabled / auth_secret。

Revision ID: 0020_api_auth
Revises: 0019_http_config
Create Date: 2026-06-12
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020_api_auth"
down_revision = "0019_http_config"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_column("pyflow_published_api", "auth_enabled"):
        op.add_column(
            "pyflow_published_api",
            sa.Column("auth_enabled", sa.Boolean(), nullable=False, server_default="false"),
        )
    if not _has_column("pyflow_published_api", "auth_secret"):
        op.add_column(
            "pyflow_published_api",
            sa.Column("auth_secret", sa.String(64), nullable=True),
        )


def downgrade() -> None:
    for col in ("auth_secret", "auth_enabled"):
        if _has_column("pyflow_published_api", col):
            op.drop_column("pyflow_published_api", col)
