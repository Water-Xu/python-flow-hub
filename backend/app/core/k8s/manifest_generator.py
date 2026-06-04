"""K8s manifest 生成 + 容量/GPU/scope 预检（决策 1/3.1/4/11/12/14）。

纯函数模块（不触达 K8s API），便于单测覆盖：
- 生成 Deployment + Service + ScaledObject + NetworkPolicy；
- 按 block.type 注入隔离 KSA（决策 14）；
- 非 GPU 块附加 runtimeClassName: gvisor，GPU 块省略（gVisor 与 GPU 互斥，决策 1）；
- 部署前容量预检（节点池 allocatable vs 请求总量，决策 12）；
- GPU 配额 + CUDA↔驱动兼容预检（决策 12/GPU 章）；
- GCP 托管块资源 scope 预检（决策 14）；
- 协议版本 label（决策 3.1 点 5）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pyflow_runtime import RUNTIME_PROTOCOL_VERSION

WORKERS_NODE_POOL = "pyflow-workers"
GPU_NODE_POOL = "pyflow-gpu-workers"
INVOKE_PORT = 8000

# 块类型 → 默认隔离 KSA（决策 14；占位，运行时由 settings 覆盖）
_DEFAULT_KSA = {
    "gcp_bigquery": "pyflow-block-bq",
    "gcp_storage": "pyflow-block-gcs",
}


@dataclass
class BlockDeploySpec:
    """单个 Block 的部署描述（由 Block 模型 + 稳定版本派生）。"""

    block_id: str
    name: str
    type: str = "script"                       # script|notebook|gcp_bigquery|gcp_storage
    execution_mode: str = "sync_http"          # sync_http|async_mq|both
    compute_config: dict[str, Any] = field(default_factory=dict)
    mq_config: dict[str, Any] = field(default_factory=dict)
    env_vars: dict[str, str] = field(default_factory=dict)
    secret_refs: dict[str, str] = field(default_factory=dict)
    gcp_resource_scope: list[str] = field(default_factory=list)
    requirements_hash: str = ""
    version_id: str = ""
    code_path: str = ""                        # MinIO key（runner 启动注入）
    image: str = ""                            # 依赖层镜像（决策 11；空则用 ctx 默认 runner 镜像）

    @property
    def block_short(self) -> str:
        return self.block_id.replace("-", "")[:8]

    @property
    def consumes_mq(self) -> bool:
        return self.execution_mode in ("async_mq", "both")

    @property
    def serves_http(self) -> bool:
        return self.execution_mode in ("sync_http", "both")

    @property
    def gpu_enabled(self) -> bool:
        return bool(self.compute_config.get("gpu_enabled"))


@dataclass
class DeployContext:
    namespace: str = "pyflow-blocks"
    resource_prefix: str = ""
    runner_image: str = ""
    gpu_runner_image: str = ""
    ksa_default: str = "pyflow-block-default"
    ksa_bigquery: str = "pyflow-block-bq"
    ksa_storage: str = "pyflow-block-gcs"
    # 中间件接入（让块连到集群内 redis/mq/db/minio）
    inject_middleware: bool = False
    middleware_secret: str = ""              # 共享中间件连接 Secret 名（空=不注入 envFrom）
    middleware_egress: list[dict[str, Any]] = field(default_factory=list)

    def ksa_for(self, block_type: str) -> str:
        if block_type == "gcp_bigquery":
            return self.ksa_bigquery
        if block_type == "gcp_storage":
            return self.ksa_storage
        return self.ksa_default


# ─────────────────────────── 资源解析 ───────────────────────────

def parse_cpu_millicores(value: str | int | float | None, default: int = 0) -> int:
    """'100m'→100，'1'/'1.5'→1000/1500，None→default。"""
    if value is None or value == "":
        return default
    s = str(value).strip()
    if s.endswith("m"):
        return int(float(s[:-1]))
    return int(float(s) * 1000)


def parse_mem_mib(value: str | int | None, default: int = 0) -> int:
    """'256Mi'→256，'1Gi'→1024，'512M'→~488，None→default。"""
    if value is None or value == "":
        return default
    s = str(value).strip()
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([KMGTP]?i?)$", s)
    if not m:
        return default
    num = float(m.group(1))
    unit = m.group(2)
    factors = {
        "": 1 / (1024 * 1024), "Ki": 1 / 1024, "Mi": 1, "Gi": 1024, "Ti": 1024 * 1024,
        "K": 1000 / (1024 * 1024), "M": 1000 * 1000 / (1024 * 1024),
        "G": 1000 ** 3 / (1024 * 1024), "T": 1000 ** 4 / (1024 * 1024),
    }
    return int(num * factors.get(unit, 1))


def container_resources(compute_config: dict[str, Any]) -> dict[str, Any]:
    cpu_req = compute_config.get("cpu_request", "100m")
    mem_req = compute_config.get("memory_request", "256Mi")
    cpu_lim = compute_config.get("cpu_limit", "1000m")
    mem_lim = compute_config.get("memory_limit", "1Gi")
    res: dict[str, Any] = {
        "requests": {"cpu": cpu_req, "memory": mem_req},
        "limits": {"cpu": cpu_lim, "memory": mem_lim},
    }
    if compute_config.get("gpu_enabled"):
        gpu_count = int(compute_config.get("gpu_count", 1))
        res["limits"]["nvidia.com/gpu"] = gpu_count
    return res


# ─────────────────────────── SecurityContext ───────────────────────────

def pod_security_context() -> dict[str, Any]:
    return {
        "runAsNonRoot": True,
        "runAsUser": 65534,
        "seccompProfile": {"type": "RuntimeDefault"},
    }


def container_security_context() -> dict[str, Any]:
    return {
        "runAsNonRoot": True,
        "runAsUser": 65534,
        "readOnlyRootFilesystem": True,
        "allowPrivilegeEscalation": False,
        "seccompProfile": {"type": "RuntimeDefault"},
        "capabilities": {"drop": ["ALL"]},
    }


def runtime_class(gpu_enabled: bool) -> str | None:
    """非 GPU 块用 gvisor，GPU 块省略（gVisor 与 GPU 互斥，决策 1）。"""
    return None if gpu_enabled else "gvisor"


def _labels(spec: BlockDeploySpec, ctx: DeployContext) -> dict[str, str]:
    return {
        "app": f"pyflow-{spec.block_short}",
        "pyflow.block/id": spec.block_id,
        "pyflow.deploy/prefix": ctx.resource_prefix or "adhoc",
        "pyflow.runtime/protocol": RUNTIME_PROTOCOL_VERSION,
    }


def deployment_name(ctx: DeployContext, spec: BlockDeploySpec) -> str:
    prefix = ctx.resource_prefix or "flow"
    return f"{prefix}-{spec.block_short}"[:63]


# ─────────────────────────── Manifests ───────────────────────────

def build_deployment(spec: BlockDeploySpec, ctx: DeployContext, *, min_replicas: int) -> dict[str, Any]:
    """生成 Block 常驻 Deployment（决策 3.1 模型 A）。

    consumer 角色：自消费 block.{id}.queue（async_mq）；
    invoke 角色：暴露 /invoke（sync_http；both 同时消费 + 服务）。
    """
    name = deployment_name(ctx, spec)
    labels = _labels(spec, ctx)
    image = spec.image or (ctx.gpu_runner_image if spec.gpu_enabled else ctx.runner_image)
    role = "invoke" if spec.serves_http else "consumer"

    env = [
        {"name": "PYFLOW_RUNNER_ROLE", "value": role},
        {"name": "PYFLOW_BLOCK_ID", "value": spec.block_id},
        {"name": "PYFLOW_CODE_PATH", "value": spec.code_path},
        {"name": "PYFLOW_PROTOCOL_VERSION", "value": RUNTIME_PROTOCOL_VERSION},
        {"name": "PYTHONDONTWRITEBYTECODE", "value": "1"},
    ]
    # 非敏感 env_vars 直接注入（已含全局/部署级合并结果，见 orchestrator）
    for k, v in (spec.env_vars or {}).items():
        env.append({"name": k, "value": str(v)})
    # 敏感值走 K8s Secret（决策 14：DB 不落明文）
    env_from = []
    # 共享中间件连接 Secret（REDIS_URL/RABBITMQ_URL/DATABASE_URL/MINIO_*）：放在最前，
    # 块自身 secret 可覆盖同名键（envFrom 后者优先）。
    if ctx.inject_middleware and ctx.middleware_secret:
        env_from.append({"secretRef": {"name": ctx.middleware_secret}})
    if spec.secret_refs:
        env_from.append({"secretRef": {"name": f"pyflow-{spec.block_short}-secrets"}})

    pod_spec: dict[str, Any] = {
        "serviceAccountName": ctx.ksa_for(spec.type),
        "securityContext": pod_security_context(),
        "containers": [
            {
                "name": "runner",
                "image": image,
                "env": env,
                "envFrom": env_from,
                "resources": container_resources(spec.compute_config),
                "securityContext": container_security_context(),
                "volumeMounts": [{"name": "tmp", "mountPath": "/tmp"}],
                **({"ports": [{"containerPort": INVOKE_PORT}]} if spec.serves_http else {}),
            }
        ],
        "volumes": [{"name": "tmp", "emptyDir": {"sizeLimit": "100Mi"}}],
    }

    # 节点池 / GPU 调度
    if spec.gpu_enabled:
        gpu_type = spec.compute_config.get("gpu_type", "nvidia-tesla-t4")
        pod_spec["nodeSelector"] = {"cloud.google.com/gke-accelerator": gpu_type}
        pod_spec["tolerations"] = [
            {"key": "nvidia.com/gpu", "operator": "Exists", "effect": "NoSchedule"},
            {"key": "pyflow-gpu", "operator": "Exists", "effect": "NoSchedule"},
        ]
    else:
        pod_spec["nodeSelector"] = {"cloud.google.com/gke-nodepool": WORKERS_NODE_POOL}
        rc = runtime_class(False)
        if rc:
            pod_spec["runtimeClassName"] = rc

    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": name, "namespace": ctx.namespace, "labels": labels},
        "spec": {
            "replicas": max(min_replicas, 0),
            "selector": {"matchLabels": {"app": labels["app"]}},
            "template": {
                "metadata": {"labels": labels},
                "spec": pod_spec,
            },
        },
    }


def build_service(spec: BlockDeploySpec, ctx: DeployContext) -> dict[str, Any] | None:
    """同步块暴露 Service（决策 10 同步编排调 /invoke）。"""
    if not spec.serves_http:
        return None
    name = deployment_name(ctx, spec)
    labels = _labels(spec, ctx)
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": name, "namespace": ctx.namespace, "labels": labels},
        "spec": {
            "selector": {"app": labels["app"]},
            "ports": [{"port": INVOKE_PORT, "targetPort": INVOKE_PORT, "name": "invoke"}],
        },
    }


def middleware_egress_rules(
    *,
    middleware_namespace: str,
    ns_ports: list[int],
    cidr_ports: list[tuple[str, int]],
) -> list[dict[str, Any]]:
    """中间件 egress 白名单（决策 1/14）：让块连到集群内/VPC 中间件。

    - middleware_namespace（如 lhy-styon）内的 RabbitMQ/MinIO/ES/Nacos：按 namespaceSelector + 端口放行；
    - VPC 私网中间件（Memorystore Redis / Cloud SQL）：按 ipBlock CIDR + 端口放行。
    """
    rules: list[dict[str, Any]] = []
    if middleware_namespace and ns_ports:
        rules.append({
            "to": [{
                "namespaceSelector": {
                    "matchLabels": {"kubernetes.io/metadata.name": middleware_namespace}
                }
            }],
            "ports": [{"protocol": "TCP", "port": p} for p in ns_ports],
        })
    for cidr, port in cidr_ports:
        rules.append({
            "to": [{"ipBlock": {"cidr": cidr}}],
            "ports": [{"protocol": "TCP", "port": port}],
        })
    return rules


def build_network_policy(spec: BlockDeploySpec, ctx: DeployContext) -> dict[str, Any]:
    """egress deny-all + 白名单（决策 1/14）。

    普通块：放行 kube-dns(53) + 配置的中间件白名单（redis/mq/db/minio）；
    GCP 托管块额外放行 Private Google Access（443）。
    """
    labels = _labels(spec, ctx)
    egress: list[dict[str, Any]] = [
        {  # kube-dns
            "to": [{"namespaceSelector": {}}],
            "ports": [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}],
        }
    ]
    if spec.type in ("gcp_bigquery", "gcp_storage"):
        # Private Google Access：private.googleapis.com / restricted.googleapis.com
        egress.append({
            "to": [{"ipBlock": {"cidr": "199.36.153.8/30"}}, {"ipBlock": {"cidr": "199.36.153.4/30"}}],
            "ports": [{"protocol": "TCP", "port": 443}],
        })
    # 中间件接入：redis / rabbitmq / 数据库 / minio 白名单（按上下文配置放行给所有块）
    if ctx.inject_middleware and ctx.middleware_egress:
        egress.extend(ctx.middleware_egress)
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {
            "name": f"{deployment_name(ctx, spec)}-egress",
            "namespace": ctx.namespace,
            "labels": labels,
        },
        "spec": {
            "podSelector": {"matchLabels": {"app": labels["app"]}},
            "policyTypes": ["Egress"],
            "egress": egress,
        },
    }


def build_scaledobject(
    spec: BlockDeploySpec, ctx: DeployContext, *, max_replica: int, msgs_per_replica: int, min_replica: int
) -> dict[str, Any] | None:
    """KEDA ScaledObject（仅 async_mq/both 块；扩缩对应 Block Deployment，决策 3.1/12）。"""
    if not spec.consumes_mq:
        return None
    name = deployment_name(ctx, spec)
    return {
        "apiVersion": "keda.sh/v1alpha1",
        "kind": "ScaledObject",
        "metadata": {
            "name": f"{name}-scaler",
            "namespace": ctx.namespace,
            "labels": _labels(spec, ctx),
        },
        "spec": {
            "scaleTargetRef": {"name": name},
            "minReplicaCount": min_replica,
            "maxReplicaCount": max_replica,
            "triggers": [
                {
                    "type": "rabbitmq",
                    "metadata": {
                        "protocol": "http",
                        "queueName": f"block.{spec.block_id}.queue",
                        "mode": "QueueLength",
                        "value": str(msgs_per_replica),
                    },
                    "authenticationRef": {"name": "pyflow-rabbitmq-trigger-auth"},
                }
            ],
        },
    }


def min_replicas_for(spec: BlockDeploySpec) -> int:
    """both / sync_http 强制 ≥1（决策 4，永不 scale-to-zero）；async_mq 可为 0。"""
    if spec.execution_mode in ("sync_http", "both"):
        return 1
    return 0


def render_block_manifests(
    spec: BlockDeploySpec,
    ctx: DeployContext,
    *,
    max_replica: int,
    msgs_per_replica: int,
) -> list[dict[str, Any]]:
    """渲染单个 Block 的全部 K8s manifest。"""
    min_r = min_replicas_for(spec)
    manifests: list[dict[str, Any]] = [build_deployment(spec, ctx, min_replicas=max(min_r, 1) if spec.serves_http else min_r)]
    svc = build_service(spec, ctx)
    if svc:
        manifests.append(svc)
    manifests.append(build_network_policy(spec, ctx))
    so = build_scaledobject(
        spec, ctx, max_replica=max_replica, msgs_per_replica=msgs_per_replica, min_replica=min_r
    )
    if so:
        manifests.append(so)
    return manifests


# ─────────────────────────── 预检 ───────────────────────────

@dataclass
class PrecheckResult:
    ok: bool
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


def capacity_precheck(
    specs: list[BlockDeploySpec],
    *,
    pool_cpu_cores: float,
    pool_mem_mib: int,
) -> PrecheckResult:
    """节点池 allocatable vs 请求总量（决策 12）。

    常驻副本（sync/both，min≥1）按 request 累加；async 块按 min=0 不计入基线，
    但 max_replica 的瞬时峰值不在此校验（由 KEDA + Node Autoscaler 处理）。
    """
    total_cpu_m = 0
    total_mem_mib = 0
    for s in specs:
        replicas = 1 if s.execution_mode in ("sync_http", "both") else 0
        if replicas == 0:
            continue
        cpu = parse_cpu_millicores(s.compute_config.get("cpu_request", "100m"), 100)
        mem = parse_mem_mib(s.compute_config.get("memory_request", "256Mi"), 256)
        total_cpu_m += cpu * replicas
        total_mem_mib += mem * replicas

    pool_cpu_m = int(pool_cpu_cores * 1000)
    ok = total_cpu_m <= pool_cpu_m and total_mem_mib <= pool_mem_mib
    return PrecheckResult(
        ok=ok,
        reason="" if ok else "常驻副本请求总量超出 pyflow-workers 节点池可分配容量，请扩容节点池或合并 sync 块",
        detail={
            "requested_cpu_m": total_cpu_m,
            "pool_cpu_m": pool_cpu_m,
            "requested_mem_mib": total_mem_mib,
            "pool_mem_mib": pool_mem_mib,
        },
    )


def derive_max_replica(spec: BlockDeploySpec, *, pool_cpu_cores: float, cap: int) -> int:
    """maxReplica = 节点池可用核数 / 单 Block limit（取保守值，决策 12）。"""
    cpu_lim_m = parse_cpu_millicores(spec.compute_config.get("cpu_limit", "1000m"), 1000)
    if cpu_lim_m <= 0:
        return 1
    by_capacity = int((pool_cpu_cores * 1000) // cpu_lim_m)
    return max(1, min(by_capacity, cap))


def gpu_precheck(
    spec: BlockDeploySpec,
    *,
    allowed_types: list[str],
    cuda_matrix: dict[str, str],
    quota_enabled: bool,
) -> PrecheckResult:
    """GPU 配额 + CUDA↔驱动兼容预检（决策 12/GPU 章）。"""
    if not spec.gpu_enabled:
        return PrecheckResult(ok=True)
    if not quota_enabled:
        return PrecheckResult(
            ok=False, reason="GPU 配额未审批：新项目 GPU 配额默认为 0，请先提交配额申请单"
        )
    gpu_type = spec.compute_config.get("gpu_type")
    if gpu_type not in allowed_types:
        return PrecheckResult(ok=False, reason=f"不支持的 GPU 类型: {gpu_type}")
    cuda = str(spec.compute_config.get("cuda_version", ""))
    max_cuda = cuda_matrix.get(gpu_type, "")
    if cuda and max_cuda and _version_tuple(cuda) > _version_tuple(max_cuda):
        return PrecheckResult(
            ok=False,
            reason=f"CUDA {cuda} 与 {gpu_type} 节点池驱动不兼容（最高支持 {max_cuda}）",
        )
    return PrecheckResult(ok=True)


def gcp_scope_precheck(spec: BlockDeploySpec, *, authorized_scopes: list[str]) -> PrecheckResult:
    """GCP 托管块资源 scope 预检：声明的 dataset/bucket 须已授权对应 GSA（决策 14）。"""
    if spec.type not in ("gcp_bigquery", "gcp_storage"):
        return PrecheckResult(ok=True)
    if not spec.gcp_resource_scope:
        return PrecheckResult(ok=False, reason="GCP 托管块必须声明 gcp_resource_scope")
    authorized = set(authorized_scopes)
    missing = [s for s in spec.gcp_resource_scope if s not in authorized]
    if missing and authorized:
        return PrecheckResult(
            ok=False, reason=f"以下资源未授权对应 GSA，禁止部署: {missing}"
        )
    return PrecheckResult(ok=True)


def _version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)) or (0,)
