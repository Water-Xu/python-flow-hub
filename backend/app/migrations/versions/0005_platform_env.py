"""新增全局环境变量表 + 部署级 env/secret_refs（让块连中间件 + 环境变量配置）

Revision ID: 0005_platform_env
Revises: 0004_versioning
Create Date: 2026-06-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_platform_env"
down_revision = "0004_versioning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pyflow_platform_env",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("env_key", sa.String(128), nullable=False),
        sa.Column("env_value", sa.Text, nullable=False, server_default=""),
        sa.Column("description", sa.String(256), nullable=False, server_default=""),
        sa.Column("updated_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_pyflow_platform_env_env_key", "pyflow_platform_env", ["env_key"], unique=True
    )

    op.add_column(
        "pyflow_flow_deployment",
        sa.Column("env_vars", sa.JSON, nullable=False, server_default="{}"),
    )
    op.add_column(
        "pyflow_flow_deployment",
        sa.Column("secret_refs", sa.JSON, nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("pyflow_flow_deployment", "secret_refs")
    op.drop_column("pyflow_flow_deployment", "env_vars")
    op.drop_index("ix_pyflow_platform_env_env_key", table_name="pyflow_platform_env")
    op.drop_table("pyflow_platform_env")
