"""修复 0003/0004/0005 建表时 created_at/updated_at 缺失 server_default

问题：ORM `TimestampMixin` 使用 server_default=func.now()，SQLAlchemy 因此在 INSERT
时省略这两列、交由数据库默认值填充；但上述迁移 create_table 时把列写为 nullable=False
却未带 server_default，导致数据库列无默认值 → 插入 NULL → NotNullViolation（接口发布等
操作返回 500）。本迁移为已部署库的相关表补回 DEFAULT now()。

Revision ID: 0006_fix_timestamp_defaults
Revises: 0005_platform_env
Create Date: 2026-06-04
"""
from __future__ import annotations

from alembic import op

revision = "0006_fix_timestamp_defaults"
down_revision = "0005_platform_env"
branch_labels = None
depends_on = None

# 受影响的表：created_at/updated_at 由 create_table 创建却漏了 server_default
_TABLES = (
    "pyflow_published_api",
    "pyflow_block_version",
    "pyflow_flow_version",
    "pyflow_platform_env",
)


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN created_at SET DEFAULT now()")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN updated_at SET DEFAULT now()")
        # 兜底回填历史 NULL（正常情况下因插入失败不会有残留行）
        op.execute(f"UPDATE {table} SET created_at = now() WHERE created_at IS NULL")
        op.execute(f"UPDATE {table} SET updated_at = now() WHERE updated_at IS NULL")


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN created_at DROP DEFAULT")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN updated_at DROP DEFAULT")
