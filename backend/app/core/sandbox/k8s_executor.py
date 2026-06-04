"""prod GKE 块执行：控制面通过 K8s Job 拉起 runner 镜像（决策 1 / 3.1）。

控制面 Pod 内不挂载 docker.sock、不调用 Docker API；与 dev local 的 docker_executor 分离。
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid
from typing import Any

from pyflow_runtime.sandbox_config import POD_SECURITY_CONTEXT

from app.config import get_settings
from app.core.sandbox.docker_executor import ExecutionOutput, _RESULT_MARKER, _parse_logs
from app.errors import PYFLOW_EXEC_SANDBOX_ERROR, PYFLOW_EXEC_TIMEOUT, BusinessException
from app.observability.logging import get_logger

settings = get_settings()
logger = get_logger()

_EXEC_BOOTSTRAP = (
    "import os,sys,json,base64\n"
    "from pyflow_runtime.executor import execute_user_code\n"
    "p=json.loads(base64.b64decode(os.environ['PYFLOW_EXEC_PAYLOAD_B64']))\n"
    "r=execute_user_code(p['code'],p.get('inputs',{}))\n"
    "sys.stdout.write('\\n" + _RESULT_MARKER + "'+json.dumps(r,default=str))\n"
)


def _k8s_clients():
    try:
        from kubernetes import client, config  # type: ignore
    except ImportError as exc:
        raise BusinessException(
            PYFLOW_EXEC_SANDBOX_ERROR,
            "kubernetes SDK not installed",
        ) from exc

    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.BatchV1Api(), client.CoreV1Api()


def _build_job_manifest(job_name: str, payload_b64: str) -> dict[str, Any]:
    sec = POD_SECURITY_CONTEXT
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": job_name,
            "namespace": settings.k8s_namespace,
            "labels": {"app": "pyflow-exec", "pyflow.runtime/protocol": "1"},
        },
        "spec": {
            "ttlSecondsAfterFinished": 300,
            "backoffLimit": 0,
            "template": {
                "metadata": {"labels": {"app": "pyflow-exec", "job-name": job_name}},
                "spec": {
                    "restartPolicy": "Never",
                    "serviceAccountName": settings.k8s_job_service_account,
                    # Pod 级 securityContext：满足 PodSecurity "restricted" 准入（seccompProfile 必填）
                    "securityContext": {
                        "runAsNonRoot": sec.get("runAsNonRoot", True),
                        "runAsUser": sec.get("runAsUser", 65534),
                        "seccompProfile": sec.get("seccompProfile", {"type": "RuntimeDefault"}),
                    },
                    "volumes": [{"name": "tmp", "emptyDir": {"sizeLimit": "100Mi"}}],
                    "containers": [
                        {
                            "name": "exec",
                            "image": settings.runner_image,
                            "imagePullPolicy": "IfNotPresent",
                            "command": ["python", "-c", _EXEC_BOOTSTRAP],
                            "env": [
                                {"name": "PYFLOW_EXEC_PAYLOAD_B64", "value": payload_b64},
                                # 只读根文件系统下禁止写 .pyc，避免无谓写盘失败
                                {"name": "PYTHONDONTWRITEBYTECODE", "value": "1"},
                            ],
                            "volumeMounts": [{"name": "tmp", "mountPath": "/tmp"}],
                            # 显式 resources：避免命名空间 LimitRange/ResourceQuota 拒绝创建
                            "resources": {
                                "requests": {"cpu": "100m", "memory": "128Mi"},
                                "limits": {"cpu": "500m", "memory": "1Gi"},
                            },
                            # 完整 SecurityContext（含 seccompProfile/capabilities），决策 1，restricted 准入达标
                            "securityContext": {
                                "runAsNonRoot": sec.get("runAsNonRoot", True),
                                "runAsUser": sec.get("runAsUser", 65534),
                                "readOnlyRootFilesystem": sec.get("readOnlyRootFilesystem", True),
                                "allowPrivilegeEscalation": sec.get(
                                    "allowPrivilegeEscalation", False
                                ),
                                "seccompProfile": sec.get(
                                    "seccompProfile", {"type": "RuntimeDefault"}
                                ),
                                "capabilities": sec.get("capabilities", {"drop": ["ALL"]}),
                            },
                        }
                    ],
                },
            },
        },
    }


def _run_job_sync(code: str, inputs: dict[str, Any], timeout: int) -> ExecutionOutput:
    batch_api, core_api = _k8s_clients()
    payload = json.dumps({"code": code, "inputs": inputs}, default=str)
    payload_b64 = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    if len(payload_b64) > 900_000:
        raise BusinessException(PYFLOW_EXEC_SANDBOX_ERROR, "block payload too large for k8s job env")

    job_name = f"pyflow-exec-{uuid.uuid4().hex[:12]}"
    manifest = _build_job_manifest(job_name, payload_b64)
    ns = settings.k8s_namespace

    try:
        batch_api.create_namespaced_job(namespace=ns, body=manifest)
    except Exception as exc:  # noqa: BLE001
        raise BusinessException(
            PYFLOW_EXEC_SANDBOX_ERROR,
            f"create k8s job failed: {exc}",
        ) from exc

    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            job = batch_api.read_namespaced_job_status(name=job_name, namespace=ns)
            status = job.status
            if status.succeeded:
                return _collect_pod_logs(core_api, ns, job_name)
            if status.failed:
                detail = _collect_failure_detail(core_api, ns, job_name)
                raise BusinessException(PYFLOW_EXEC_SANDBOX_ERROR, detail[:800])
            time.sleep(0.5)
        raise BusinessException(PYFLOW_EXEC_TIMEOUT, "k8s job execution timeout")
    finally:
        try:
            batch_api.delete_namespaced_job(
                name=job_name,
                namespace=ns,
                propagation_policy="Background",
            )
        except Exception:  # noqa: BLE001
            logger.warning("k8s_job_cleanup_failed", job=job_name)


def _try_collect_logs(core_api: Any, namespace: str, job_name: str) -> str:
    try:
        out = _collect_pod_logs(core_api, namespace, job_name)
        return (out.stdout or "") + (out.stderr or "")
    except Exception:  # noqa: BLE001
        return ""


def _collect_failure_detail(core_api: Any, namespace: str, job_name: str) -> str:
    """Job 失败时采集可诊断信息：容器等待/终止原因 + exitCode + 日志。

    很多失败（ImagePullBackOff / 启动崩溃 / OOMKilled / 权限）pod 不产生应用日志，
    仅凭日志会得到空串；此处补充 container_statuses 与 pod 事件级原因，便于定位。
    """
    parts: list[str] = []
    try:
        pods = core_api.list_namespaced_pod(
            namespace=namespace, label_selector=f"job-name={job_name}",
        ).items
        if pods:
            pod = pods[0]
            phase = getattr(pod.status, "phase", None)
            if phase:
                parts.append(f"pod phase={phase}")
            if getattr(pod.status, "reason", None):
                parts.append(f"reason={pod.status.reason}")
            for cs in (pod.status.container_statuses or []):
                state = cs.state
                if state and state.waiting and state.waiting.reason:
                    parts.append(
                        f"container waiting: {state.waiting.reason}"
                        f"{' - ' + state.waiting.message if state.waiting.message else ''}"
                    )
                if state and state.terminated:
                    term = state.terminated
                    parts.append(
                        f"container terminated: reason={term.reason} exit={term.exit_code}"
                        f"{' - ' + term.message if term.message else ''}"
                    )
    except Exception:  # noqa: BLE001
        pass

    logs = _try_collect_logs(core_api, namespace, job_name)
    if logs.strip():
        parts.append("logs:\n" + logs.strip())

    # 无 pod / 无日志（如准入拒绝 FailedCreate）时，事件里才有真正原因
    if not logs.strip():
        events = _collect_events(core_api, namespace, job_name)
        if events:
            parts.append("events: " + events)

    return " | ".join(parts) if parts else "k8s job failed (no diagnostics available)"


def _collect_events(core_api: Any, namespace: str, job_name: str) -> str:
    """读取与该 Job 关联的最近事件（捕获 PodSecurity 准入拒绝 / FailedCreate 等原因）。"""
    try:
        evs = core_api.list_namespaced_event(
            namespace=namespace,
            field_selector=f"involvedObject.name={job_name}",
        ).items
        msgs = [f"{e.reason}: {e.message}" for e in evs if e.message][-3:]
        return " ; ".join(msgs)
    except Exception:  # noqa: BLE001
        return ""


def _collect_pod_logs(core_api: Any, namespace: str, job_name: str) -> ExecutionOutput:
    pods = core_api.list_namespaced_pod(
        namespace=namespace,
        label_selector=f"job-name={job_name}",
    ).items
    if not pods:
        raise BusinessException(PYFLOW_EXEC_SANDBOX_ERROR, "k8s job pod not found")
    pod_name = pods[0].metadata.name
    logs = core_api.read_namespaced_pod_log(
        name=pod_name,
        namespace=namespace,
        container="exec",
    )
    return _parse_logs(logs, 0)


async def execute_in_k8s_job(
    code: str,
    inputs: dict[str, Any],
    *,
    timeout: int | None = None,
) -> ExecutionOutput:
    """在 GKE 上通过一次性 Job 执行用户块代码。"""
    timeout = timeout or settings.execution_timeout
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_run_job_sync, code, inputs, timeout),
            timeout=timeout + 30,
        )
    except asyncio.TimeoutError as exc:
        raise BusinessException(PYFLOW_EXEC_TIMEOUT, "k8s job wait timeout") from exc
