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


def _calc_dur(run: FlowRun) -> int | None:
    dur = run.duration_ms
    if dur is None and run.finished_at and run.created_at:
        fa = run.finished_at if run.finished_at.tzinfo else run.finished_at.replace(tzinfo=timezone.utc)
        ca = run.created_at if run.created_at.tzinfo else run.created_at.replace(tzinfo=timezone.utc)
        dur = int((fa - ca).total_seconds() * 1000)
    return dur


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
    """整流级别（FlowRun）成功率统计，与调用记录列表保持一致口径。"""
    rows = (await session.execute(
        select(FlowRun.status, func.count(), func.avg(FlowRun.duration_ms),
               func.max(FlowRun.duration_ms))
        .where(FlowRun.created_at >= since)
        .group_by(FlowRun.status)
    )).all()
    total = 0
    success = 0
    failed = 0
    durations: list[float] = []
    max_ms = 0
    for status, cnt, avg_ms, mx in rows:
        total += cnt
        if status == "succeeded":
            success += cnt
        elif status in ("failed", "canceled"):
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
    """最近 24h 按小时分桶，基于 FlowRun（整流粒度）。"""
    rows = (await session.execute(
        select(FlowRun.created_at, FlowRun.status)
        .where(FlowRun.created_at >= since)
        .order_by(FlowRun.created_at.desc())
        .limit(5000)
    )).all()
    buckets: dict[str, dict] = {}
    for created_at, status in rows:
        if created_at is None:
            continue
        ts = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
        key = ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:00")
        b = buckets.setdefault(key, {"hour": key, "total": 0, "success": 0, "failed": 0})
        b["total"] += 1
        if status == "succeeded":
            b["success"] += 1
        elif status in ("failed", "canceled"):
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


async def _recent_flow_runs(session: AsyncSession, limit: int = 20) -> list[dict]:
    rows = (await session.execute(
        select(FlowRun, Flow.name.label("flow_name"), PublishedApi.name.label("api_name"),
               PublishedApi.path.label("api_path"))
        .outerjoin(Flow, FlowRun.flow_id == Flow.id)
        .outerjoin(PublishedApi, FlowRun.api_id == PublishedApi.id)
        .order_by(FlowRun.created_at.desc())
        .limit(limit)
    )).all()
    out = []
    for row in rows:
        r = row.FlowRun
        states = r.node_states or {}
        done = sum(1 for s in states.values() if isinstance(s, dict) and s.get("status") in ("done", "succeeded"))
        skipped = sum(1 for s in states.values() if isinstance(s, dict) and s.get("status") == "skipped")
        dur = _calc_dur(r)
        out.append({
            "id": r.id, "flow_id": r.flow_id, "flow_name": row.flow_name or "",
            "flow_deployment_id": r.flow_deployment_id,
            "api_id": r.api_id, "api_name": row.api_name or "",
            "api_path": row.api_path or "",
            "trigger_source": r.trigger_source or "manual",
            "status": r.status, "node_total": len(states), "node_done": done,
            "node_skipped": skipped, "owner_pod": r.owner_pod,
            "duration_ms": dur,
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


def _get_node_name_from_dag(dag_snapshot: dict, node_id: str) -> str:
    """从 dag_snapshot 中提取节点显示名称。"""
    nodes = dag_snapshot.get("nodes", [])
    for node in nodes:
        if node.get("id") == node_id:
            data = node.get("data", {})
            # 按优先级取名：label > name > block_name > entrypoint > id[:8]
            return (
                data.get("label") or data.get("name") or
                data.get("block_name") or data.get("entrypoint") or
                node_id[:8]
            )
    return node_id[:8]


def _build_node_block_map(dag_snapshot: dict) -> dict[str, str]:
    """构建 node_id -> block_id 映射（用于关联 ExecutionRecord）。"""
    result = {}
    for node in dag_snapshot.get("nodes", []):
        block_id = node.get("data", {}).get("block_id")
        if block_id:
            result[node["id"]] = block_id
    return result


def _build_call_chain(
    trigger_src: str,
    run: FlowRun,
    api: PublishedApi | None,
    steps: list[dict],
    total_ms: int | None,
    executions: list[dict] | None = None,
) -> dict:
    """构建完整调用链路结构（基础设施节点 + 业务执行节点）。"""
    overall_ok = run.status in ("succeeded", "running")

    # 业务执行节点优先从 steps（node_states），fallback 到 executions 列表
    if steps:
        flow_nodes = [
            {
                "id": f"step_{step['node_id']}",
                "type": "block",
                "label": step.get("node_name") or step["node_id"][:8],
                "node_id": step["node_id"],
                "block_id": step.get("block_id"),
                "status": step["status"],
                "duration_ms": step.get("duration_ms"),
                "hit_port": step.get("hit_port"),
                "error": step.get("error"),
                "has_output": step.get("has_output", False),
            }
            for step in steps
        ]
    elif executions:
        # node_states 为空时（如块模式执行未回写 state）从 ExecutionRecord 重建
        flow_nodes = [
            {
                "id": f"exec_{ex['id'][:8]}",
                "type": "block",
                "label": ex.get("block_name") or ex["block_id"][:8],
                "block_id": ex.get("block_id"),
                "status": "done" if ex["status"] in ("success", "succeeded") else ex["status"],
                "duration_ms": ex.get("duration_ms"),
                "error": ex.get("stderr") or None,
                "has_output": bool(ex.get("output")),
            }
            for ex in executions
        ]
    else:
        flow_nodes = []

    # Flow 编排包装节点
    orchestrator_node = {
        "id": "orchestrator",
        "type": "orchestrator",
        "label": "Flow 编排",
        "detail": f"flow_run {run.id[:8]}",
        "status": "done" if overall_ok else "failed",
        "duration_ms": total_ms,
        "children": flow_nodes,
    }

    if trigger_src == "http":
        nodes = [
            {"id": "client", "type": "client", "label": "调用客户端",
             "status": "ok", "detail": "HTTP 请求方"},
            {"id": "network", "type": "network", "label": "网络传输",
             "status": "ok", "detail": "TCP / TLS 握手"},
            {"id": "gateway", "type": "gateway", "label": "API 网关",
             "status": "ok", "detail": "路由 & 负载均衡"},
            {"id": "portal", "type": "service", "label": "API Portal",
             "status": "ok" if overall_ok else "error",
             "detail": f"POST /api/public/{api.path if api else '?'}",
             "sub": api.name if api else ""},
            {"id": "auth", "type": "auth", "label": "鉴权 & 限流",
             "status": "ok", "detail": "Token 校验 / 频率限制"},
            orchestrator_node,
            {"id": "response", "type": "response", "label": "HTTP 响应",
             "status": "ok" if overall_ok else "error",
             "detail": "200 OK" if overall_ok else "执行失败",
             "duration_ms": total_ms},
        ]
    elif trigger_src == "stream":
        nodes = [
            {"id": "client", "type": "client", "label": "调用客户端",
             "status": "ok", "detail": "HTTP SSE 请求"},
            {"id": "gateway", "type": "gateway", "label": "API 网关",
             "status": "ok", "detail": "路由 & 长连接保持"},
            {"id": "portal", "type": "service", "label": "API Portal (Stream)",
             "status": "ok" if overall_ok else "error",
             "detail": f"POST /api/public/{api.path if api else '?'}/stream",
             "sub": api.name if api else ""},
            {"id": "auth", "type": "auth", "label": "鉴权 & 限流",
             "status": "ok", "detail": "Token 校验"},
            orchestrator_node,
            {"id": "sse", "type": "response", "label": "SSE 流式推送",
             "status": "ok" if overall_ok else "error",
             "detail": "text/event-stream", "duration_ms": total_ms},
        ]
    elif trigger_src == "mq":
        mq_cfg = (api.mq_config or {}) if api else {}
        api_short = (run.api_id or "?")[:8]
        exchange = mq_cfg.get("exchange", f"flow.{api_short}")
        routing_key = mq_cfg.get("routing_key", "")
        queue_name = mq_cfg.get("queue", f"flow.{api_short}.queue")
        nodes = [
            {"id": "publisher", "type": "client", "label": "消息发布者",
             "status": "ok", "detail": "AMQP publish"},
            {"id": "broker", "type": "mq_broker", "label": "RabbitMQ Broker",
             "status": "ok", "detail": "消息代理 (AMQP 0-9-1)"},
            {"id": "exchange", "type": "mq_exchange", "label": "Exchange",
             "status": "ok", "detail": exchange, "sub": "topic 类型"},
            {"id": "route", "type": "mq_route", "label": "路由绑定",
             "status": "ok", "detail": routing_key or "#"},
            {"id": "queue", "type": "mq_queue", "label": "消息队列",
             "status": "ok", "detail": queue_name},
            {"id": "consumer", "type": "service", "label": "Flow Consumer",
             "status": "ok", "detail": "消息消费 & 反序列化"},
            {"id": "idempotent", "type": "filter", "label": "幂等校验",
             "status": "ok", "detail": "Redis 去重 (message_id)"},
            orchestrator_node,
            {"id": "ack", "type": "response", "label": "消息确认",
             "status": "ok" if overall_ok else "nack",
             "detail": "basic.ack" if overall_ok else "basic.nack (重入队列)"},
        ]
    else:
        # manual
        nodes = [
            {"id": "user", "type": "client", "label": "用户 / Flow Editor",
             "status": "ok", "detail": "手动触发执行"},
            {"id": "api", "type": "service", "label": "控制面 API",
             "status": "ok", "detail": "POST /api/flows/{id}/run"},
            orchestrator_node,
            {"id": "result", "type": "response", "label": "执行结果",
             "status": "ok" if overall_ok else "error", "duration_ms": total_ms},
        ]

    return {
        "type": trigger_src,
        "nodes": nodes,
        "total_ms": total_ms,
        "status": run.status,
    }


@router.get("/flow-runs/{run_id}/trace")
async def flow_run_trace(
    run_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    """单次整流链路 trace：含节点名称、每步耗时、触发源、流程入参出参、完整 call_chain 结构。"""
    run = await session.get(FlowRun, run_id)
    if run is None:
        raise BusinessException(PYFLOW_FLOW_NOT_FOUND, run_id)

    flow = await session.get(Flow, run.flow_id) if run.flow_id else None
    api = await session.get(PublishedApi, run.api_id) if run.api_id else None

    # 从 dag_snapshot 提取节点名称 和 node_id -> block_id 映射
    dag = run.dag_snapshot or {}
    node_block_map = _build_node_block_map(dag)

    states = run.node_states or {}

    # 查询关联块执行，按时间排序
    recs = (await session.execute(
        select(ExecutionRecord, Block.name.label("block_name"))
        .outerjoin(Block, ExecutionRecord.block_id == Block.id)
        .where(ExecutionRecord.flow_run_id == run_id)
        .order_by(ExecutionRecord.created_at)
    )).all()

    # block_id -> [ExecutionRecord, ...] 映射（按创建时间顺序，供逐一匹配）
    exec_by_block: dict[str, list] = {}
    for r in recs:
        bid = r.ExecutionRecord.block_id
        exec_by_block.setdefault(bid, []).append(r)

    # 构建 steps（含 node_name、duration_ms）
    steps = []
    for node_id, st in states.items():
        if not isinstance(st, dict):
            continue
        node_name = _get_node_name_from_dag(dag, node_id)
        block_id = node_block_map.get(node_id)

        # 按顺序取同一 block 的第一条 execution（匹配本次节点执行）
        exec_dur: int | None = None
        exec_started_at = None
        exec_status_ok = True
        if block_id and block_id in exec_by_block and exec_by_block[block_id]:
            ex_row = exec_by_block[block_id].pop(0)
            ex = ex_row.ExecutionRecord
            exec_dur = ex.duration_ms
            exec_started_at = ex.created_at
            exec_status_ok = ex.status in ("success", "done")

        steps.append({
            "node_id": node_id,
            "node_name": node_name,
            "block_id": block_id,
            "status": st.get("status", "unknown"),
            "hit_port": st.get("hit_port"),
            "has_output": "output" in st,
            "output": st.get("output"),
            "error": st.get("error"),
            "duration_ms": exec_dur,
            "started_at": exec_started_at.isoformat() if exec_started_at else None,
        })

    # 流级别入参 / 出参
    flow_inputs: dict | None = None
    flow_output: dict | None = None
    if recs:
        # 取第一条有非空 inputs 的记录
        for r in recs:
            v = r.ExecutionRecord.inputs
            if v and isinstance(v, dict) and v:
                flow_inputs = v
                break
        # 取最后一条有非空 output 的记录
        for r in reversed(recs):
            v = r.ExecutionRecord.output
            if v and isinstance(v, dict) and v:
                flow_output = v
                break

    total_ms = _calc_dur(run)
    trigger_src = run.trigger_source or "manual"

    # executions 列表（供 call_chain 降级使用）
    exec_list = [
        {
            "id": r.ExecutionRecord.id,
            "block_id": r.ExecutionRecord.block_id,
            "block_name": r.block_name or "",
            "status": r.ExecutionRecord.status,
            "duration_ms": r.ExecutionRecord.duration_ms,
            "stderr": r.ExecutionRecord.stderr or "",
            "output": r.ExecutionRecord.output,
        }
        for r in recs
    ]
    call_chain = _build_call_chain(trigger_src, run, api, steps, total_ms, exec_list)

    return {
        "run": {
            "id": run.id,
            "flow_id": run.flow_id,
            "flow_name": flow.name if flow else "",
            "api_id": run.api_id,
            "api_name": api.name if api else "",
            "api_path": api.path if api else "",
            "trigger_source": trigger_src,
            "status": run.status,
            "owner_pod": run.owner_pod,
            "fence_token": run.fence_token,
            "duration_ms": total_ms,
            "created_at": run.created_at,
            "finished_at": run.finished_at,
            "inputs": flow_inputs,
            "output": flow_output,
        },
        "steps": steps,
        "executions": [
            {
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
            }
            for r in recs
        ],
        "call_chain": call_chain,
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
            dag = run.dag_snapshot or {}
            states = run.node_states or {}
            steps = [
                {
                    "node_id": node_id,
                    "node_name": _get_node_name_from_dag(dag, node_id),
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
                "trigger_source": run.trigger_source or "manual",
                "status": run.status,
                "steps": steps,
                "duration_ms": _calc_dur(run),
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
