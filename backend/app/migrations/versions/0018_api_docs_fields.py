"""新增 pyflow_published_api 开发者文档字段：remarks/sample_request/sample_response/changelog。

Revision ID: 0018_api_docs_fields
Revises: 0017_block_source_flow_id
Create Date: 2026-06-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018_api_docs_fields"
down_revision = "0017_block_source_flow_id"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    for col_name in ("remarks", "sample_request", "sample_response", "changelog"):
        if not _has_column("pyflow_published_api", col_name):
            op.add_column(
                "pyflow_published_api",
                sa.Column(col_name, sa.Text(), nullable=False, server_default=""),
            )


def downgrade() -> None:
    for col_name in ("remarks", "sample_request", "sample_response", "changelog"):
        if _has_column("pyflow_published_api", col_name):
            op.drop_column("pyflow_published_api", col_name)
