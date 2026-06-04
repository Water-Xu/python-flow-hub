"""新增 pyflow_block.entrypoints（一脚本多入口函数）

支持一个 Block 脚本暴露多个入口函数：列存 [{name, description, params}]，
由 AST 静态扫描自动回填；Flow 节点通过 config.entrypoint 选择调用哪个函数。
默认入口仍为 run，旧块该列为空列表，行为不变。

Revision ID: 0007_block_entrypoints
Revises: 0006_fix_timestamp_defaults
Create Date: 2026-06-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_block_entrypoints"
down_revision = "0006_fix_timestamp_defaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pyflow_block",
        sa.Column("entrypoints", sa.JSON, nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("pyflow_block", "entrypoints")
