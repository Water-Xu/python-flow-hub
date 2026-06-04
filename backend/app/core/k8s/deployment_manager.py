"""K8s 资源 apply/delete（Phase 4a）。

控制面通过 K8s API 创建/更新/删除 Block Deployment、Service、NetworkPolicy、Secret 及
KEDA ScaledObject/TriggerAuthentication（决策 3.1 模型 A：控制面只编排，不在 Pod 内跑 Docker）。
全部 namespaced，限定 pyflow-blocks（决策 K8s RBAC）。
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.errors import PYFLOW_K8S_DEPLOY_FAILED, BusinessException
from app.observability.logging import get_logger

logger = get_logger("pyflow.k8s")

_KEDA_GROUP = "keda.sh"
_KEDA_VERSION = "v1alpha1"


def _load_clients():
    try:
        from kubernetes import client, config  # type: ignore
    except ImportError as exc:
        raise BusinessException(PYFLOW_K8S_DEPLOY_FAILED, "kubernetes SDK not installed") from exc
    try:
        config.load_incluster_config()
    except Exception:  # noqa: BLE001 本地降级 kubeconfig
        try:
            config.load_kube_config()
        except Exception as exc:  # noqa: BLE001
            raise BusinessException(PYFLOW_K8S_DEPLOY_FAILED, f"kube config unavailable: {exc}") from exc
    return client


def _apply_one(client, manifest: dict[str, Any], namespace: str) -> None:
    """create-or-replace 单个 manifest。"""
    from kubernetes.client.rest import ApiException  # type: ignore

    kind = manifest["kind"]
    name = manifest["metadata"]["name"]

    def _cr(create, read, replace):
        try:
            read()
            replace()
        except ApiException as e:
            if e.status == 404:
                create()
            else:
                raise

    if kind == "Deployment":
        api = client.AppsV1Api()
        _cr(
            lambda: api.create_namespaced_deployment(namespace, manifest),
            lambda: api.read_namespaced_deployment(name, namespace),
            lambda: api.replace_namespaced_deployment(name, namespace, manifest),
        )
    elif kind == "Service":
        api = client.CoreV1Api()
        # Service 需保留 clusterIP，replace 易冲突 → 用 patch
        try:
            api.read_namespaced_service(name, namespace)
            api.patch_namespaced_service(name, namespace, manifest)
        except ApiException as e:
            if e.status == 404:
                api.create_namespaced_service(namespace, manifest)
            else:
                raise
    elif kind == "Secret":
        api = client.CoreV1Api()
        _cr(
            lambda: api.create_namespaced_secret(namespace, manifest),
            lambda: api.read_namespaced_secret(name, namespace),
            lambda: api.replace_namespaced_secret(name, namespace, manifest),
        )
    elif kind == "NetworkPolicy":
        api = client.NetworkingV1Api()
        _cr(
            lambda: api.create_namespaced_network_policy(namespace, manifest),
            lambda: api.read_namespaced_network_policy(name, namespace),
            lambda: api.replace_namespaced_network_policy(name, namespace, manifest),
        )
    elif kind in ("ScaledObject", "TriggerAuthentication"):
        api = client.CustomObjectsApi()
        plural = "scaledobjects" if kind == "ScaledObject" else "triggerauthentications"
        try:
            api.get_namespaced_custom_object(_KEDA_GROUP, _KEDA_VERSION, namespace, plural, name)
            api.patch_namespaced_custom_object(
                _KEDA_GROUP, _KEDA_VERSION, namespace, plural, name, manifest
            )
        except ApiException as e:
            if e.status == 404:
                api.create_namespaced_custom_object(
                    _KEDA_GROUP, _KEDA_VERSION, namespace, plural, manifest
                )
            else:
                raise
    else:
        raise BusinessException(PYFLOW_K8S_DEPLOY_FAILED, f"unsupported kind: {kind}")


def _delete_one(client, kind: str, name: str, namespace: str) -> None:
    from kubernetes.client.rest import ApiException  # type: ignore

    def _swallow(fn):
        try:
            fn()
        except ApiException as e:
            if e.status != 404:
                raise

    if kind == "Deployment":
        _swallow(lambda: client.AppsV1Api().delete_namespaced_deployment(name, namespace))
    elif kind == "Service":
        _swallow(lambda: client.CoreV1Api().delete_namespaced_service(name, namespace))
    elif kind == "Secret":
        _swallow(lambda: client.CoreV1Api().delete_namespaced_secret(name, namespace))
    elif kind == "NetworkPolicy":
        _swallow(lambda: client.NetworkingV1Api().delete_namespaced_network_policy(name, namespace))
    elif kind in ("ScaledObject", "TriggerAuthentication"):
        plural = "scaledobjects" if kind == "ScaledObject" else "triggerauthentications"
        _swallow(lambda: client.CustomObjectsApi().delete_namespaced_custom_object(
            _KEDA_GROUP, _KEDA_VERSION, namespace, plural, name
        ))


async def apply_manifests(manifests: list[dict[str, Any]], namespace: str) -> None:
    """顺序 apply 一批 manifest（幂等）。"""
    def _do() -> None:
        client = _load_clients()
        for m in manifests:
            _apply_one(client, m, namespace)
            logger.info("k8s_applied", kind=m["kind"], name=m["metadata"]["name"])

    await asyncio.to_thread(_do)


async def delete_manifests(manifests: list[dict[str, Any]], namespace: str) -> None:
    """逆序删除一批 manifest（先删 ScaledObject 再删 Deployment，避免 KEDA 重建）。"""
    def _do() -> None:
        client = _load_clients()
        for m in reversed(manifests):
            _delete_one(client, m["kind"], m["metadata"]["name"], namespace)
            logger.info("k8s_deleted", kind=m["kind"], name=m["metadata"]["name"])

    await asyncio.to_thread(_do)


async def read_deployment_status(name: str, namespace: str) -> dict[str, Any]:
    """读取单个 Deployment 的副本状态（供 cluster_monitor / 部署中心）。"""
    def _do() -> dict[str, Any]:
        from kubernetes.client.rest import ApiException  # type: ignore

        client = _load_clients()
        api = client.AppsV1Api()
        try:
            dep = api.read_namespaced_deployment(name, namespace)
        except ApiException as e:
            if e.status == 404:
                return {"exists": False, "replicas": 0, "ready": 0}
            raise
        status = dep.status
        return {
            "exists": True,
            "replicas": status.replicas or 0,
            "ready": status.ready_replicas or 0,
            "available": status.available_replicas or 0,
            "updated": status.updated_replicas or 0,
        }

    return await asyncio.to_thread(_do)
