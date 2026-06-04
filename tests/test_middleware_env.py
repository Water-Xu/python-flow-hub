"""块中间件接入 + 环境变量合并 单测（纯逻辑，不依赖 K8s/DB）。"""

from __future__ import annotations

import base64

from app.config import Settings
from app.core.k8s import middleware
from app.core.k8s.manifest_generator import BlockDeploySpec
from app.core.k8s.orchestrator import merge_env_into_specs


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[arg-type]


def test_parse_egress_cidrs():
    out = middleware.parse_egress_cidrs("10.0.1.0/24:6379, 10.196.0.3/32:5432 ,bad")
    assert out == [("10.0.1.0/24", 6379), ("10.196.0.3/32", 5432)]


def test_parse_ns_ports():
    assert middleware.parse_ns_ports("5672, 15672 ,x,9000") == [5672, 15672, 9000]


def test_middleware_connection_map_falls_back_to_control_plane():
    s = _settings(redis_url="redis://r:6379/0", rabbitmq_url="amqp://u:p@mq:5672//v",
                  db_dsn="postgresql://u:p@db:5432/x", minio_endpoint="m:9000",
                  minio_access_key="ak", minio_secret_key="sk")
    m = middleware.middleware_connection_map(s)
    assert m["REDIS_URL"] == "redis://r:6379/0"
    assert m["RABBITMQ_URL"] == "amqp://u:p@mq:5672//v"
    assert m["DATABASE_URL"] == "postgresql://u:p@db:5432/x"
    assert m["MINIO_ENDPOINT"] == "m:9000"
    # 单独覆盖块连接
    s2 = _settings(db_dsn="postgresql://u:p@db:5432/x",
                   block_db_dsn="postgresql://app:p@10.196.0.3:5432/ai_outfit")
    assert middleware.middleware_connection_map(s2)["DATABASE_URL"].endswith("/ai_outfit")


def test_build_middleware_secret_base64():
    s = _settings(redis_url="redis://r:6379/0", block_middleware_secret="pyflow-block-middleware")
    secret = middleware.build_middleware_secret(s, "pyflow-blocks")
    assert secret["kind"] == "Secret"
    assert secret["metadata"]["name"] == "pyflow-block-middleware"
    decoded = base64.b64decode(secret["data"]["REDIS_URL"]).decode()
    assert decoded == "redis://r:6379/0"


def test_middleware_summary_masks_password():
    s = _settings(rabbitmq_url="amqp://lhy:secret@mq:5672//v")
    summary = middleware.middleware_summary(s)
    rmq = next(c for c in summary["connections"] if c["env"] == "RABBITMQ_URL")
    assert "secret" not in rmq["value"]
    assert "***" in rmq["value"]
    # MinIO secret key 永不返回明文
    sk = next(c for c in summary["connections"] if c["env"] == "MINIO_SECRET_KEY")
    assert sk["value"] == "***"


def test_merge_env_priority_global_lt_deployment_lt_block():
    specs = [
        BlockDeploySpec("b1", "n1", env_vars={"A": "block", "C": "block-c"}),
        BlockDeploySpec("b2", "n2", env_vars={}),
    ]
    merge_env_into_specs(
        specs,
        global_env={"A": "global", "B": "global-b", "D": "global-d"},
        deployment_env={"A": "deploy", "B": "deploy-b"},
        deployment_secret_refs={"S1": "k1"},
    )
    # b1：块级 A 覆盖部署/全局；B 部署覆盖全局；D 仅全局
    assert specs[0].env_vars["A"] == "block"
    assert specs[0].env_vars["B"] == "deploy-b"
    assert specs[0].env_vars["C"] == "block-c"
    assert specs[0].env_vars["D"] == "global-d"
    # b2：无块级，部署 + 全局合并
    assert specs[1].env_vars["A"] == "deploy"
    assert specs[1].env_vars["D"] == "global-d"
    # secret_refs：部署级合并
    assert specs[0].secret_refs["S1"] == "k1"


def test_build_egress_for_settings():
    s = _settings(middleware_namespace="lhy-styon",
                  middleware_ns_ports="5672,15672", block_egress_cidrs="10.0.1.0/24:6379")
    rules = middleware.build_egress_for_settings(s)
    ports = [p["port"] for r in rules for p in r["ports"]]
    assert 5672 in ports and 6379 in ports
