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
