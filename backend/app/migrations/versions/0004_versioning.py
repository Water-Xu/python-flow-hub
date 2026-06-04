"""新增版本快照表 pyflow_block_version / pyflow_flow_version（Phase 3，决策 8）

Revision ID: 0004_versioning
Revises: 0003_api_portal
Create Date: 2026-06-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_versioning"
down_revision = "0003_api_portal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pyflow_block_version",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("block_id", sa.String(36), nullable=False),
        sa.Column("version_tag", sa.String(64), nullable=False, server_default=""),
        sa.Column("commit_message", sa.Text, nullable=False, server_default=""),
        sa.Column("is_stable", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("code_path", sa.String(512), nullable=False, server_default=""),
        sa.Column("notebook_path", sa.String(512), nullable=True),
        sa.Column("requirements_path", sa.String(512), nullable=True),
        sa.Column("input_ports", sa.JSON, nullable=False),
        sa.Column("output_ports", sa.JSON, nullable=False),
        sa.Column("requirements_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("content_sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_pyflow_block_version_block_id", "pyflow_block_version", ["block_id"])

    op.create_table(
        "pyflow_flow_version",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("flow_id", sa.String(36), nullable=False),
        sa.Column("version_tag", sa.String(64), nullable=False, server_default=""),
        sa.Column("commit_message", sa.Text, nullable=False, server_default=""),
        sa.Column("is_stable", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("snapshot_path", sa.String(512), nullable=False, server_default=""),
        sa.Column("content_sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("node_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("edge_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_pyflow_flow_version_flow_id", "pyflow_flow_version", ["flow_id"])


def downgrade() -> None:
    op.drop_table("pyflow_flow_version")
    op.drop_table("pyflow_block_version")
