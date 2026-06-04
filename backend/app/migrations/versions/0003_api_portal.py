"""新增 pyflow_published_api 表（接口发布 + 策略 + 锁定）

Revision ID: 0003_api_portal
Revises: 0002_flow_import
Create Date: 2026-06-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_api_portal"
down_revision = "0002_flow_import"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pyflow_published_api",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("path", sa.String(128), nullable=False, unique=True),
        sa.Column("tags", sa.String(256), nullable=False, server_default=""),
        sa.Column("flow_id", sa.String(36), nullable=False),
        sa.Column("active_flow_id", sa.String(36), nullable=True),
        sa.Column("owner_login_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        # 锁定
        sa.Column("is_locked", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("lock_reason", sa.Text, nullable=True),
        sa.Column("locked_by", sa.String(64), nullable=True),
        sa.Column("locked_at", sa.String(32), nullable=True),
        # 限流
        sa.Column("rate_limit_enabled", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("rate_limit_per_minute", sa.Integer, nullable=False, server_default="60"),
        # 负载均衡
        sa.Column("load_balance_strategy", sa.String(32), nullable=False, server_default="round_robin"),
        # 降级
        sa.Column("degradation_enabled", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("degradation_fallback", sa.JSON, nullable=True),
        # 流量统计
        sa.Column("total_calls", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("success_calls", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("error_calls", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("avg_latency_ms", sa.Float, nullable=False, server_default="0"),
        # 时间戳
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_pyflow_published_api_path", "pyflow_published_api", ["path"])
    op.create_index("ix_pyflow_published_api_flow_id", "pyflow_published_api", ["flow_id"])
    op.create_index("ix_pyflow_published_api_owner", "pyflow_published_api", ["owner_login_id"])


def downgrade() -> None:
    op.drop_table("pyflow_published_api")
