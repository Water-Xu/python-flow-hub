"""集群状态采集（Phase 4a）：Block / Flow-Consumer / FlowRunner Deployment 副本/Pod 状态 → 部署中心 / WS 推送。"""

from __future__ import annotations

from typing import Any

from app.core.k8s.deployment_manager import read_deployment_status
from app.core.k8s.manifest_generator import (
    BlockDeploySpec,
    DeployContext,
    FlowConsumerSpec,
    FlowRunnerSpec,
    deployment_name,
    flow_consumer_name,
    flow_runner_name,
)
from app.observability.logging import get_logger

logger = get_logger("pyflow.k8s.monitor")


async def collect_deployment_status(
    specs: list[BlockDeploySpec],
    ctx: DeployContext,
    flow_consumer_specs: list[FlowConsumerSpec] | None = None,
) -> list[dict[str, Any]]:
    """采集一个 FlowDeployment 下所有 Block invoke 服务 + Flow-Consumer 的副本状态。"""
    statuses: list[dict[str, Any]] = []
    for spec in specs:
        name = deployment_name(ctx, spec)
        try:
            st = await read_deployment_status(name, ctx.namespace)
        except Exception as exc:  # noqa: BLE001 单块查询失败不影响整体
            logger.warning("deploy_status_failed", block_id=spec.block_id, error=str(exc))
            st = {"exists": False, "replicas": 0, "ready": 0, "error": str(exc)}
        block_status = {
            "block_id": spec.block_id,
            "name": spec.name,
            "deployment": name,
            "kind": "block",
            **st,
        }
        statuses.append(block_status)
        _update_metrics(ctx.resource_prefix, spec.block_id, st.get("replicas", 0))

    for fc in flow_consumer_specs or []:
        name = flow_consumer_name(ctx, fc)
        try:
            st = await read_deployment_status(name, ctx.namespace)
        except Exception as exc:  # noqa: BLE001
            logger.warning("flow_consumer_status_failed", api_id=fc.api_id, error=str(exc))
            st = {"exists": False, "replicas": 0, "ready": 0, "error": str(exc)}
        statuses.append({
            "api_id": fc.api_id,
            "name": fc.api_name,
            "deployment": name,
            "kind": "flow_consumer",
            **st,
        })
    return statuses


def aggregate_status(block_statuses: list[dict[str, Any]]) -> str:
    """聚合为 FlowDeployment 级别状态。"""
    if not block_statuses:
        return "stopped"
    existing = [b for b in block_statuses if b.get("exists")]
    if not existing:
        return "stopped"
    all_ready = all(b.get("ready", 0) >= 1 or b.get("replicas", 0) == 0 for b in existing)
    any_degraded = any(b.get("replicas", 0) > 0 and b.get("ready", 0) == 0 for b in existing)
    if all_ready and not any_degraded:
        return "running"
    if any_degraded:
        return "partially_degraded"
    return "deploying"


def _update_metrics(resource_prefix: str, block_id: str, replicas: int) -> None:
    try:
        from app.observability.metrics import K8S_BLOCK_REPLICAS

        K8S_BLOCK_REPLICAS.labels(resource_prefix=resource_prefix or "adhoc", block_id=block_id).set(replicas)
    except Exception:  # noqa: BLE001
        pass


async def collect_flow_runner_status(
    spec: FlowRunnerSpec,
    ctx: DeployContext,
) -> list[dict[str, Any]]:
    """采集 flow_mode 整流单 Pod 的副本状态（单一 FlowRunner Deployment）。"""
    name = flow_runner_name(ctx, spec)
    try:
        st = await read_deployment_status(name, ctx.namespace)
    except Exception as exc:  # noqa: BLE001
        logger.warning("flow_runner_status_failed", flow_id=spec.flow_id, error=str(exc))
        st = {"exists": False, "replicas": 0, "ready": 0, "error": str(exc)}
    return [
        {
            "flow_id": spec.flow_id,
            "name": spec.flow_name,
            "deployment": name,
            "kind": "flow_runner",
            **st,
        }
    ]
