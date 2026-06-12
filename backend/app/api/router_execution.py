"""/api/exec — 执行历史与日志。"""

from __future__ import annotations

from datetime import timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import Role, require_role
from app.db import get_session
from app.models.api_portal import PublishedApi
from app.models.execution import ExecutionRecord, FlowRun
from app.models.flow import Flow

router = APIRouter(prefix="/api/exec", tags=["execution"])


@router.get("/records")
async def list_records(
    block_id: str | None = None,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    stmt = select(ExecutionRecord).order_by(ExecutionRecord.created_at.desc()).limit(min(limit, 200))
    if block_id:
        stmt = stmt.where(ExecutionRecord.block_id == block_id)
    rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id, "block_id": r.block_id, "status": r.status,
            "duration_ms": r.duration_ms, "created_at": r.created_at,
            "flow_run_id": r.flow_run_id,
        }
        for r in rows
    ]


@router.get("/records/{execution_id}")
async def get_record(
    execution_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    r = await session.get(ExecutionRecord, execution_id)
    if r is None:
        return {"error": "not found"}
    return {
        "id": r.id, "block_id": r.block_id, "status": r.status,
        "inputs": r.inputs, "output": r.output, "stdout": r.stdout,
        "stderr": r.stderr, "duration_ms": r.duration_ms,
    }


@router.get("/flow-runs")
async def list_flow_runs(
    flow_id: str | None = None,
    trigger_source: str | None = None,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    """整流执行历史列表，含触发源、流程名、接口名、耗时、节点进度。"""
    stmt = (
        select(
            FlowRun,
            Flow.name.label("flow_name"),
            PublishedApi.name.label("api_name"),
            PublishedApi.path.label("api_path"),
        )
        .outerjoin(Flow, FlowRun.flow_id == Flow.id)
        .outerjoin(PublishedApi, FlowRun.api_id == PublishedApi.id)
        .order_by(FlowRun.created_at.desc())
        .limit(min(limit, 200))
    )
    if flow_id:
        stmt = stmt.where(FlowRun.flow_id == flow_id)
    if trigger_source:
        stmt = stmt.where(FlowRun.trigger_source == trigger_source)

    rows = (await session.execute(stmt)).all()
    result = []
    for row in rows:
        r = row.FlowRun
        states = r.node_states or {}
        node_total = len(states)
        node_done = sum(
            1 for s in states.values()
            if isinstance(s, dict) and s.get("status") in ("done", "succeeded")
        )
        dur = r.duration_ms
        if dur is None and r.finished_at and r.created_at:
            fa = r.finished_at if r.finished_at.tzinfo else r.finished_at.replace(tzinfo=timezone.utc)
            ca = r.created_at if r.created_at.tzinfo else r.created_at.replace(tzinfo=timezone.utc)
            dur = int((fa - ca).total_seconds() * 1000)
        result.append({
            "id": r.id,
            "flow_id": r.flow_id,
            "flow_name": row.flow_name or "",
            "api_id": r.api_id,
            "api_name": row.api_name or "",
            "api_path": row.api_path or "",
            "trigger_source": r.trigger_source or "manual",
            "status": r.status,
            "node_total": node_total,
            "node_done": node_done,
            "duration_ms": dur,
            "created_at": r.created_at,
            "finished_at": r.finished_at,
        })
    return result
