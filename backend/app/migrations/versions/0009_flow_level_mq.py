"""MQ 触发从 Block 级上移到接口/Flow 级（决策 3.1 重写为 Flow 级模型 A）

- pyflow_published_api 新增 trigger_type（http|mq|both）+ mq_config（JSON）。
- pyflow_block 删除 execution_mode / mq_config：块在 Flow 内一律作为 HTTP invoke 服务被驱动，
  MQ 接收/重试/回复全部归属接口层。

Revision ID: 0009_flow_level_mq
Revises: 0008_deployment_resource_overrides
Create Date: 2026-06-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_flow_level_mq"
down_revision = "0008_deployment_resource_overrides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pyflow_published_api",
        sa.Column("trigger_type", sa.String(16), nullable=False, server_default="http"),
    )
    op.add_column(
        "pyflow_published_api",
        sa.Column("mq_config", sa.JSON, nullable=False, server_default="{}"),
    )
    op.drop_column("pyflow_block", "mq_config")
    op.drop_column("pyflow_block", "execution_mode")


def downgrade() -> None:
    op.add_column(
        "pyflow_block",
        sa.Column("execution_mode", sa.String(16), nullable=False, server_default="sync_http"),
    )
    op.add_column(
        "pyflow_block",
        sa.Column("mq_config", sa.JSON, nullable=False, server_default="{}"),
    )
    op.drop_column("pyflow_published_api", "mq_config")
    op.drop_column("pyflow_published_api", "trigger_type")
