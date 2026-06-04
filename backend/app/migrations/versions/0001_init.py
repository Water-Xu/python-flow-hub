"""initial schema — 全量建表（依据 ORM metadata）

Revision ID: 0001_init
Revises:
Create Date: 2026-06-04
"""
from __future__ import annotations

from alembic import op

from app.db import Base
from app import models  # noqa: F401 注册全部模型

revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
