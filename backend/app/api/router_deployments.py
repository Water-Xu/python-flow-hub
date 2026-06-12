"""/api/deployments — FlowDeployment（Phase 4a K8s 编排：部署/销毁/状态/预检）。"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import Role, require_role
from app.core.k8s import orchestrator
from app.db import get_session
from app.errors import PYFLOW_EXEC_INPUT_INVALID, PYFLOW_FLOW_NOT_FOUND, BusinessException
from app.models.deployment import FlowDeployment

router = APIRouter(prefix="/api/deployments", tags=["deployments"])


class DeploymentCreateRequest(BaseModel):
    flow_id: str
    name: str
    environment: str = "local"  # local | k8s
    deployment_type: str = "block_mode"  # block_mode | flow_mode


class DeploymentEnvRequest(BaseModel):
    env_vars: dict[str, str] = {}
    secret_refs: dict[str, str] = {}


# CPU：'100m' / '0.5' / '2'；内存：'256Mi' / '1Gi' / '512M'
_CPU_PATTERN = r"^\d+(\.\d+)?m?$"
_MEM_PATTERN = r"^\d+(\.\d+)?(Ki|Mi|Gi|Ti|Pi|K|M|G|T|P)?$"
_GPU_TYPE_PATTERN = r"^[a-z0-9-]+$"


class BlockResourceSpec(BaseModel):
    """单个 Block 的 Pod 资源覆盖（仅作用于本部署；空字段表示沿用块默认值）。"""

    cpu_request: str | None = Field(default=None, pattern=_CPU_PATTERN)
    memory_request: str | None = Field(default=None, pattern=_MEM_PATTERN)
    cpu_limit: str | None = Field(default=None, pattern=_CPU_PATTERN)
    memory_limit: str | None = Field(default=None, pattern=_MEM_PATTERN)
    gpu_enabled: bool | None = None
    gpu_count: int | None = Field(default=None, ge=1, le=8)
    gpu_type: str | None = Field(default=None, pattern=_GPU_TYPE_PATTERN, max_length=64)


class DeploymentResourceRequest(BaseModel):
    """部署级 Pod 资源覆盖：{block_id: BlockResourceSpec}。"""

    resource_overrides: dict[str, BlockResourceSpec] = {}


class DependencyInstallRequest(BaseModel):
    """安装依赖到部署的块 requirements（重新部署后生效）。"""

    package: str = Field(..., min_length=1, max_length=256)
    block_ids: list[str] | None = None  # None 表示全部块


def _dep_dict(d: FlowDeployment) -> dict:
    return {
        "id": d.id, "flow_id": d.flow_id, "flow_version_id": d.flow_version_id,
        "name": d.name, "environment": d.environment, "status": d.status,
        "deployment_type": getattr(d, "deployment_type", "block_mode"),
        "resource_prefix": d.resource_prefix, "entry_endpoint": d.entry_endpoint,
        "block_statuses": d.block_statuses or [], "created_at": d.created_at,
        "env_vars": d.env_vars or {}, "secret_refs": d.secret_refs or {},
        "resource_overrides": d.resource_overrides or {},
    }


async def _get(session: AsyncSession, deployment_id: str) -> FlowDeployment:
    dep = await session.get(FlowDeployment, deployment_id)
    if dep is None:
        raise BusinessException(PYFLOW_FLOW_NOT_FOUND, deployment_id)
    return dep


@router.get("")
async def list_deployments(
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    rows = (await session.execute(
        select(FlowDeployment).order_by(FlowDeployment.created_at.desc())
    )).scalars().all()
    return [_dep_dict(d) for d in rows]


@router.get("/{deployment_id}")
async def get_deployment(
    deployment_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    return _dep_dict(await _get(session, deployment_id))


@router.post("")
async def create_deployment(
    req: DeploymentCreateRequest,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.DEPLOYER)),
):
    prefix = f"flow-{req.flow_id[:8]}-{req.name}".lower().replace(" ", "-")[:63]
    dep = FlowDeployment(
        flow_id=req.flow_id, name=req.name, environment=req.environment,
        deployment_type=req.deployment_type,
        resource_prefix=prefix, status="stopped",
        entry_endpoint=f"/flow/{req.flow_id}/invoke",
    )
    session.add(dep)
    await session.commit()
    await session.refresh(dep)
    return _dep_dict(dep)


@router.put("/{deployment_id}/env")
async def update_deployment_env(
    deployment_id: str,
    req: DeploymentEnvRequest,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.DEPLOYER)),
):
    """配置部署级环境变量（注入该部署全部块；下次部署生效）。"""
    dep = await _get(session, deployment_id)
    dep.env_vars = req.env_vars or {}
    dep.secret_refs = req.secret_refs or {}
    await session.commit()
    return _dep_dict(dep)


@router.get("/{deployment_id}/resources")
async def list_deployment_resources(
    deployment_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    """列出该部署的 Pod 资源（flow_mode: 整流单 Pod；block_mode: 各块独立 Pod）。"""
    dep = await _get(session, deployment_id)
    if getattr(dep, "deployment_type", "block_mode") == "flow_mode":
        return orchestrator.list_flow_runner_resource(dep)
    return await orchestrator.list_block_resources(session, dep)


@router.put("/{deployment_id}/resources")
async def update_deployment_resources(
    deployment_id: str,
    req: DeploymentResourceRequest,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.DEPLOYER)),
):
    """配置部署级 Pod 资源覆盖（按 block_id 覆盖 CPU/内存/GPU；下次部署生效）。"""
    dep = await _get(session, deployment_id)
    overrides: dict[str, dict] = {}
    for block_id, spec in (req.resource_overrides or {}).items():
        # 仅保留显式设置的字段，空值不写入（沿用块默认）
        cleaned = {k: v for k, v in spec.model_dump().items() if v is not None}
        if cleaned:
            overrides[block_id] = cleaned
    dep.resource_overrides = overrides
    await session.commit()
    return _dep_dict(dep)


@router.get("/{deployment_id}/resource-summary")
async def deployment_resource_summary(
    deployment_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    """Flow 维度资源汇总（flow_mode: 整流单 Pod；block_mode: 各块独立 Pod 累加）。"""
    dep = await _get(session, deployment_id)
    if getattr(dep, "deployment_type", "block_mode") == "flow_mode":
        return orchestrator.flow_runner_resource_summary(dep)
    return await orchestrator.flow_resource_summary(session, dep)


@router.post("/{deployment_id}/resources/precheck")
async def precheck_deployment_resources(
    deployment_id: str,
    req: DeploymentResourceRequest,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    """对“尚未保存”的资源覆盖做实时容量/GPU/scope 预检（编辑时即时反馈，不落库）。"""
    dep = await _get(session, deployment_id)
    is_flow_mode = getattr(dep, "deployment_type", "block_mode") == "flow_mode"

    if is_flow_mode:
        from app.core.k8s.manifest_generator import BlockDeploySpec
        flow_spec_data = (req.resource_overrides or {}).get(orchestrator.FLOW_RUNNER_RESOURCE_KEY)
        override = {k: v for k, v in (flow_spec_data.model_dump() if flow_spec_data else {}).items() if v is not None}
        compute = {**orchestrator._FLOW_RUNNER_DEFAULT_COMPUTE, **override}
        synthetic = BlockDeploySpec(
            block_id=orchestrator.FLOW_RUNNER_RESOURCE_KEY,
            name="FlowRunner",
            compute_config=compute,
        )
        return orchestrator.run_prechecks([synthetic])

    specs = await orchestrator.build_specs(session, dep.flow_id)
    overrides: dict[str, dict] = {}
    for block_id, spec in (req.resource_overrides or {}).items():
        cleaned = {k: v for k, v in spec.model_dump().items() if v is not None}
        if cleaned:
            overrides[block_id] = cleaned
    orchestrator.merge_resource_overrides_into_specs(specs, overrides)
    return orchestrator.run_prechecks(specs)


@router.get("/{deployment_id}/precheck")
async def precheck_deployment(
    deployment_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.DEPLOYER)),
):
    """容量 + GPU + scope 预检（含部署级资源覆盖；不部署）。"""
    dep = await _get(session, deployment_id)
    specs = await orchestrator.build_deployment_specs(session, dep)
    return orchestrator.run_prechecks(specs)


@router.get("/{deployment_id}/manifests")
async def render_manifests(
    deployment_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.DEPLOYER)),
):
    """渲染 K8s manifest 预览（不 apply；含全局/部署级环境变量与中间件接入）。"""
    dep = await _get(session, deployment_id)
    specs = await orchestrator.build_deployment_specs(session, dep)
    ctx = orchestrator._build_context(dep)
    return {"manifests": orchestrator.render_all_manifests(specs, ctx)}


@router.post("/{deployment_id}/deploy")
async def deploy_deployment(
    deployment_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.DEPLOYER)),
):
    """一键部署到 K8s（构建/apply Deployment/Service/KEDA/NetworkPolicy）。"""
    dep = await _get(session, deployment_id)
    return await orchestrator.deploy(session, dep)


@router.get("/{deployment_id}/status")
async def deployment_status(
    deployment_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    """实时 K8s 状态（副本/Ready）。"""
    dep = await _get(session, deployment_id)
    if dep.environment != "k8s":
        return {"status": dep.status, "block_statuses": dep.block_statuses or []}
    return await orchestrator.status(session, dep)


@router.get("/{deployment_id}/pods")
async def list_deployment_pods(
    deployment_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    """列出该部署的全部 Pod（含状态/重启次数/节点）。"""
    dep = await _get(session, deployment_id)
    if dep.environment != "k8s":
        return []

    def _do():
        from kubernetes import client, config  # type: ignore
        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()
        v1 = client.CoreV1Api()
        namespace = "pyflow-blocks"
        label_selector = f"pyflow.deploy/prefix={dep.resource_prefix}"
        pods = v1.list_namespaced_pod(namespace, label_selector=label_selector)
        result = []
        for pod in pods.items:
            cs = pod.status.container_statuses or []
            restarts = sum(c.restart_count for c in cs) if cs else 0
            state = "unknown"
            if pod.status.phase:
                state = pod.status.phase.lower()
            if cs:
                st = cs[0].state
                if st.running:
                    state = "running"
                elif st.waiting:
                    state = f"waiting:{st.waiting.reason or ''}"
                elif st.terminated:
                    state = f"terminated:{st.terminated.reason or ''}"
            result.append({
                "name": pod.metadata.name,
                "node": pod.spec.node_name or "",
                "phase": pod.status.phase or "Unknown",
                "state": state,
                "restarts": restarts,
                "app": pod.metadata.labels.get("app", "") if pod.metadata.labels else "",
                "ready": all(c.ready for c in cs) if cs else False,
                "start_time": pod.status.start_time.isoformat() if pod.status.start_time else None,
            })
        return result

    import asyncio
    return await asyncio.to_thread(_do)


@router.get("/{deployment_id}/pods/{pod_name}/logs")
async def get_pod_logs(
    deployment_id: str,
    pod_name: str,
    container: str | None = None,
    tail_lines: int = 200,
    previous: bool = False,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    """获取指定 Pod 的运行日志（tail_lines 行，previous=true 看上次崩溃日志）。"""
    dep = await _get(session, deployment_id)
    if dep.environment != "k8s":
        return {"logs": ""}

    def _do():
        from kubernetes import client, config  # type: ignore
        from kubernetes.client.rest import ApiException  # type: ignore
        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()
        v1 = client.CoreV1Api()
        namespace = "pyflow-blocks"
        kwargs: dict = {
            "tail_lines": max(1, min(tail_lines, 2000)),
            "timestamps": True,
        }
        if container:
            kwargs["container"] = container
        if previous:
            kwargs["previous"] = True
        try:
            logs = v1.read_namespaced_pod_log(pod_name, namespace, **kwargs)
        except ApiException as e:
            if e.status == 400 and previous:
                logs = f"[无上次崩溃日志] HTTP {e.status}: {e.reason}"
            else:
                logs = f"[获取日志失败] HTTP {e.status}: {e.reason}"
        return {"logs": logs or "（暂无日志）"}

    import asyncio
    return await asyncio.to_thread(_do)


@router.delete("/{deployment_id}")
async def destroy_deployment(
    deployment_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.ADMIN)),
):
    """销毁部署（删除全部 K8s 资源，ADMIN）。"""
    dep = await _get(session, deployment_id)
    if dep.environment == "k8s":
        await orchestrator.destroy(session, dep)
    await session.delete(dep)
    await session.commit()
    return {"deleted": True}


@router.get("/{deployment_id}/build-logs")
async def get_deployment_build_logs(
    deployment_id: str,
    hours: int = 24,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    """获取最近依赖镜像 Cloud Build 构建日志（用于诊断 partially_degraded 状态）。"""
    from app.config import get_settings as _get_settings
    _settings = _get_settings()

    if not _settings.cloudbuild_enabled:
        return {"builds": [], "note": "Cloud Build 未启用"}

    def _fetch() -> list[dict]:
        import google.auth  # type: ignore
        from google.auth.transport.requests import Request  # type: ignore
        import httpx
        from datetime import datetime, timezone, timedelta

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(Request())
        token = creds.token
        project = _settings.gcp_project
        hdrs = {"Authorization": f"Bearer {token}"}

        # 1. 列出最近 N 小时的构建（含所有状态）
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=max(1, min(hours, 72)))).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        url = f"https://cloudbuild.googleapis.com/v1/projects/{project}/builds"
        with httpx.Client(timeout=20) as cli:
            resp = cli.get(url, headers=hdrs, params={"filter": f'create_time>"{cutoff}"', "pageSize": 30})
            if resp.status_code != 200:
                return []
            builds_raw = resp.json().get("builds", [])

        # 2. 只保留 dep- 镜像相关的构建
        dep_builds = [
            b for b in builds_raw
            if any(":dep-" in (img or "") for img in b.get("images", []))
        ][:6]

        if not dep_builds:
            return []

        # 3. 查询 Cloud Logging 获取最近日志行
        result = []
        for b in dep_builds:
            build_id = b["id"]
            status = b.get("status", "UNKNOWN")
            image = next((img for img in b.get("images", []) if ":dep-" in img), "")

            log_lines: list[str] = []
            if status in ("FAILURE", "SUCCESS", "WORKING"):
                log_filter = (
                    f'logName="projects/{project}/logs/cloudbuild" '
                    f'labels.build_id="{build_id}"'
                )
                with httpx.Client(timeout=20) as cli:
                    lr = cli.post(
                        "https://logging.googleapis.com/v2/entries:list",
                        headers=hdrs,
                        json={
                            "resourceNames": [f"projects/{project}"],
                            "filter": log_filter,
                            "orderBy": "timestamp desc",
                            "pageSize": 100,
                        },
                    )
                    if lr.status_code == 200:
                        entries = lr.json().get("entries", [])
                        for e in reversed(entries):
                            msg = (
                                e.get("textPayload")
                                or e.get("jsonPayload", {}).get("message", "")
                                or e.get("jsonPayload", {}).get("text", "")
                            )
                            if msg and msg.strip():
                                log_lines.append(msg.rstrip())

            result.append({
                "id": build_id,
                "status": status,
                "image": image.rsplit(":", 1)[-1] if ":" in image else image,
                "image_full": image,
                "create_time": b.get("createTime", ""),
                "duration": b.get("duration", ""),
                "log_lines": log_lines,
                "console_url": (
                    f"https://console.cloud.google.com/cloud-build/builds/{build_id}"
                    f"?project={project}"
                ),
            })

        return result

    import asyncio
    builds = await asyncio.to_thread(_fetch)
    return {"builds": builds}


def _parse_requirements_text(text: str) -> list[dict]:
    """解析 requirements.txt 文本为结构化包信息列表。"""
    packages = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("@gcs:") or stripped.startswith("@wheel:"):
            pkg_type = "wheel"
            fname = stripped.rsplit("/", 1)[-1]
            if fname.endswith(".whl"):
                fname = fname[:-4]
            packages.append({"spec": stripped, "type": pkg_type, "name": fname, "version_spec": ""})
        elif stripped.startswith("-") or stripped.startswith("--"):
            packages.append({"spec": stripped, "type": "option", "name": stripped, "version_spec": ""})
        else:
            m = re.match(r"^([a-zA-Z0-9][a-zA-Z0-9._-]*(?:\[[^\]]+\])?)\s*([=<>!~].+)?$", stripped)
            if m:
                name = m.group(1)
                version_spec = (m.group(2) or "").strip()
                packages.append({"spec": stripped, "type": "pypi", "name": name, "version_spec": version_spec})
            else:
                packages.append({"spec": stripped, "type": "other", "name": stripped, "version_spec": ""})
    return packages


@router.get("/{deployment_id}/dependencies")
async def list_deployment_dependencies(
    deployment_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    """列出该部署所有块的 Python 依赖声明（来自 draft_requirements）。"""
    from app.models.block import Block
    from app.models.flow import FlowNode

    dep = await _get(session, deployment_id)
    nodes = (await session.execute(
        select(FlowNode).where(FlowNode.flow_id == dep.flow_id, FlowNode.node_type == "block")
    )).scalars().all()

    blocks_data = []
    seen_block_ids: set[str] = set()
    merged: dict[str, dict] = {}

    for node in nodes:
        if not node.block_id or node.block_id in seen_block_ids:
            continue
        seen_block_ids.add(node.block_id)
        block = await session.get(Block, node.block_id)
        if block is None:
            continue
        packages = _parse_requirements_text(block.draft_requirements or "")
        blocks_data.append({
            "block_id": block.id,
            "name": block.name,
            "packages": packages,
            "requirements_raw": block.draft_requirements or "",
        })
        for pkg in packages:
            key = pkg["name"].lower().replace("-", "_")
            if key not in merged:
                merged[key] = pkg

    return {
        "deployment_id": dep.id,
        "deployment_type": getattr(dep, "deployment_type", "block_mode"),
        "blocks": blocks_data,
        "merged": list(merged.values()),
    }


@router.post("/{deployment_id}/dependencies/install")
async def install_deployment_dependency(
    deployment_id: str,
    req: DependencyInstallRequest,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.DEPLOYER)),
):
    """在该部署块的 draft_requirements 中追加依赖（重新部署后生效）。"""
    from app.models.block import Block
    from app.models.flow import FlowNode

    pkg_spec = req.package.strip()
    # 允许 PyPI 包规范或 @gcs:/@wheel: wheel 引用
    if not re.match(r"^(@(gcs|wheel):.*|[a-zA-Z0-9][a-zA-Z0-9._-]*([\s\[=<>!~].*)?)$", pkg_spec):
        raise BusinessException(PYFLOW_EXEC_INPUT_INVALID, f"包规范非法：{pkg_spec!r}")

    dep = await _get(session, deployment_id)
    nodes = (await session.execute(
        select(FlowNode).where(FlowNode.flow_id == dep.flow_id, FlowNode.node_type == "block")
    )).scalars().all()

    updated_blocks: list[str] = []
    seen_block_ids: set[str] = set()

    # 提取待添加包名（用于去重判断）
    pkg_name_key = re.split(r"[\s\[=<>!~]", pkg_spec.lstrip("@").split(":", 1)[-1] if pkg_spec.startswith("@") else pkg_spec, maxsplit=1)[0].lower().replace("-", "_")

    for node in nodes:
        if not node.block_id or node.block_id in seen_block_ids:
            continue
        seen_block_ids.add(node.block_id)
        if req.block_ids is not None and node.block_id not in req.block_ids:
            continue
        block = await session.get(Block, node.block_id)
        if block is None:
            continue

        # 已存在则跳过（避免重复添加）
        current = block.draft_requirements or ""
        existing_keys = {
            re.split(r"[\s\[=<>!~]", ln.strip(), maxsplit=1)[0].lower().replace("-", "_")
            for ln in current.splitlines()
            if ln.strip() and not ln.strip().startswith("#") and not ln.strip().startswith("@")
        }
        if pkg_name_key in existing_keys:
            continue

        block.draft_requirements = (current.rstrip("\n") + "\n" + pkg_spec + "\n").lstrip("\n")
        updated_blocks.append(block.name)

    await session.commit()
    return {
        "installed": pkg_spec,
        "updated_blocks": updated_blocks,
        "message": f"已添加到 {len(updated_blocks)} 个块的 requirements（重新部署后生效）",
    }
