"""/api/dashboard — Python 链路监控看板。

汇聚控制面运行态：资源计数、最近 24h 执行成功率/耗时趋势、最近整流（Flow）链路与单块执行、
依赖连通性。作为轻量 Python 调用链路监控面板（决策 13）。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import Role, require_role
from app.db import get_session
from app.errors import PYFLOW_FLOW_NOT_FOUND, BusinessException
from app.models.api_portal import PublishedApi
from app.models.block import Block
from app.models.deployment import FlowDeployment
from app.models.execution import ExecutionRecord, FlowRun
from app.models.flow import Flow

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _counts(session: AsyncSession) -> dict:
    blocks = (await session.execute(select(func.count()).select_from(Block))).scalar() or 0
    flows = (await session.execute(select(func.count()).select_from(Flow))).scalar() or 0
    apis = (await session.execute(select(func.count()).select_from(PublishedApi))).scalar() or 0
    mq_apis = (await session.execute(
        select(func.count()).select_from(PublishedApi).where(
            PublishedApi.trigger_type.in_(["mq", "both"])
        )
    )).scalar() or 0

    dep_rows = (await session.execute(
        select(FlowDeployment.status, func.count()).group_by(FlowDeployment.status)
    )).all()
    dep_status = {status: cnt for status, cnt in dep_rows}
    return {
        "blocks": blocks,
        "flows": flows,
        "apis": apis,
        "mq_apis": mq_apis,
        "deployments_total": sum(dep_status.values()),
        "deployments_by_status": dep_status,
        "deployments_running": dep_status.get("running", 0),
    }


async def _exec_stats(session: AsyncSession, since: datetime) -> dict:
    rows = (await session.execute(
        select(ExecutionRecord.status, func.count(), func.avg(ExecutionRecord.duration_ms),
               func.max(ExecutionRecord.duration_ms))
        .where(ExecutionRecord.created_at >= since)
        .group_by(ExecutionRecord.status)
    )).all()
    total = 0
    success = 0
    failed = 0
    durations: list[float] = []
    max_ms = 0
    for status, cnt, avg_ms, mx in rows:
        total += cnt
        if status == "success":
            success += cnt
        elif status in ("failed", "timeout"):
            failed += cnt
        if avg_ms is not None:
            durations.append(float(avg_ms) * cnt)
        if mx is not None:
            max_ms = max(max_ms, int(mx))
    avg_duration = int(sum(durations) / total) if total else 0
    success_rate = round(success / total * 100, 1) if total else 100.0
    return {
        "total": total,
        "success": success,
        "failed": failed,
        "success_rate": success_rate,
        "avg_duration_ms": avg_duration,
        "max_duration_ms": max_ms,
    }


async def _exec_trend(session: AsyncSession, since: datetime) -> list[dict]:
    """最近 24h 按小时分桶（执行总数 / 失败数）。"""
    rows = (await session.execute(
        select(ExecutionRecord.created_at, ExecutionRecord.status)
        .where(ExecutionRecord.created_at >= since)
        .order_by(ExecutionRecord.created_at.desc())
        .limit(5000)
    )).all()
    buckets: dict[str, dict] = {}
    for created_at, status in rows:
        if created_at is None:
            continue
        ts = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
        key = ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:00")
        b = buckets.setdefault(key, {"hour": key, "total": 0, "failed": 0})
        b["total"] += 1
        if status in ("failed", "timeout"):
            b["failed"] += 1
    return [buckets[k] for k in sorted(buckets.keys())]


async def _recent_executions(session: AsyncSession, limit: int = 15) -> list[dict]:
    rows = (await session.execute(
        select(ExecutionRecord, Block.name.label("block_name"))
        .outerjoin(Block, ExecutionRecord.block_id == Block.id)
        .order_by(ExecutionRecord.created_at.desc())
        .limit(limit)
    )).all()
    return [{
        "id": r.ExecutionRecord.id,
        "block_id": r.ExecutionRecord.block_id,
        "block_name": r.block_name or "",
        "flow_run_id": r.ExecutionRecord.flow_run_id,
        "status": r.ExecutionRecord.status,
        "duration_ms": r.ExecutionRecord.duration_ms,
        "error_code": r.ExecutionRecord.error_code,
        "login_id": r.ExecutionRecord.login_id,
        "created_at": r.ExecutionRecord.created_at,
    } for r in rows]


async def _recent_flow_runs(session: AsyncSession, limit: int = 12) -> list[dict]:
    rows = (await session.execute(
        select(FlowRun, Flow.name.label("flow_name"))
        .outerjoin(Flow, FlowRun.flow_id == Flow.id)
        .order_by(FlowRun.created_at.desc())
        .limit(limit)
    )).all()
    out = []
    for row in rows:
        r = row.FlowRun
        states = r.node_states or {}
        done = sum(1 for s in states.values() if isinstance(s, dict) and s.get("status") == "done")
        skipped = sum(1 for s in states.values() if isinstance(s, dict) and s.get("status") == "skipped")
        out.append({
            "id": r.id, "flow_id": r.flow_id, "flow_name": row.flow_name or "",
            "flow_deployment_id": r.flow_deployment_id,
            "status": r.status, "node_total": len(states), "node_done": done,
            "node_skipped": skipped, "owner_pod": r.owner_pod,
            "created_at": r.created_at, "finished_at": r.finished_at,
        })
    return out


@router.get("/overview")
async def overview(
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    """看板总览：计数 + 24h 执行统计/趋势 + 最近链路/执行 + 依赖连通性。"""
    since = _utcnow() - timedelta(hours=24)
    counts, stats, trend, recent_exec, recent_runs = await asyncio.gather(
        _counts(session),
        _exec_stats(session, since),
        _exec_trend(session, since),
        _recent_executions(session),
        _recent_flow_runs(session),
    )
    deps = await _probe_deps()
    return {
        "counts": counts,
        "exec_stats": stats,
        "exec_trend": trend,
        "recent_executions": recent_exec,
        "recent_flow_runs": recent_runs,
        "deps": deps,
        "generated_at": _utcnow().isoformat(),
    }


@router.get("/flow-runs/{run_id}/trace")
async def flow_run_trace(
    run_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    """单次整流链路 trace：按节点状态还原执行步骤（成功/跳过/失败 + 输出），含块名称与完整日志。"""
    run = await session.get(FlowRun, run_id)
    if run is None:
        raise BusinessException(PYFLOW_FLOW_NOT_FOUND, run_id)
    flow = await session.get(Flow, run.flow_id) if run.flow_id else None
    states = run.node_states or {}
    steps = []
    for node_id, st in states.items():
        if not isinstance(st, dict):
            continue
        steps.append({
            "node_id": node_id,
            "status": st.get("status", "unknown"),
            "hit_port": st.get("hit_port"),
            "has_output": "output" in st,
            "output": st.get("output"),
            "error": st.get("error"),
        })
    # 单块执行明细（关联 flow_run_id），含块名称与完整 stdout/stderr
    recs = (await session.execute(
        select(ExecutionRecord, Block.name.label("block_name"))
        .outerjoin(Block, ExecutionRecord.block_id == Block.id)
        .where(ExecutionRecord.flow_run_id == run_id)
        .order_by(ExecutionRecord.created_at)
    )).all()
    return {
        "run": {
            "id": run.id, "flow_id": run.flow_id, "flow_name": flow.name if flow else "",
            "status": run.status, "owner_pod": run.owner_pod,
            "fence_token": run.fence_token,
            "created_at": run.created_at, "finished_at": run.finished_at,
        },
        "steps": steps,
        "executions": [{
            "id": r.ExecutionRecord.id,
            "block_id": r.ExecutionRecord.block_id,
            "block_name": r.block_name or "",
            "status": r.ExecutionRecord.status,
            "duration_ms": r.ExecutionRecord.duration_ms,
            "inputs": r.ExecutionRecord.inputs,
            "output": r.ExecutionRecord.output,
            "stdout": r.ExecutionRecord.stdout or "",
            "stderr": r.ExecutionRecord.stderr or "",
            "created_at": r.ExecutionRecord.created_at,
        } for r in recs],
    }


@router.get("/exec/{execution_id}")
async def exec_detail(
    execution_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    """单次执行详情：入参、出参、完整 stdout/stderr；若关联整流则附加链路 trace。"""
    r = await session.get(ExecutionRecord, execution_id)
    if r is None:
        raise BusinessException(PYFLOW_FLOW_NOT_FOUND, execution_id)
    block = await session.get(Block, r.block_id) if r.block_id else None
    result: dict = {
        "id": r.id,
        "block_id": r.block_id,
        "block_name": block.name if block else "",
        "status": r.status,
        "duration_ms": r.duration_ms,
        "error_code": r.error_code,
        "login_id": r.login_id,
        "inputs": r.inputs,
        "output": r.output,
        "stdout": r.stdout or "",
        "stderr": r.stderr or "",
        "created_at": r.created_at,
        "flow_run_id": r.flow_run_id,
        "flow_run": None,
    }
    if r.flow_run_id:
        run = await session.get(FlowRun, r.flow_run_id)
        if run:
            flow = await session.get(Flow, run.flow_id) if run.flow_id else None
            states = run.node_states or {}
            steps = [
                {
                    "node_id": node_id,
                    "status": st.get("status", "unknown"),
                    "hit_port": st.get("hit_port"),
                    "has_output": "output" in st,
                    "output": st.get("output"),
                    "error": st.get("error"),
                }
                for node_id, st in states.items()
                if isinstance(st, dict)
            ]
            result["flow_run"] = {
                "id": run.id,
                "flow_id": run.flow_id,
                "flow_name": flow.name if flow else "",
                "status": run.status,
                "steps": steps,
                "created_at": run.created_at,
                "finished_at": run.finished_at,
            }
    return result


async def _probe_deps() -> dict:
    """复用 health 探测（连通性诊断，失败不抛错）。"""
    from app.api.router_health import _check_minio, _check_postgres, _check_rabbitmq, _check_redis

    try:
        pg, redis_ok, mq_ok, minio_ok = await asyncio.gather(
            _check_postgres(), _check_redis(), _check_rabbitmq(), _check_minio(),
        )
    except Exception:  # noqa: BLE001
        return {}
    return {
        "postgres": "up" if pg else "down",
        "redis": "up" if redis_ok else "down",
        "rabbitmq": "up" if mq_ok else "down",
        "minio": "up" if minio_ok else "down",
    }
