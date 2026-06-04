"""新增 pyflow_flow_deployment.resource_overrides（部署级 Pod 资源覆盖）

按 block_id 维度覆盖 compute_config（CPU/内存/GPU），仅作用于该部署，
让同一流程在不同部署下可使用不同的 Pod 资源规格。旧部署该列为空 dict，行为不变。

Revision ID: 0008_deployment_resource_overrides
Revises: 0007_block_entrypoints
Create Date: 2026-06-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_deployment_resource_overrides"
down_revision = "0007_block_entrypoints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pyflow_flow_deployment",
        sa.Column("resource_overrides", sa.JSON, nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("pyflow_flow_deployment", "resource_overrides")
