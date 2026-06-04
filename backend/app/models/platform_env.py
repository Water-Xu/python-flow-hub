"""平台级全局环境变量（注入所有 K8s 部署的调用块）。

仅存非敏感配置（白名单 host/端口/开关等）；敏感凭据走 K8s Secret（决策 14），
禁止在 DB 明文存密码。优先级：全局 < 部署 < 块（更具体者覆盖）。
"""

from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base_mixin import TimestampMixin, UUIDMixin


class PlatformEnv(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "pyflow_platform_env"

    # 环境变量名（注入块容器，如 BUSINESS_API_BASE）；全局唯一
    env_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    env_value: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(String(256), default="")
    updated_by: Mapped[str] = mapped_column(String(64), default="")
