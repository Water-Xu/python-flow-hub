"""/api/exec — 执行历史与日志。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import Role, require_role
from app.db import get_session
from app.models.execution import ExecutionRecord, FlowRun

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
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    stmt = select(FlowRun).order_by(FlowRun.created_at.desc()).limit(min(limit, 200))
    if flow_id:
        stmt = stmt.where(FlowRun.flow_id == flow_id)
    rows = (await session.execute(stmt)).scalars().all()
    return [
        {"id": r.id, "flow_id": r.flow_id, "status": r.status,
         "node_states": r.node_states, "created_at": r.created_at}
        for r in rows
    ]
