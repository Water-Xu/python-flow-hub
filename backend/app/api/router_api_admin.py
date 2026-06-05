"""/api/admin — 管理员接口：统一查看所有已发布接口 + 策略配置 + 锁定管理 + 版本切换。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import Role, require_role
from app.config import get_settings
from app.core.mq.invocation_doc import build_mq_invocation
from app.db import get_session
from app.errors import PYFLOW_API_NOT_FOUND, BusinessException
from app.models.api_portal import PublishedApi
from app.models.block import Block
from app.models.deployment import FlowDeployment
from app.models.flow import Flow, FlowEdge, FlowNode
from app.schemas.api_portal import (
    ApiInstanceInfo,
    ApiPolicyRequest,
    ApiResponse,
    LockApiRequest,
    SwitchVersionRequest,
)

router = APIRouter(prefix="/api/admin", tags=["api-admin"])

settings = get_settings()


async def _get_api(session: AsyncSession, api_id: str) -> PublishedApi:
    api = await session.get(PublishedApi, api_id)
    if api is None:
        raise BusinessException(PYFLOW_API_NOT_FOUND, api_id)
    return api


@router.get("/apis", response_model=list[ApiResponse])
async def list_all_apis(
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.ADMIN)),
):
    """管理员：查看所有用户发布的接口。"""
    rows = (await session.execute(
        select(PublishedApi).order_by(PublishedApi.created_at.desc())
    )).scalars().all()
    return rows


@router.get("/apis/{api_id}", response_model=ApiResponse)
async def get_api_detail(
    api_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.ADMIN)),
):
    return await _get_api(session, api_id)


@router.get("/apis/{api_id}/docs")
async def get_admin_api_docs(
    api_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.ADMIN)),
):
    """管理员查看接口文档（含内部块信息）。"""
    api = await _get_api(session, api_id)
    flow_id = api.active_flow_id or api.flow_id
    flow = await session.get(Flow, flow_id)

    nodes = (await session.execute(
        select(FlowNode).where(FlowNode.flow_id == flow_id)
    )).scalars().all()

    block_docs = []
    entry_input_ports: list = []
    edge_target_ids = {e.target_node_id for e in (await session.execute(
        select(FlowEdge).where(FlowEdge.flow_id == flow_id)
    )).scalars().all()}
    for node in nodes:
        if node.block_id:
            block = await session.get(Block, node.block_id)
            if block:
                block_docs.append({
                    "node_id": node.id,
                    "block_id": block.id,
                    "block_name": block.name,
                    "description": block.description,
                    "owner_login_id": block.owner_login_id,
                    "type": block.type,
                    # 该节点实际调用的入口函数（默认 run）
                    "entrypoint": (node.config or {}).get("entrypoint") or "run",
                    "input_ports": block.input_ports,
                    "output_ports": block.output_ports,
                    "compute_config": block.compute_config,
                })
                # 流程入口块（无入边）端口用于 MQ 示例消息体
                if node.id not in edge_target_ids:
                    entry_input_ports.extend(block.input_ports or [])

    # 接口级 MQ 触发文档（trigger_type 为 mq/both 时非空）
    mq_invocation = build_mq_invocation(api, entry_input_ports)

    return {
        "api_id": api_id,
        "name": api.name,
        "description": api.description,
        "path": f"/api/public/{api.path}",
        "method": "POST",
        "status": api.status,
        "is_locked": api.is_locked,
        "owner_login_id": api.owner_login_id,
        "trigger_type": api.trigger_type,
        "flow_id": flow_id,
        "flow_name": flow.name if flow else "未知",
        "blocks": block_docs,
        "mq_supported": mq_invocation is not None,
        "mq_invocation": mq_invocation,
        "stats": {
            "total_calls": api.total_calls,
            "success_calls": api.success_calls,
            "error_calls": api.error_calls,
            "success_rate": (
                round(api.success_calls / api.total_calls * 100, 1)
                if api.total_calls > 0 else 0
            ),
            "avg_latency_ms": round(api.avg_latency_ms, 2),
        },
    }


@router.get("/apis/{api_id}/instances", response_model=ApiInstanceInfo)
async def get_api_instances(
    api_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.ADMIN)),
):
    """查看接口实例数（Phase 4+ 实时查询 K8s；当前 dev-local 返回占位信息）。"""
    api = await _get_api(session, api_id)
    mode = settings.deployment_mode

    if mode == "local":
        instances = [
            {
                "pod_name": "pyflow-hub-dev-local",
                "status": "running",
                "ready": True,
                "restart_count": 0,
                "cpu_usage": "—",
                "memory_usage": "—",
            }
        ]
        return ApiInstanceInfo(
            deployment_mode=mode,
            instance_count=1,
            instances=instances,
        )

    # K8s 模式：查询该 API 关联 flow 的最新运行部署，将 block_statuses 映射为实例信息
    flow_id = api.active_flow_id or api.flow_id
    deployment = (await session.execute(
        select(FlowDeployment)
        .where(
            FlowDeployment.flow_id == flow_id,
            FlowDeployment.status.in_(["running", "partially_degraded"]),
        )
        .order_by(FlowDeployment.updated_at.desc())
    )).scalars().first()

    if deployment is None or not deployment.block_statuses:
        return ApiInstanceInfo(deployment_mode=mode, instance_count=0, instances=[])

    def _bs_status(bs: dict) -> str:
        if not bs.get("exists"):
            return "stopped"
        replicas = bs.get("replicas", 0) or 0
        ready = bs.get("ready", 0) or 0
        if ready >= 1:
            return "running"
        if replicas > 0:
            return "degraded"
        return "scaled_down"

    instances = [
        {
            "pod_name": bs.get("deployment") or bs.get("name") or bs.get("block_id") or "—",
            "status": _bs_status(bs),
            "ready": (bs.get("ready", 0) or 0) >= 1,
            "restart_count": 0,
            "cpu_usage": "—",
            "memory_usage": "—",
            "replicas": bs.get("replicas", 0) or 0,
            "kind": bs.get("kind", "block"),
            "block_id": bs.get("block_id"),
            "block_name": bs.get("name") if bs.get("kind") != "flow_consumer" else None,
            "api_id": bs.get("api_id"),
            "label": bs.get("name"),
        }
        for bs in deployment.block_statuses
    ]
    instance_count = sum(1 for inst in instances if inst["ready"])
    return ApiInstanceInfo(
        deployment_mode=mode,
        instance_count=instance_count,
        instances=instances,
    )


@router.get("/stats/overview")
async def get_stats_overview(
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.ADMIN)),
):
    """全局流量概览。"""
    apis = (await session.execute(select(PublishedApi))).scalars().all()
    total_calls = sum(a.total_calls for a in apis)
    success_calls = sum(a.success_calls for a in apis)
    error_calls = sum(a.error_calls for a in apis)
    active_count = sum(1 for a in apis if a.status == "active")
    locked_count = sum(1 for a in apis if a.is_locked)

    return {
        "total_apis": len(apis),
        "active_apis": active_count,
        "locked_apis": locked_count,
        "total_calls": total_calls,
        "success_calls": success_calls,
        "error_calls": error_calls,
        "success_rate": (
            round(success_calls / total_calls * 100, 1) if total_calls > 0 else 0
        ),
        "top_apis": sorted(
            [{"id": a.id, "name": a.name, "path": a.path, "total_calls": a.total_calls}
             for a in apis],
            key=lambda x: x["total_calls"], reverse=True
        )[:5],
    }


# ── 策略管理 ──────────────────────────────────────────────────────────────────

@router.put("/apis/{api_id}/policy", response_model=ApiResponse)
async def update_api_policy(
    api_id: str,
    req: ApiPolicyRequest,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.ADMIN)),
):
    """更新限流 / 负载均衡 / 降级策略。"""
    api = await _get_api(session, api_id)
    if req.rate_limit_enabled is not None:
        api.rate_limit_enabled = req.rate_limit_enabled
    if req.rate_limit_per_minute is not None:
        api.rate_limit_per_minute = req.rate_limit_per_minute
    if req.load_balance_strategy is not None:
        api.load_balance_strategy = req.load_balance_strategy
    if req.degradation_enabled is not None:
        api.degradation_enabled = req.degradation_enabled
    if req.degradation_fallback is not None:
        api.degradation_fallback = req.degradation_fallback
    await session.commit()
    await session.refresh(api)
    return api


# ── 锁定管理 ──────────────────────────────────────────────────────────────────

@router.post("/apis/{api_id}/lock", response_model=ApiResponse)
async def lock_api(
    api_id: str,
    req: LockApiRequest,
    session: AsyncSession = Depends(get_session),
    login_id: str = Depends(require_role(Role.ADMIN)),
):
    """锁定接口：关联的 Block / Flow 变为只读（仅允许创建副本/新版本）。"""
    api = await _get_api(session, api_id)
    api.is_locked = True
    api.lock_reason = req.lock_reason or "管理员锁定"
    api.locked_by = login_id
    api.locked_at = datetime.now(timezone.utc).isoformat()
    await session.commit()
    await session.refresh(api)
    return api


@router.post("/apis/{api_id}/unlock", response_model=ApiResponse)
async def unlock_api(
    api_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.ADMIN)),
):
    """解锁接口：恢复关联 Block / Flow 的可编辑状态。"""
    api = await _get_api(session, api_id)
    api.is_locked = False
    api.lock_reason = None
    api.locked_by = None
    api.locked_at = None
    await session.commit()
    await session.refresh(api)
    return api


# ── 版本切换（平滑过渡） ───────────────────────────────────────────────────────

@router.post("/apis/{api_id}/switch-version", response_model=ApiResponse)
async def switch_api_version(
    api_id: str,
    req: SwitchVersionRequest,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.ADMIN)),
):
    """平滑过渡：将接口的实际调用流程切换到新版本 Flow，实现不停机升级。

    - 原 flow_id（发布时绑定的流程）保持不变（若已锁定则仍只读）。
    - active_flow_id 更新为新 Flow，后续所有调用走新版本。
    """
    api = await _get_api(session, api_id)

    new_flow = await session.get(Flow, req.new_flow_id)
    if new_flow is None:
        raise BusinessException(PYFLOW_API_NOT_FOUND, f"Flow {req.new_flow_id} 不存在")

    old_active = api.active_flow_id
    api.active_flow_id = req.new_flow_id
    await session.commit()
    await session.refresh(api)

    return api
