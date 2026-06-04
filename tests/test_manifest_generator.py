"""manifest_generator 单测（Phase 4a/4c 核心：容量/GPU/scope 预检 + 安全上下文）。"""

from __future__ import annotations

from app.core.k8s.manifest_generator import (
    BlockDeploySpec,
    DeployContext,
    build_deployment,
    build_network_policy,
    capacity_precheck,
    container_security_context,
    derive_max_replica,
    gcp_scope_precheck,
    gpu_precheck,
    middleware_egress_rules,
    min_replicas_for,
    parse_cpu_millicores,
    parse_mem_mib,
    render_block_manifests,
    runtime_class,
)


def test_parse_cpu_millicores():
    assert parse_cpu_millicores("100m") == 100
    assert parse_cpu_millicores("1") == 1000
    assert parse_cpu_millicores("1.5") == 1500
    assert parse_cpu_millicores(None, 50) == 50


def test_parse_mem_mib():
    assert parse_mem_mib("256Mi") == 256
    assert parse_mem_mib("1Gi") == 1024
    assert parse_mem_mib(None, 128) == 128


def test_container_security_context_restricted():
    sc = container_security_context()
    assert sc["runAsNonRoot"] is True
    assert sc["readOnlyRootFilesystem"] is True
    assert sc["allowPrivilegeEscalation"] is False
    assert sc["seccompProfile"] == {"type": "RuntimeDefault"}
    assert sc["capabilities"] == {"drop": ["ALL"]}


def test_runtime_class_gvisor_only_non_gpu():
    assert runtime_class(False) == "gvisor"
    assert runtime_class(True) is None  # GPU 块禁用 gVisor（决策 1）


def test_min_replicas_sync_never_zero():
    assert min_replicas_for(BlockDeploySpec("b1", "n", execution_mode="sync_http")) == 1
    assert min_replicas_for(BlockDeploySpec("b1", "n", execution_mode="both")) == 1
    assert min_replicas_for(BlockDeploySpec("b1", "n", execution_mode="async_mq")) == 0


def test_capacity_precheck_pass_and_fail():
    specs = [
        BlockDeploySpec("b1", "n1", execution_mode="sync_http",
                        compute_config={"cpu_request": "500m", "memory_request": "512Mi"}),
        BlockDeploySpec("b2", "n2", execution_mode="async_mq"),  # min=0 不计基线
    ]
    ok = capacity_precheck(specs, pool_cpu_cores=4.0, pool_mem_mib=8192)
    assert ok.ok is True

    heavy = [
        BlockDeploySpec(f"b{i}", "n", execution_mode="sync_http",
                        compute_config={"cpu_request": "2000m", "memory_request": "2Gi"})
        for i in range(5)
    ]
    bad = capacity_precheck(heavy, pool_cpu_cores=4.0, pool_mem_mib=8192)
    assert bad.ok is False
    assert "节点池" in bad.reason


def test_derive_max_replica_by_capacity():
    spec = BlockDeploySpec("b1", "n", compute_config={"cpu_limit": "1000m"})
    assert derive_max_replica(spec, pool_cpu_cores=4.0, cap=10) == 4
    assert derive_max_replica(spec, pool_cpu_cores=20.0, cap=10) == 10  # cap 兜底


def test_gpu_precheck_quota_and_cuda():
    spec = BlockDeploySpec("b1", "n", compute_config={
        "gpu_enabled": True, "gpu_type": "nvidia-tesla-t4", "cuda_version": "12.2",
    })
    # 配额未审批直接拒绝
    r = gpu_precheck(spec, allowed_types=["nvidia-tesla-t4"], cuda_matrix={"nvidia-tesla-t4": "12.4"}, quota_enabled=False)
    assert r.ok is False and "配额" in r.reason
    # 配额开启 + CUDA 兼容 → 通过
    r2 = gpu_precheck(spec, allowed_types=["nvidia-tesla-t4"], cuda_matrix={"nvidia-tesla-t4": "12.4"}, quota_enabled=True)
    assert r2.ok is True
    # CUDA 高于驱动 → 拒绝
    spec.compute_config["cuda_version"] = "12.9"
    r3 = gpu_precheck(spec, allowed_types=["nvidia-tesla-t4"], cuda_matrix={"nvidia-tesla-t4": "12.4"}, quota_enabled=True)
    assert r3.ok is False and "驱动" in r3.reason


def test_gcp_scope_precheck():
    spec = BlockDeploySpec("b1", "n", type="gcp_bigquery", gcp_resource_scope=["bq://ds.t"])
    ok = gcp_scope_precheck(spec, authorized_scopes=["bq://ds.t"])
    assert ok.ok is True
    bad = gcp_scope_precheck(spec, authorized_scopes=["bq://other"])
    assert bad.ok is False
    empty = gcp_scope_precheck(BlockDeploySpec("b2", "n", type="gcp_storage"), authorized_scopes=[])
    assert empty.ok is False  # 必须声明 scope


def test_build_deployment_gpu_no_gvisor():
    spec = BlockDeploySpec("abcdef12-0000", "gpu-block", execution_mode="async_mq",
                           compute_config={"gpu_enabled": True, "gpu_type": "nvidia-tesla-t4"})
    ctx = DeployContext(runner_image="runner:1", gpu_runner_image="gpu-runner:1")
    dep = build_deployment(spec, ctx, min_replicas=0)
    pod = dep["spec"]["template"]["spec"]
    assert "runtimeClassName" not in pod  # GPU 块不附 gvisor
    assert any(t["key"] == "pyflow-gpu" for t in pod["tolerations"])
    assert pod["containers"][0]["image"] == "gpu-runner:1"
    assert pod["containers"][0]["resources"]["limits"]["nvidia.com/gpu"] == 1


def test_build_deployment_cpu_has_gvisor_and_protocol_label():
    spec = BlockDeploySpec("abcdef12-0000", "cpu-block", execution_mode="sync_http")
    ctx = DeployContext(runner_image="runner:1")
    dep = build_deployment(spec, ctx, min_replicas=1)
    assert dep["spec"]["template"]["spec"]["runtimeClassName"] == "gvisor"
    assert dep["metadata"]["labels"]["pyflow.runtime/protocol"]
    assert dep["spec"]["template"]["spec"]["containers"][0]["ports"][0]["containerPort"] == 8000


def test_network_policy_gcp_egress_whitelist():
    gcp = BlockDeploySpec("b1", "n", type="gcp_bigquery")
    np = build_network_policy(gcp, DeployContext())
    assert np["spec"]["policyTypes"] == ["Egress"]
    # 含 443 放行 Private Google Access
    ports = [p["port"] for rule in np["spec"]["egress"] for p in rule.get("ports", [])]
    assert 443 in ports
    assert 53 in ports  # kube-dns


def test_middleware_egress_rules_ns_and_cidr():
    rules = middleware_egress_rules(
        middleware_namespace="lhy-styon",
        ns_ports=[5672, 15672, 9000],
        cidr_ports=[("10.0.1.0/24", 6379), ("10.196.0.3/32", 5432)],
    )
    # 命名空间规则按 metadata.name 选中 lhy-styon
    ns_rule = rules[0]
    assert ns_rule["to"][0]["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"] == "lhy-styon"
    ns_ports = [p["port"] for p in ns_rule["ports"]]
    assert ns_ports == [5672, 15672, 9000]
    # VPC 私网 ipBlock 规则
    cidrs = [r["to"][0]["ipBlock"]["cidr"] for r in rules[1:]]
    assert "10.0.1.0/24" in cidrs and "10.196.0.3/32" in cidrs
    redis_rule = next(r for r in rules if r["to"][0].get("ipBlock", {}).get("cidr") == "10.0.1.0/24")
    assert redis_rule["ports"][0]["port"] == 6379


def test_network_policy_injects_middleware_egress():
    spec = BlockDeploySpec("b1", "n", execution_mode="async_mq")
    egress = middleware_egress_rules(
        middleware_namespace="lhy-styon", ns_ports=[5672], cidr_ports=[("10.0.1.0/24", 6379)]
    )
    ctx = DeployContext(inject_middleware=True, middleware_egress=egress)
    np = build_network_policy(spec, ctx)
    ports = [p["port"] for rule in np["spec"]["egress"] for p in rule.get("ports", [])]
    assert 5672 in ports and 6379 in ports and 53 in ports
    # 关闭注入则不放行中间件
    np2 = build_network_policy(spec, DeployContext(inject_middleware=False, middleware_egress=egress))
    ports2 = [p["port"] for rule in np2["spec"]["egress"] for p in rule.get("ports", [])]
    assert 5672 not in ports2 and 53 in ports2


def test_build_deployment_envfrom_middleware_secret():
    spec = BlockDeploySpec("abcdef12-0000", "n", execution_mode="sync_http",
                           env_vars={"FOO": "bar"})
    ctx = DeployContext(runner_image="runner:1", inject_middleware=True,
                        middleware_secret="pyflow-block-middleware")
    dep = build_deployment(spec, ctx, min_replicas=1)
    container = dep["spec"]["template"]["spec"]["containers"][0]
    secret_names = [e["secretRef"]["name"] for e in container["envFrom"]]
    assert "pyflow-block-middleware" in secret_names
    # 合并后的非敏感 env 直接注入
    env_names = {e["name"]: e.get("value") for e in container["env"]}
    assert env_names.get("FOO") == "bar"


def test_build_deployment_no_middleware_when_disabled():
    spec = BlockDeploySpec("abcdef12-0000", "n", execution_mode="sync_http")
    ctx = DeployContext(runner_image="runner:1", inject_middleware=False, middleware_secret="x")
    dep = build_deployment(spec, ctx, min_replicas=1)
    container = dep["spec"]["template"]["spec"]["containers"][0]
    assert container["envFrom"] == []


def test_render_block_manifests_with_keda():
    spec = BlockDeploySpec("abcdef12-0000", "n", execution_mode="async_mq")
    ctx = DeployContext(runner_image="runner:1")
    ms = render_block_manifests(spec, ctx, max_replica=5, msgs_per_replica=10, keda_enabled=True)
    kinds = [m["kind"] for m in ms]
    assert "ScaledObject" in kinds
    dep = next(m for m in ms if m["kind"] == "Deployment")
    assert dep["spec"]["replicas"] == 0  # 有 KEDA：异步块 0 起步，由队列深度拉起


def test_render_block_manifests_keda_degraded():
    """集群未装 KEDA：跳过 ScaledObject，异步块退化为固定副本 min=1（否则无人消费）。"""
    spec = BlockDeploySpec("abcdef12-0000", "n", execution_mode="async_mq")
    ctx = DeployContext(runner_image="runner:1")
    ms = render_block_manifests(spec, ctx, max_replica=5, msgs_per_replica=10, keda_enabled=False)
    kinds = [m["kind"] for m in ms]
    assert "ScaledObject" not in kinds
    dep = next(m for m in ms if m["kind"] == "Deployment")
    assert dep["spec"]["replicas"] == 1
