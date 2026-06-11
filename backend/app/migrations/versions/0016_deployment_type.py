"""新增 pyflow_flow_deployment.deployment_type 字段，支持 flow_mode 整流单 Pod 部署模型。

Revision ID: 0016_deployment_type
Revises: 0015_api_entry_node_id
Create Date: 2026-06-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_deployment_type"
down_revision = "0015_api_entry_node_id"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_column("pyflow_flow_deployment", "deployment_type"):
        op.add_column(
            "pyflow_flow_deployment",
            sa.Column("deployment_type", sa.String(length=16), nullable=False, server_default="block_mode"),
        )


def downgrade() -> None:
    if _has_column("pyflow_flow_deployment", "deployment_type"):
        op.drop_column("pyflow_flow_deployment", "deployment_type")
