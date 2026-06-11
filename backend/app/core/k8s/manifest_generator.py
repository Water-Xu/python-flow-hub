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
    """单个 Block 的部署描述（由 Block 模型 + 稳定版本派生）。

    MQ 触发已上移到接口/Flow 级（FlowConsumerSpec）：块在 Flow 内一律作为 HTTP invoke 服务，
    被 Flow-Consumer / 同步编排按 DAG 调用 /invoke（决策 3.1 重写为 Flow 级模型 A）。
    """

    block_id: str
    name: str
    type: str = "script"                       # script|notebook|gcp_bigquery|gcp_storage
    compute_config: dict[str, Any] = field(default_factory=dict)
    env_vars: dict[str, str] = field(default_factory=dict)
    secret_refs: dict[str, str] = field(default_factory=dict)
    gcp_resource_scope: list[str] = field(default_factory=list)
    requirements_hash: str = ""
    requirements_path: str = ""
    version_id: str = ""
    code_path: str = ""                        # MinIO key（runner 启动注入）
    image: str = ""                            # 依赖层镜像（决策 11；空则用 ctx 默认 runner 镜像）

    @property
    def block_short(self) -> str:
        return self.block_id.replace("-", "")[:8]

    @property
    def serves_http(self) -> bool:
        # 块一律暴露 /invoke（被 Flow 编排调用）
        return True

    @property
    def gpu_enabled(self) -> bool:
        return bool(self.compute_config.get("gpu_enabled"))


@dataclass
class FlowConsumerSpec:
    """接口/Flow 级 MQ 消费者部署描述（决策 3.1 重写为 Flow 级模型 A）。

    消费 flow.{api_id}.queue，收到消息后按 DAG 驱动整条 Flow（调各块 /invoke Service）。
    KEDA 按该队列深度扩缩本 Deployment。
    """

    api_id: str
    api_name: str
    flow_id: str
    mq_config: dict[str, Any] = field(default_factory=dict)
    # DAG 快照：{"nodes": [{id, node_type, block_id, config, service}], "edges": [...]}
    dag: dict[str, Any] = field(default_factory=dict)
    compute_config: dict[str, Any] = field(default_factory=dict)
    env_vars: dict[str, str] = field(default_factory=dict)
    secret_refs: dict[str, str] = field(default_factory=dict)
    image: str = ""

    @property
    def api_short(self) -> str:
        return self.api_id.replace("-", "")[:8]


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
    # MinIO 对象存储：endpoint/ak/sk 由中间件 Secret 注入，bucket/secure 随 Deployment 注入（runner 启动拉代码）
    minio_bucket: str = "pyflow-versions"
    minio_secure: bool = False

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
    """生成 Block 常驻 Deployment（决策 3.1 重写为 Flow 级模型 A）。

    invoke 角色：暴露 /invoke，被 Flow-Consumer / 同步编排按 DAG 调用。
    """
    name = deployment_name(ctx, spec)
    labels = _labels(spec, ctx)
    image = spec.image or (ctx.gpu_runner_image if spec.gpu_enabled else ctx.runner_image)
    role = "invoke"

    env = [
        {"name": "PYFLOW_RUNNER_ROLE", "value": role},
        {"name": "PYFLOW_BLOCK_ID", "value": spec.block_id},
        {"name": "PYFLOW_CODE_PATH", "value": spec.code_path},
        {"name": "PYFLOW_PROTOCOL_VERSION", "value": RUNTIME_PROTOCOL_VERSION},
        {"name": "PYTHONDONTWRITEBYTECODE", "value": "1"},
        # runner 启动据此从 MinIO 拉取真实 Block 代码（endpoint/ak/sk 由中间件 Secret envFrom 注入）
        {"name": "PYFLOW_MINIO_BUCKET", "value": ctx.minio_bucket},
        {"name": "PYFLOW_MINIO_SECURE", "value": "true" if ctx.minio_secure else "false"},
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
    - VPC 私网中间件（Cloud SQL）：按 ipBlock CIDR + 端口放行。
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


def render_block_manifests(
    spec: BlockDeploySpec,
    ctx: DeployContext,
    *,
    keda_enabled: bool = True,
) -> list[dict[str, Any]]:
    """渲染单个 Block 的全部 K8s manifest（invoke 服务，常驻 min≥1，决策 4）。"""
    manifests: list[dict[str, Any]] = [build_deployment(spec, ctx, min_replicas=1)]
    svc = build_service(spec, ctx)
    if svc:
        manifests.append(svc)
    manifests.append(build_network_policy(spec, ctx))
    return manifests


# ─────────────────────────── Flow-Consumer（接口/Flow 级 MQ） ───────────────────────────

def flow_consumer_name(ctx: DeployContext, spec: FlowConsumerSpec) -> str:
    prefix = ctx.resource_prefix or "flow"
    return f"{prefix}-fc-{spec.api_short}"[:63]


def _flow_consumer_labels(spec: FlowConsumerSpec, ctx: DeployContext) -> dict[str, str]:
    return {
        "app": f"pyflow-fc-{spec.api_short}",
        "pyflow.api/id": spec.api_id,
        "pyflow.flow/id": spec.flow_id,
        "pyflow.deploy/prefix": ctx.resource_prefix or "adhoc",
        "pyflow.runtime/protocol": RUNTIME_PROTOCOL_VERSION,
    }


def build_flow_consumer_deployment(
    spec: FlowConsumerSpec, ctx: DeployContext, *, min_replicas: int
) -> dict[str, Any]:
    """Flow-Consumer 常驻 Deployment：消费 flow.{api_id}.queue 驱动整条 DAG（决策 3.1）。"""
    import json

    name = flow_consumer_name(ctx, spec)
    labels = _flow_consumer_labels(spec, ctx)
    image = spec.image or ctx.runner_image

    env = [
        {"name": "PYFLOW_RUNNER_ROLE", "value": "flow_consumer"},
        {"name": "PYFLOW_API_ID", "value": spec.api_id},
        {"name": "PYFLOW_FLOW_ID", "value": spec.flow_id},
        {"name": "PYFLOW_NAMESPACE", "value": ctx.namespace},
        {"name": "PYFLOW_MQ_CONFIG", "value": json.dumps(spec.mq_config or {}, ensure_ascii=False)},
        {"name": "PYFLOW_FLOW_DAG", "value": json.dumps(spec.dag or {}, ensure_ascii=False)},
        {"name": "PYFLOW_PROTOCOL_VERSION", "value": RUNTIME_PROTOCOL_VERSION},
        {"name": "PYTHONDONTWRITEBYTECODE", "value": "1"},
    ]
    for k, v in (spec.env_vars or {}).items():
        env.append({"name": k, "value": str(v)})

    env_from = []
    if ctx.inject_middleware and ctx.middleware_secret:
        env_from.append({"secretRef": {"name": ctx.middleware_secret}})

    compute = spec.compute_config or {}
    pod_spec: dict[str, Any] = {
        "serviceAccountName": ctx.ksa_default,
        "securityContext": pod_security_context(),
        "containers": [
            {
                "name": "flow-consumer",
                "image": image,
                "env": env,
                "envFrom": env_from,
                "resources": container_resources(compute),
                "securityContext": container_security_context(),
                "volumeMounts": [{"name": "tmp", "mountPath": "/tmp"}],
            }
        ],
        "volumes": [{"name": "tmp", "emptyDir": {"sizeLimit": "100Mi"}}],
        "nodeSelector": {"cloud.google.com/gke-nodepool": WORKERS_NODE_POOL},
        "runtimeClassName": "gvisor",
    }
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": name, "namespace": ctx.namespace, "labels": labels},
        "spec": {
            "replicas": max(min_replicas, 0),
            "selector": {"matchLabels": {"app": labels["app"]}},
            "template": {"metadata": {"labels": labels}, "spec": pod_spec},
        },
    }


def build_flow_consumer_network_policy(
    spec: FlowConsumerSpec, ctx: DeployContext
) -> dict[str, Any]:
    """Flow-Consumer egress：kube-dns + 中间件白名单（RabbitMQ/Redis）+ 同命名空间块 Service。"""
    labels = _flow_consumer_labels(spec, ctx)
    egress: list[dict[str, Any]] = [
        {  # kube-dns
            "to": [{"namespaceSelector": {}}],
            "ports": [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}],
        },
        {  # 同命名空间块 invoke Service（驱动 DAG）
            "to": [{"podSelector": {}}],
            "ports": [{"protocol": "TCP", "port": INVOKE_PORT}],
        },
    ]
    if ctx.inject_middleware and ctx.middleware_egress:
        egress.extend(ctx.middleware_egress)
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {
            "name": f"{flow_consumer_name(ctx, spec)}-egress",
            "namespace": ctx.namespace,
            "labels": labels,
        },
        "spec": {
            "podSelector": {"matchLabels": {"app": labels["app"]}},
            "policyTypes": ["Egress"],
            "egress": egress,
        },
    }


def build_flow_scaledobject(
    spec: FlowConsumerSpec, ctx: DeployContext, *, max_replica: int, msgs_per_replica: int
) -> dict[str, Any]:
    """KEDA ScaledObject：按 flow.{api_id}.queue 深度扩缩 Flow-Consumer Deployment（决策 3.1/6/12）。"""
    name = flow_consumer_name(ctx, spec)
    return {
        "apiVersion": "keda.sh/v1alpha1",
        "kind": "ScaledObject",
        "metadata": {
            "name": f"{name}-scaler",
            "namespace": ctx.namespace,
            "labels": _flow_consumer_labels(spec, ctx),
        },
        "spec": {
            "scaleTargetRef": {"name": name},
            "minReplicaCount": 0,
            "maxReplicaCount": max_replica,
            "triggers": [
                {
                    "type": "rabbitmq",
                    "metadata": {
                        "protocol": "http",
                        "queueName": f"flow.{spec.api_id}.queue",
                        "mode": "QueueLength",
                        "value": str(msgs_per_replica),
                    },
                    "authenticationRef": {"name": "pyflow-rabbitmq-trigger-auth"},
                }
            ],
        },
    }


def render_flow_consumer_manifests(
    spec: FlowConsumerSpec,
    ctx: DeployContext,
    *,
    max_replica: int,
    msgs_per_replica: int,
    keda_enabled: bool = True,
) -> list[dict[str, Any]]:
    """渲染 Flow-Consumer 的全部 K8s manifest。

    keda_enabled=False（集群未装 KEDA）时：跳过 ScaledObject，消费者退化为固定 1 副本
    （否则 0 副本无人消费队列），保证功能可用、仅失去自动扩缩。
    """
    min_r = 0 if keda_enabled else 1
    manifests: list[dict[str, Any]] = [
        build_flow_consumer_deployment(spec, ctx, min_replicas=min_r),
        build_flow_consumer_network_policy(spec, ctx),
    ]
    if keda_enabled:
        manifests.append(build_flow_scaledobject(
            spec, ctx, max_replica=max_replica, msgs_per_replica=msgs_per_replica
        ))
    return manifests


# ─────────────────────────── Flow-Runner（flow_mode 整流单 Pod 模型） ───────────────────────────

@dataclass
class FlowRunnerSpec:
    """整流单 Pod 部署描述（flow_mode 决策：每条 Flow 部署为一个 Pod，所有块代码内嵌执行）。

    优势：消除块间 HTTP 调用开销；简化资源规划（1 Pod per Flow）；KEDA 仅对 Flow 级扩缩。
    runner 角色为 flow_runner，启动时从 MinIO 拉取所有块代码，在 Pod 内 in-process 执行 DAG。
    """

    flow_id: str
    flow_name: str
    # 各块信息，runner 据此逐一从 MinIO 拉取代码
    blocks: list[dict[str, Any]]   # [{block_id, code_path}]
    # DAG 快照（无 service 字段，in-process 不需要块 Service）
    dag: dict[str, Any]            # {nodes, edges, entry_node_id}
    # 该 Flow 上所有 MQ/both 触发接口（含各自 entry_node_id 与 entrypoint_map）
    mq_apis: list[dict[str, Any]]  # [{api_id, mq_config, entry_node_id, entrypoint_map}]
    compute_config: dict[str, Any] = field(default_factory=dict)
    env_vars: dict[str, str] = field(default_factory=dict)
    secret_refs: dict[str, str] = field(default_factory=dict)
    image: str = ""

    @property
    def flow_short(self) -> str:
        return self.flow_id.replace("-", "")[:8]

    @property
    def has_mq(self) -> bool:
        return bool(self.mq_apis)


def flow_runner_name(ctx: DeployContext, spec: FlowRunnerSpec) -> str:
    prefix = ctx.resource_prefix or "flow"
    return f"{prefix}-fr-{spec.flow_short}"[:63]


def _flow_runner_labels(spec: FlowRunnerSpec, ctx: DeployContext) -> dict[str, str]:
    return {
        "app": f"pyflow-fr-{spec.flow_short}",
        "pyflow.flow/id": spec.flow_id,
        "pyflow.runner/type": "flow_runner",
        "pyflow.deploy/prefix": ctx.resource_prefix or "adhoc",
        "pyflow.runtime/protocol": RUNTIME_PROTOCOL_VERSION,
    }


def build_flow_runner_deployment(
    spec: FlowRunnerSpec, ctx: DeployContext, *, min_replicas: int
) -> dict[str, Any]:
    """Flow-Runner Deployment：整流单 Pod，所有块 in-process 执行，暴露 /run（HTTP）+
    内建 MQ 消费（flow_mode，决策新增）。"""
    import json

    name = flow_runner_name(ctx, spec)
    labels = _flow_runner_labels(spec, ctx)
    image = spec.image or ctx.runner_image

    env = [
        {"name": "PYFLOW_RUNNER_ROLE", "value": "flow_runner"},
        {"name": "PYFLOW_FLOW_ID", "value": spec.flow_id},
        {"name": "PYFLOW_FLOW_BLOCKS", "value": json.dumps(spec.blocks or [], ensure_ascii=False)},
        {"name": "PYFLOW_FLOW_DAG", "value": json.dumps(spec.dag or {}, ensure_ascii=False)},
        {"name": "PYFLOW_MQ_APIS", "value": json.dumps(spec.mq_apis or [], ensure_ascii=False)},
        {"name": "PYFLOW_NAMESPACE", "value": ctx.namespace},
        {"name": "PYFLOW_MINIO_BUCKET", "value": ctx.minio_bucket},
        {"name": "PYFLOW_MINIO_SECURE", "value": "true" if ctx.minio_secure else "false"},
        {"name": "PYFLOW_PROTOCOL_VERSION", "value": RUNTIME_PROTOCOL_VERSION},
        {"name": "PYTHONDONTWRITEBYTECODE", "value": "1"},
    ]
    for k, v in (spec.env_vars or {}).items():
        env.append({"name": k, "value": str(v)})

    env_from = []
    if ctx.inject_middleware and ctx.middleware_secret:
        env_from.append({"secretRef": {"name": ctx.middleware_secret}})
    if spec.secret_refs:
        env_from.append({"secretRef": {"name": f"pyflow-fr-{spec.flow_short}-secrets"}})

    pod_spec: dict[str, Any] = {
        "serviceAccountName": ctx.ksa_default,
        "securityContext": pod_security_context(),
        "containers": [
            {
                "name": "flow-runner",
                "image": image,
                "env": env,
                "envFrom": env_from,
                "resources": container_resources(spec.compute_config or {}),
                "securityContext": container_security_context(),
                # /tmp 用于用户代码临时文件（readOnlyRootFilesystem 要求挂载 emptyDir）
                "volumeMounts": [{"name": "tmp", "mountPath": "/tmp"}],
                # 暴露 HTTP /run 端点（被控制面 HTTP 路径直接调用）
                "ports": [{"containerPort": INVOKE_PORT, "name": "run"}],
            }
        ],
        "volumes": [{"name": "tmp", "emptyDir": {"sizeLimit": "200Mi"}}],
        "nodeSelector": {"cloud.google.com/gke-nodepool": WORKERS_NODE_POOL},
        "runtimeClassName": "gvisor",
    }

    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": name, "namespace": ctx.namespace, "labels": labels},
        "spec": {
            # flow_runner 至少 1 副本（同时服务 HTTP；MQ 由 KEDA 扩缩）
            "replicas": max(min_replicas, 1),
            "selector": {"matchLabels": {"app": labels["app"]}},
            "template": {"metadata": {"labels": labels}, "spec": pod_spec},
        },
    }


def build_flow_runner_service(spec: FlowRunnerSpec, ctx: DeployContext) -> dict[str, Any]:
    """暴露 /run 的 ClusterIP Service，供控制面 HTTP 调用路径直接调用整流。"""
    name = flow_runner_name(ctx, spec)
    labels = _flow_runner_labels(spec, ctx)
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": name, "namespace": ctx.namespace, "labels": labels},
        "spec": {
            "selector": {"app": labels["app"]},
            "ports": [{"port": INVOKE_PORT, "targetPort": INVOKE_PORT, "name": "run"}],
        },
    }


def build_flow_runner_network_policy(
    spec: FlowRunnerSpec, ctx: DeployContext
) -> dict[str, Any]:
    """FlowRunner egress：kube-dns + 中间件白名单（RabbitMQ/Redis/MinIO）。

    无需访问同命名空间块 Service（所有块 in-process 执行），比 block_mode 策略更严格。
    """
    labels = _flow_runner_labels(spec, ctx)
    egress: list[dict[str, Any]] = [
        {  # kube-dns
            "to": [{"namespaceSelector": {}}],
            "ports": [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}],
        },
    ]
    if ctx.inject_middleware and ctx.middleware_egress:
        egress.extend(ctx.middleware_egress)
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {
            "name": f"{flow_runner_name(ctx, spec)}-egress",
            "namespace": ctx.namespace,
            "labels": labels,
        },
        "spec": {
            "podSelector": {"matchLabels": {"app": labels["app"]}},
            "policyTypes": ["Egress"],
            "egress": egress,
        },
    }


def build_flow_runner_scaledobject(
    spec: FlowRunnerSpec,
    ctx: DeployContext,
    *,
    max_replica: int,
    msgs_per_replica: int,
) -> dict[str, Any] | None:
    """KEDA ScaledObject for flow_runner：多 MQ API 触发合并为多 triggers（取最大值扩缩）。

    仅在存在 MQ 触发接口时生成；纯 HTTP Flow 不创建 ScaledObject（固定 min_replicas=1）。
    """
    if not spec.mq_apis:
        return None
    name = flow_runner_name(ctx, spec)
    triggers = [
        {
            "type": "rabbitmq",
            "metadata": {
                "protocol": "http",
                "queueName": f"flow.{api['api_id']}.queue",
                "mode": "QueueLength",
                "value": str(msgs_per_replica),
            },
            "authenticationRef": {"name": "pyflow-rabbitmq-trigger-auth"},
        }
        for api in spec.mq_apis
    ]
    return {
        "apiVersion": "keda.sh/v1alpha1",
        "kind": "ScaledObject",
        "metadata": {
            "name": f"{name}-scaler",
            "namespace": ctx.namespace,
            "labels": _flow_runner_labels(spec, ctx),
        },
        "spec": {
            "scaleTargetRef": {"name": name},
            # 最少 1 副本（HTTP /run 需常驻），MQ 高负载时扩缩
            "minReplicaCount": 1,
            "maxReplicaCount": max_replica,
            "triggers": triggers,
        },
    }


def render_flow_runner_manifests(
    spec: FlowRunnerSpec,
    ctx: DeployContext,
    *,
    max_replica: int,
    msgs_per_replica: int,
    keda_enabled: bool = True,
) -> list[dict[str, Any]]:
    """渲染 flow_mode 整流 Pod 的全部 K8s manifest（Deployment + Service + NetworkPolicy + KEDA）。"""
    manifests: list[dict[str, Any]] = [
        build_flow_runner_deployment(spec, ctx, min_replicas=1),
        build_flow_runner_service(spec, ctx),
        build_flow_runner_network_policy(spec, ctx),
    ]
    if keda_enabled and spec.has_mq:
        so = build_flow_runner_scaledobject(
            spec, ctx, max_replica=max_replica, msgs_per_replica=msgs_per_replica
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

    块均为常驻 invoke 副本（min≥1）按 request 累加；Flow-Consumer 的瞬时峰值
    不在此校验（由 KEDA + Node Autoscaler 处理）。
    """
    total_cpu_m = 0
    total_mem_mib = 0
    for s in specs:
        cpu = parse_cpu_millicores(s.compute_config.get("cpu_request", "100m"), 100)
        mem = parse_mem_mib(s.compute_config.get("memory_request", "256Mi"), 256)
        total_cpu_m += cpu
        total_mem_mib += mem

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
