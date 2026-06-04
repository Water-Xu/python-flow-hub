"""/api/portal — 用户接口：发布流程为 HTTP 接口 + 查看自己的接口 + 调用接口。

调用路径：POST /api/public/{path}
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import Role, require_role
from app.config import get_settings
from app.core.execution_service import execute_block
from app.core.flow.flow_runner import run_flow
from app.core.mq.invocation_doc import build_mq_invocation
from app.db import get_session
from app.errors import (
    PYFLOW_API_LOCKED,
    PYFLOW_API_NOT_FOUND,
    PYFLOW_API_PATH_EXISTS,
    PYFLOW_API_RATE_LIMITED,
    PYFLOW_BLOCK_NOT_FOUND,
    PYFLOW_EXEC_SANDBOX_ERROR,
    BusinessException,
)
from app.core.mq.validation import validate_mq_config
from app.models.api_portal import PublishedApi
from app.models.block import Block
from app.models.flow import Flow, FlowEdge, FlowNode
from app.schemas.api_portal import ApiMqConfigRequest, ApiResponse, PublishApiRequest

router = APIRouter(tags=["api-portal"])
settings = get_settings()

# 内存限流计数器：{api_id: deque[timestamp]}（dev local；生产用 Redis）
_rate_counters: dict[str, deque[float]] = defaultdict(deque)


def _check_rate_limit(api: PublishedApi) -> None:
    """滑动窗口限流（60 秒）。dev 模式；生产使用 Redis。

    用 deque 仅从左端弹出过期时间戳（O(过期数)），避免每次请求重建整个列表。
    """
    if not api.rate_limit_enabled:
        return
    now = time.time()
    cutoff = now - 60.0
    window = _rate_counters[api.id]
    while window and window[0] <= cutoff:
        window.popleft()
    if len(window) >= api.rate_limit_per_minute:
        raise BusinessException(PYFLOW_API_RATE_LIMITED, f"限流 {api.rate_limit_per_minute} req/min")
    window.append(now)


async def _get_api(session: AsyncSession, api_id: str) -> PublishedApi:
    api = await session.get(PublishedApi, api_id)
    if api is None:
        raise BusinessException(PYFLOW_API_NOT_FOUND, api_id)
    return api


async def _get_api_by_path(session: AsyncSession, path: str) -> PublishedApi:
    result = await session.execute(
        select(PublishedApi).where(PublishedApi.path == path)
    )
    api = result.scalar_one_or_none()
    if api is None:
        raise BusinessException(PYFLOW_API_NOT_FOUND, path)
    return api


# ── 用户接口管理 ──────────────────────────────────────────────────────────────

@router.get("/api/portal/apis", response_model=list[ApiResponse])
async def list_my_apis(
    session: AsyncSession = Depends(get_session),
    login_id: str = Depends(require_role(Role.VIEWER)),
):
    """列出我发布的所有接口。"""
    rows = (await session.execute(
        select(PublishedApi)
        .where(PublishedApi.owner_login_id == login_id)
        .order_by(PublishedApi.created_at.desc())
    )).scalars().all()
    return rows


@router.post("/api/portal/apis", response_model=ApiResponse)
async def publish_flow_as_api(
    req: PublishApiRequest,
    session: AsyncSession = Depends(get_session),
    login_id: str = Depends(require_role(Role.EDITOR)),
):
    """将一个流程发布为接口（接口路径唯一）。"""
    # 校验流程存在
    flow = await session.get(Flow, req.flow_id)
    if flow is None:
        raise BusinessException(PYFLOW_BLOCK_NOT_FOUND, req.flow_id)

    # 校验路径唯一
    existing = (await session.execute(
        select(PublishedApi).where(PublishedApi.path == req.path)
    )).scalar_one_or_none()
    if existing is not None:
        raise BusinessException(PYFLOW_API_PATH_EXISTS, req.path)

    api = PublishedApi(
        name=req.name,
        description=req.description,
        path=req.path,
        tags=req.tags,
        flow_id=req.flow_id,
        active_flow_id=req.flow_id,
        owner_login_id=login_id,
        status="active",
    )
    session.add(api)
    await session.commit()
    await session.refresh(api)
    return api


@router.get("/api/portal/apis/{api_id}", response_model=ApiResponse)
async def get_my_api(
    api_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    return await _get_api(session, api_id)


@router.delete("/api/portal/apis/{api_id}")
async def unpublish_api(
    api_id: str,
    session: AsyncSession = Depends(get_session),
    login_id: str = Depends(require_role(Role.EDITOR)),
):
    """下线接口（如已锁定则拒绝）。"""
    api = await _get_api(session, api_id)
    if api.is_locked:
        raise BusinessException(PYFLOW_API_LOCKED, f"接口 {api.name} 已被管理员锁定，无法下线")
    await session.delete(api)
    await session.commit()
    return {"deleted": api_id}


@router.post("/api/portal/apis/{api_id}/pause")
async def pause_api(
    api_id: str,
    session: AsyncSession = Depends(get_session),
    login_id: str = Depends(require_role(Role.EDITOR)),
):
    api = await _get_api(session, api_id)
    if api.is_locked:
        raise BusinessException(PYFLOW_API_LOCKED, "接口已锁定")
    api.status = "paused"
    await session.commit()
    return {"status": "paused"}


@router.post("/api/portal/apis/{api_id}/activate")
async def activate_api(
    api_id: str,
    session: AsyncSession = Depends(get_session),
    login_id: str = Depends(require_role(Role.EDITOR)),
):
    api = await _get_api(session, api_id)
    api.status = "active"
    await session.commit()
    return {"status": "active"}


@router.put("/api/portal/apis/{api_id}/mq", response_model=ApiResponse)
async def update_api_mq_config(
    api_id: str,
    req: ApiMqConfigRequest,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.EDITOR)),
):
    """配置接口触发方式（http/mq/both）与 MQ 触发参数（队列/条件/映射/回复/重试）。

    MQ 触发已上移到接口/Flow 级（决策 3.1 重写为 Flow 级模型 A）：
    消费者按 flow.{api_id}.queue 消费，收到消息驱动整条 Flow 编排。
    """
    api = await _get_api(session, api_id)
    if api.is_locked:
        raise BusinessException(PYFLOW_API_LOCKED, f"接口 {api.name} 已锁定，无法修改触发配置")
    # 服务端校验（决策 1/6/10）：非法配置拦在运行期之外
    validate_mq_config(req.mq_config, req.trigger_type)
    api.trigger_type = req.trigger_type
    api.mq_config = req.mq_config if req.trigger_type in ("mq", "both") else {}
    await session.commit()
    await session.refresh(api)
    return api


@router.get("/api/portal/apis/{api_id}/docs")
async def get_api_docs(
    api_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    """生成接口文档（从关联流程和块自动提取端口信息）。"""
    api = await _get_api(session, api_id)
    flow_id = api.active_flow_id or api.flow_id
    flow = await session.get(Flow, flow_id)

    nodes = (await session.execute(
        select(FlowNode).where(FlowNode.flow_id == flow_id)
    )).scalars().all()
    edges = (await session.execute(
        select(FlowEdge).where(FlowEdge.flow_id == flow_id)
    )).scalars().all()

    # 收集所有块的端口信息作为文档
    block_docs = []
    for node in nodes:
        if node.block_id:
            block = await session.get(Block, node.block_id)
            if block:
                block_docs.append({
                    "node_id": node.id,
                    "block_id": block.id,
                    "block_name": block.name,
                    "description": block.description,
                    "input_ports": block.input_ports,
                    "output_ports": block.output_ports,
                    "entrypoints": block.entrypoints,
                    # 该节点实际调用的入口函数（默认 run）
                    "entrypoint": (node.config or {}).get("entrypoint") or "run",
                })

    # 接口级 MQ 触发文档（trigger_type 为 mq/both 时非空），用流程入口块端口生成示例消息体
    entry_ports = _entry_input_ports(nodes, edges, block_docs)
    mq_invocation = build_mq_invocation(api, entry_ports)

    return {
        "api_id": api_id,
        "name": api.name,
        "description": api.description,
        "path": f"{settings.public_api_prefix}/api/public/{api.path}",
        "method": "POST",
        "status": api.status,
        "trigger_type": api.trigger_type,
        "flow_id": flow_id,
        "flow_name": flow.name if flow else "未知",
        "node_count": len(nodes),
        "edge_count": len(edges),
        "blocks": block_docs,
        "request_example": {"inputs": {}},
        "response_example": {"outputs": {}, "flow_run_id": "uuid", "status": "succeeded"},
        # ── MQ 触发支持（接口级）──
        "mq_supported": mq_invocation is not None,
        "mq_invocation": mq_invocation,
    }


def _entry_input_ports(
    nodes: list[Any], edges: list[Any], block_docs: list[dict[str, Any]]
) -> list[Any]:
    """流程入口块（无入边的块节点）的 input_ports 合集，用于生成 MQ 示例消息体。"""
    targets = {e.target_node_id for e in edges}
    entry_block_ids = {
        n.block_id for n in nodes if n.block_id and n.id not in targets
    }
    ports: list[Any] = []
    for doc in block_docs:
        if doc["block_id"] in entry_block_ids:
            ports.extend(doc.get("input_ports") or [])
    return ports


# ── 公开调用入口 ───────────────────────────────────────────────────────────────

@router.post("/api/public/{path}")
async def invoke_api(
    path: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """公开调用接口（无需登录态校验；限流 + 降级在此处理）。"""
    api = await _get_api_by_path(session, path)

    if api.status != "active":
        raise BusinessException(PYFLOW_API_NOT_FOUND, f"接口 {path} 当前状态为 {api.status}")

    # 降级：返回 fallback
    if api.degradation_enabled and api.degradation_fallback:
        api.total_calls += 1
        api.success_calls += 1
        await session.commit()
        return {"degraded": True, "data": api.degradation_fallback}

    # 限流检查
    _check_rate_limit(api)

    body: dict[str, Any] = {}
    try:
        body = await request.json()
    except Exception:
        pass
    inputs = body.get("inputs", {})

    flow_id = api.active_flow_id or api.flow_id
    nodes_rows = (await session.execute(
        select(FlowNode).where(FlowNode.flow_id == flow_id)
    )).scalars().all()
    edges_rows = (await session.execute(
        select(FlowEdge).where(FlowEdge.flow_id == flow_id)
    )).scalars().all()

    nodes = [
        {"id": n.id, "node_type": n.node_type, "block_id": n.block_id,
         "config": n.config, "position": n.position}
        for n in nodes_rows
    ]
    edges = [
        {"id": e.id, "source_node_id": e.source_node_id,
         "target_node_id": e.target_node_id,
         "source_port": e.source_port, "target_port": e.target_port}
        for e in edges_rows
    ]

    # 一次 IN 查询批量装载所有块，避免按节点 N+1 逐个 session.get
    block_ids = {n["block_id"] for n in nodes if n.get("block_id")}
    block_cache: dict[str, Block] = {}
    if block_ids:
        rows = (await session.execute(
            select(Block).where(Block.id.in_(block_ids))
        )).scalars().all()
        block_cache = {b.id: b for b in rows}
        missing = block_ids - block_cache.keys()
        if missing:
            raise BusinessException(PYFLOW_BLOCK_NOT_FOUND, next(iter(missing)))

    start_ts = time.time()
    try:
        async def node_executor(node: dict, node_inputs: dict) -> dict:
            block_id = node.get("block_id")
            if not block_id:
                return {}
            block = block_cache[block_id]
            entrypoint = (node.get("config") or {}).get("entrypoint") or "run"
            record = await execute_block(
                session, block_id=block.id, code=block.draft_code or "",
                inputs=node_inputs, login_id=api.owner_login_id,
                entrypoint=entrypoint,
            )
            if record.status != "success":
                detail = (record.stderr or "block execution failed").strip()[:500]
                raise BusinessException(PYFLOW_EXEC_SANDBOX_ERROR, detail)
            return record.output if isinstance(record.output, dict) else {"value": record.output}

        async def checkpoint(node_id: str, status: str, output: dict) -> None:
            pass

        outputs = await run_flow(nodes, edges, inputs, node_executor, checkpoint)
        elapsed = (time.time() - start_ts) * 1000

        api.total_calls += 1
        api.success_calls += 1
        # 滚动平均
        n = api.total_calls
        api.avg_latency_ms = (api.avg_latency_ms * (n - 1) + elapsed) / n
        await session.commit()

        return {"outputs": outputs, "status": "succeeded", "latency_ms": round(elapsed, 2)}

    except BusinessException:
        api.total_calls += 1
        api.error_calls += 1
        await session.commit()
        raise
    except Exception as exc:
        api.total_calls += 1
        api.error_calls += 1
        await session.commit()
        raise BusinessException(PYFLOW_EXEC_SANDBOX_ERROR, str(exc)[:500]) from exc


