"""RBAC：平台级角色（决策 2）+ 资源级 ACL（决策 15）。"""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base_mixin import TimestampMixin, UUIDMixin


class PyFlowUserRole(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "pyflow_user_role"

    login_id: Mapped[str] = mapped_column(String(64), index=True)
    # viewer | editor | deployer | admin
    role: Mapped[str] = mapped_column(String(16))
    granted_by: Mapped[str] = mapped_column(String(64))


class PyFlowResourceGrant(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "pyflow_resource_grant"

    # block | flow
    resource_type: Mapped[str] = mapped_column(String(16), index=True)
    resource_id: Mapped[str] = mapped_column(String(36), index=True)
    login_id: Mapped[str] = mapped_column(String(64), index=True)
    # view | edit | deploy
    access: Mapped[str] = mapped_column(String(16))
    granted_by: Mapped[str] = mapped_column(String(64))
