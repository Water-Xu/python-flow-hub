"""FlowRun 新增 api_id / trigger_source / duration_ms，用于 Dashboard 展示调用来源。

Revision ID: 0021_flow_run_api_tracking
Revises: 0020_api_auth
Create Date: 2026-06-12
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021_flow_run_api_tracking"
down_revision = "0020_api_auth"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_column("pyflow_flow_run", "api_id"):
        op.add_column(
            "pyflow_flow_run",
            sa.Column("api_id", sa.String(36), nullable=True),
        )
    if not _has_column("pyflow_flow_run", "trigger_source"):
        op.add_column(
            "pyflow_flow_run",
            sa.Column("trigger_source", sa.String(16), nullable=True),
        )
    if not _has_column("pyflow_flow_run", "duration_ms"):
        op.add_column(
            "pyflow_flow_run",
            sa.Column("duration_ms", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    for col in ("duration_ms", "trigger_source", "api_id"):
        if _has_column("pyflow_flow_run", col):
            op.drop_column("pyflow_flow_run", col)
