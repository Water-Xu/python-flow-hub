"""控制面配置（环境变量驱动）。"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PYFLOW_", env_file=".env", extra="ignore")

    deployment_mode: str = "local"          # local | k8s

    # 对外网关前缀（nginx 反代 /lhy-styon-pyflow → 控制面）。门户展示可调 URL 时拼上此前缀。
    public_api_prefix: str = "/lhy-styon-pyflow"

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
    workers_pool_cpu_cores: float = 2.0      # 节点池单节点可分配核数（e2-standard-2；CPU 配额受限，提配额后调大）
    workers_pool_mem_mib: int = 6144         # 节点池单节点可分配内存 MiB（e2-standard-2 ~6Gi 可分配）
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
    cloudbuild_builder_sa: str = ""  # 空 = 用 Cloud Build 默认 SA
    pip_index_url: str = ""                   # 私有 PyPI 镜像；空则用默认（dev）
    pip_require_hashes: bool = False
    # 依赖白名单（与 pyflowhub_pack 方案对齐；空列表且 require_whitelist=true 时拒绝所有 PyPI 包）
    pip_require_whitelist: bool = True
    pip_allowed_packages: str = (
        "fastembed,pymilvus,onnxruntime,numpy,httpx,pillow,torch,faiss-cpu,open-clip-torch,"
        "pyflow-vector-ingest,pyflow_vector_ingest,pyflow_vector,sentence-transformers"
    )
    # 允许源码安装（不用 --only-binary）的重型包
    pip_allow_sdist_packages: str = "fastembed"
    # 块大文件 / wheel 所在 MinIO bucket（不含 pyflow-versions 版本代码）
    block_artifacts_bucket: str = "pyflow-artifacts"
    # Cloud Build 拉取 @gcs: wheel 的 staging bucket（默认可推导）
    cloudbuild_staging_bucket: str = ""
    artifact_registry: str = (
        "us-central1-docker.pkg.dev/lhy-styon-dev-4832/lhy-styon"
    )

    db_dsn: str = "postgresql+asyncpg://pyflow:pyflow@localhost:5432/pyflow"

    redis_url: str = "redis://localhost:6379/0"
    redis_cluster: bool = False

    rabbitmq_url: str = "amqp://pyflow:pyflow@localhost:5672//lhy-styon"

    # ── 块运行时中间件接入（让中台启动的 Flow / 调用块连到集群内 redis/mq/db/minio）──
    # 开关：是否向 Block Deployment 注入中间件连接（共享 Secret + NetworkPolicy egress 放行）
    block_inject_middleware: bool = True
    # 注入给块的连接串（默认复用控制面同一套；可单独指定业务库/独立 redis 等）。
    # 空字符串表示沿用对应控制面连接（见 effective_block_* 派生）。
    block_redis_url: str = ""
    block_rabbitmq_url: str = ""
    block_db_dsn: str = ""
    block_minio_endpoint: str = ""
    block_minio_access_key: str = ""
    block_minio_secret_key: str = ""
    # 向量库 / 搜索 / 注册中心（空字符串表示不注入该中间件；值走 Secret，不入 git）
    block_milvus_uri: str = ""               # 如 http://milvus.lhy-styon:19530
    block_es_url: str = ""                    # 如 http://elasticsearch.lhy-styon:9200
    block_nacos_addr: str = ""                # 如 nacos-registry.lhy-styon:8848
    # 中间件（RabbitMQ/MinIO/ES/Nacos/Milvus）所在命名空间（pyflow 跨 ns 访问需放行）
    middleware_namespace: str = "lhy-styon"
    # 命名空间内放行的中间件端口（逗号分隔）：amqp/mgmt/minio/minio-console/es/nacos/milvus-grpc/redis
    middleware_ns_ports: str = "5672,15672,9000,9001,9200,8848,19530,6379"
    # VPC 私网中间件 egress 白名单（Cloud SQL 等，cidr:port 逗号分隔）
    # 例：10.196.0.3/32:5432
    block_egress_cidrs: str = "10.196.0.3/32:5432"
    # 块连接中间件的共享 Secret 名（运行时由 orchestrator 从 block_* 渲染到 pyflow-blocks）
    block_middleware_secret: str = "pyflow-block-middleware"

    def effective_block_redis_url(self) -> str:
        return self.block_redis_url or self.redis_url

    def effective_block_rabbitmq_url(self) -> str:
        return self.block_rabbitmq_url or self.rabbitmq_url

    def effective_block_db_dsn(self) -> str:
        return self.block_db_dsn or self.db_dsn

    def effective_block_minio_endpoint(self) -> str:
        return self.block_minio_endpoint or self.minio_endpoint

    def effective_block_minio_access_key(self) -> str:
        return self.block_minio_access_key or self.minio_access_key

    def effective_block_minio_secret_key(self) -> str:
        return self.block_minio_secret_key or self.minio_secret_key

    def effective_block_milvus_uri(self) -> str:
        return self.block_milvus_uri

    def effective_block_es_url(self) -> str:
        return self.block_es_url

    def effective_block_nacos_addr(self) -> str:
        return self.block_nacos_addr

    def effective_cloudbuild_staging_bucket(self) -> str:
        if self.cloudbuild_staging_bucket.strip():
            return self.cloudbuild_staging_bucket.strip()
        return f"{self.gcp_project}-pyflow-build"

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
