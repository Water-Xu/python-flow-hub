"""块运行时中间件接入（让中台启动的 Flow / 调用块连到集群内 redis/mq/db/minio）。

- 共享 Secret：把 REDIS_URL / RABBITMQ_URL / DATABASE_URL / MINIO_* 注入 pyflow-blocks，
  各 Block Deployment 经 envFrom 引用（敏感连接串不落 ConfigMap/git，决策 14）；
- egress 白名单：解析 settings 生成 NetworkPolicy egress 规则（命名空间内中间件 + VPC 私网）。
"""

from __future__ import annotations

import base64
from typing import Any

from app.config import Settings
from app.core.k8s.manifest_generator import middleware_egress_rules


# 注入块容器的通用环境变量名（用户代码按约定读取 os.environ）
BLOCK_REDIS_ENV = "REDIS_URL"
BLOCK_RABBITMQ_ENV = "RABBITMQ_URL"
BLOCK_DB_ENV = "DATABASE_URL"
BLOCK_MINIO_ENDPOINT_ENV = "MINIO_ENDPOINT"
BLOCK_MINIO_AK_ENV = "MINIO_ACCESS_KEY"
BLOCK_MINIO_SK_ENV = "MINIO_SECRET_KEY"


def middleware_connection_map(settings: Settings) -> dict[str, str]:
    """块可用的中间件连接（含敏感连接串）。"""
    return {
        BLOCK_REDIS_ENV: settings.effective_block_redis_url(),
        BLOCK_RABBITMQ_ENV: settings.effective_block_rabbitmq_url(),
        BLOCK_DB_ENV: settings.effective_block_db_dsn(),
        BLOCK_MINIO_ENDPOINT_ENV: settings.effective_block_minio_endpoint(),
        BLOCK_MINIO_AK_ENV: settings.effective_block_minio_access_key(),
        BLOCK_MINIO_SK_ENV: settings.effective_block_minio_secret_key(),
    }


def build_middleware_secret(settings: Settings, namespace: str) -> dict[str, Any]:
    """渲染共享中间件连接 Secret（pyflow-block-middleware）。"""
    data = {
        k: base64.b64encode(str(v).encode("utf-8")).decode("ascii")
        for k, v in middleware_connection_map(settings).items()
        if v
    }
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": settings.block_middleware_secret, "namespace": namespace},
        "type": "Opaque",
        "data": data,
    }


def parse_egress_cidrs(raw: str) -> list[tuple[str, int]]:
    """'10.0.1.0/24:6379,10.196.0.3/32:5432' -> [('10.0.1.0/24', 6379), ...]。"""
    out: list[tuple[str, int]] = []
    for item in (raw or "").split(","):
        item = item.strip()
        if not item or ":" not in item:
            continue
        cidr, _, port = item.rpartition(":")
        cidr = cidr.strip()
        try:
            out.append((cidr, int(port.strip())))
        except ValueError:
            continue
    return out


def parse_ns_ports(raw: str) -> list[int]:
    ports: list[int] = []
    for p in (raw or "").split(","):
        p = p.strip()
        if not p:
            continue
        try:
            ports.append(int(p))
        except ValueError:
            continue
    return ports


def build_egress_for_settings(settings: Settings) -> list[dict[str, Any]]:
    """从 settings 派生中间件 egress 规则。"""
    return middleware_egress_rules(
        middleware_namespace=settings.middleware_namespace,
        ns_ports=parse_ns_ports(settings.middleware_ns_ports),
        cidr_ports=parse_egress_cidrs(settings.block_egress_cidrs),
    )


def middleware_summary(settings: Settings) -> dict[str, Any]:
    """前端「平台设置-中间件连接」展示用（脱敏：不返回密码明文）。"""
    def mask(uri: str) -> str:
        if "@" in uri and "://" in uri:
            scheme, _, rest = uri.partition("://")
            cred, _, host = rest.partition("@")
            if ":" in cred:
                user = cred.split(":", 1)[0]
                return f"{scheme}://{user}:***@{host}"
        return uri

    return {
        "inject_enabled": settings.block_inject_middleware,
        "secret_name": settings.block_middleware_secret,
        "middleware_namespace": settings.middleware_namespace,
        "ns_ports": parse_ns_ports(settings.middleware_ns_ports),
        "egress_cidrs": [f"{c}:{p}" for c, p in parse_egress_cidrs(settings.block_egress_cidrs)],
        "connections": [
            {"env": BLOCK_REDIS_ENV, "value": mask(settings.effective_block_redis_url())},
            {"env": BLOCK_RABBITMQ_ENV, "value": mask(settings.effective_block_rabbitmq_url())},
            {"env": BLOCK_DB_ENV, "value": mask(settings.effective_block_db_dsn())},
            {"env": BLOCK_MINIO_ENDPOINT_ENV, "value": settings.effective_block_minio_endpoint()},
            {"env": BLOCK_MINIO_AK_ENV, "value": settings.effective_block_minio_access_key()},
            {"env": BLOCK_MINIO_SK_ENV, "value": "***"},
        ],
    }
