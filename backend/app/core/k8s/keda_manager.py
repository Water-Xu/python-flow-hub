"""KEDA ScaledObject + RabbitMQ TriggerAuthentication 管理（决策 5/12）。

KEDA 走 management API（http 协议）读队列就绪深度；凭据经 K8s Secret + TriggerAuthentication
注入，控制面不明文持有（从现有 RabbitMQ 凭据派生，写入后即从内存清除）。
"""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import quote

from app.config import get_settings

settings = get_settings()


def build_rabbitmq_auth_manifests(namespace: str) -> list[dict[str, Any]]:
    """生成 KEDA RabbitMQ 鉴权 Secret + TriggerAuthentication。

    host 为完整连接串含 vhost（URL 编码），KEDA 通过 management API 读队列深度。
    """
    vhost_encoded = quote(settings.rabbitmq_vhost, safe="")
    host = (
        f"http://{settings.rabbitmq_user}:{settings.rabbitmq_password}@"
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
