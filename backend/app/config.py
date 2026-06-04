"""控制面配置（环境变量驱动）。"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PYFLOW_", env_file=".env", extra="ignore")

    deployment_mode: str = "local"          # local | k8s

    k8s_namespace: str = "pyflow-blocks"
    k8s_job_service_account: str = "pyflow-hub-sa"
    runner_image: str = (
        "us-central1-docker.pkg.dev/lhy-styon-dev-4832/lhy-styon/pyflow-runner:latest"
    )
    gpu_runner_image: str = (
        "us-central1-docker.pkg.dev/lhy-styon-dev-4832/lhy-styon/pyflow-runner-gpu:latest"
    )

    # ── K8s 节点池容量（决策 12：参数按实际容量推导，不硬编码 20/5）─────────────
    # pyflow-workers 节点池可分配总量（部署预检 allocatable vs 请求总量）
    workers_pool_cpu_cores: float = 4.0      # 节点池可分配总核数（保守值）
    workers_pool_mem_mib: int = 8192         # 节点池可分配总内存 MiB
    # KEDA 默认每副本消息数（按单条消息处理耗时标定）
    keda_msgs_per_replica: int = 10
    keda_max_replica_cap: int = 10           # maxReplica 上限兜底

    # ── KEDA / RabbitMQ management（决策 5：KEDA 走 management API 读队列深度）──
    rabbitmq_mgmt_host: str = "rabbitmq.lhy-styon.svc.cluster.local:15672"
    rabbitmq_vhost: str = "/lhy-styon"
    rabbitmq_user: str = "pyflow"
    rabbitmq_password: str = "pyflow"

    # ── Workload Identity KSA（决策 14：按块类型隔离）──────────────────────────
    ksa_default: str = "pyflow-block-default"
    ksa_bigquery: str = "pyflow-block-bq"
    ksa_storage: str = "pyflow-block-gcs"
    # GSA 已授权的资源 scope（部署预检；逗号分隔，如 "bq://ds.t,gcs://bucket/p"）
    gcp_authorized_scopes: str = ""

    # ── GPU（决策 12/GPU 章：配额是硬前置）────────────────────────────────────
    gpu_allowed_types: str = "nvidia-tesla-t4,nvidia-l4,nvidia-a100"
    gpu_quota_enabled: bool = False          # 配额未审批前禁止 GPU 部署
    # CUDA ↔ GPU 驱动兼容矩阵（gpu_type → 支持的最高 cuda）
    gpu_cuda_matrix: str = (
        "nvidia-tesla-t4:12.4,nvidia-l4:12.4,nvidia-a100:12.4"
    )

    # ── Cloud Build 镜像构建（Phase 4b 供应链加固）────────────────────────────
    cloudbuild_enabled: bool = False
    cloudbuild_builder_sa: str = "pyflow-builder@lhy-styon-dev-4832.iam.gserviceaccount.com"
    pip_index_url: str = ""                   # 私有 PyPI 镜像；空则用默认（dev）
    pip_require_hashes: bool = False
    artifact_registry: str = (
        "us-central1-docker.pkg.dev/lhy-styon-dev-4832/lhy-styon"
    )

    db_dsn: str = "postgresql+asyncpg://pyflow:pyflow@localhost:5432/pyflow"

    redis_url: str = "redis://localhost:6379/0"
    redis_cluster: bool = False

    rabbitmq_url: str = "amqp://pyflow:pyflow@localhost:5672//lhy-styon"

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_secure: bool = False
    minio_bucket: str = "pyflow-versions"

    # 鉴权（1b 起；1a 用 dev 默认用户兜底）
    auth_enabled: bool = False
    satoken_verify_url: str = ""
    dev_default_login_id: str = "dev-admin"
    bootstrap_admin: str = "dev-admin"

    # 可观测性
    otlp_endpoint: str = ""
    gcp_project: str = "lhy-styon-dev-4832"

    # Docker 沙箱
    docker_base_image: str = "python:3.11-slim"
    sandbox_gvisor: bool = False
    execution_timeout: int = 300


@lru_cache
def get_settings() -> Settings:
    return Settings()
