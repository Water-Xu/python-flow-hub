"""KEDA ScaledObject + RabbitMQ TriggerAuthentication 管理（决策 5/12）。

KEDA 走 management API（http 协议）读队列就绪深度；凭据经 K8s Secret + TriggerAuthentication
注入，控制面不明文持有（从现有 RabbitMQ 凭据派生，写入后即从内存清除）。
"""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import quote, urlsplit

from app.config import get_settings

settings = get_settings()


def _rabbitmq_credentials() -> tuple[str, str]:
    """KEDA 凭据以 rabbitmq_url 为单一来源（与应用实际连接一致），回退到独立配置项。

    避免出现「应用用 rabbitmq_url 连接、KEDA 用独立 user/password 派生」两份凭据漂移
    （历史上独立项默认 pyflow/pyflow 与真实用户不符，导致 management API 401）。
    """
    parsed = urlsplit(settings.rabbitmq_url)
    # urlsplit 不解码 userinfo：URL 中的 username/password 已是 URL 编码片段，直接复用；
    # 仅当 URL 未带凭据时，回退到独立配置项（明文）并补做 URL 编码。
    user = parsed.username if parsed.username is not None else quote(settings.rabbitmq_user, safe="")
    password = (
        parsed.password if parsed.password is not None
        else quote(settings.rabbitmq_password, safe="")
    )
    return user, password


def build_rabbitmq_auth_manifests(namespace: str) -> list[dict[str, Any]]:
    """生成 KEDA RabbitMQ 鉴权 Secret + TriggerAuthentication。

    host 为完整连接串含 vhost（URL 编码），KEDA 通过 management API 读队列深度。
    """
    vhost_encoded = quote(settings.rabbitmq_vhost, safe="")
    user, password = _rabbitmq_credentials()
    host = (
        f"http://{user}:{password}@"
        f"{settings.rabbitmq_mgmt_host}/{vhost_encoded}"
    )
    secret = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": "pyflow-rabbitmq-auth", "namespace": namespace},
        "type": "Opaque",
        "data": {"host": base64.b64encode(host.encode("utf-8")).decode("ascii")},
    }
    trigger_auth = {
        "apiVersion": "keda.sh/v1alpha1",
        "kind": "TriggerAuthentication",
        "metadata": {"name": "pyflow-rabbitmq-trigger-auth", "namespace": namespace},
        "spec": {
            "secretTargetRef": [
                {"parameter": "host", "name": "pyflow-rabbitmq-auth", "key": "host"}
            ]
        },
    }
    return [secret, trigger_auth]
