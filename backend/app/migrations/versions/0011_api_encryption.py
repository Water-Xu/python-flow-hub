"""新增 pyflow_published_api 加密保护字段（AES-256-GCM）。

Revision ID: 0011_api_encryption
Revises: 0010_api_entrypoint
Create Date: 2026-06-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_api_encryption"
down_revision = "0010_api_entrypoint"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    """探测列是否已存在，使迁移可重入。"""
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_column("pyflow_published_api", "encryption_enabled"):
        op.add_column(
            "pyflow_published_api",
            sa.Column("encryption_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if not _has_column("pyflow_published_api", "encryption_key"):
        op.add_column(
            "pyflow_published_api",
            sa.Column("encryption_key", sa.String(64), nullable=True),
        )
    if not _has_column("pyflow_published_api", "require_encrypted_request"):
        op.add_column(
            "pyflow_published_api",
            sa.Column(
                "require_encrypted_request", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
        )


def downgrade() -> None:
    for column in ("require_encrypted_request", "encryption_key", "encryption_enabled"):
        if _has_column("pyflow_published_api", column):
            op.drop_column("pyflow_published_api", column)
