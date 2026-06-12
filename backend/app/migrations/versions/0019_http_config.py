"""新增 pyflow_published_api.http_config：HTTP 触发的输入映射配置。

Revision ID: 0019_http_config
Revises: 0018_api_docs_fields
Create Date: 2026-06-12
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019_http_config"
down_revision = "0018_api_docs_fields"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_column("pyflow_published_api", "http_config"):
        op.add_column(
            "pyflow_published_api",
            sa.Column("http_config", sa.JSON(), nullable=False, server_default="{}"),
        )


def downgrade() -> None:
    if _has_column("pyflow_published_api", "http_config"):
        op.drop_column("pyflow_published_api", "http_config")
