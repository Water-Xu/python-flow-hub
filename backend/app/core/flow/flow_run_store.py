"""FlowRun 多副本续跑：lease + fence_token（决策 7/10，Phase 4a）。

控制面多副本时，同一 FlowRun 只能被一个副本驱动。用 DB 行级 CAS 实现：
- claim：owner 为空或 lease 过期时抢占，fence_token 单调递增；
- renew：心跳续租，CAS 校验 fence_token + owner，被接管则失败；
- resume：扫描 status=running 且 lease 过期的 run，从最后完成节点下游续跑。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import FlowRun
from app.observability.logging import get_logger

logger = get_logger("pyflow.flow.run")

LEASE_TTL_SECONDS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def claim_run(
    session: AsyncSession, run_id: str, pod_name: str, *, lease_ttl: int = LEASE_TTL_SECONDS
) -> int | None:
    """抢占/接管 FlowRun，成功返回新的 fence_token，失败返回 None。

    条件：owner 为空 或 lease 已过期。fence_token 单调递增（决策 7）。
    """
    run = await session.get(FlowRun, run_id)
    if run is None or run.status != "running":
        return None
    now = _now()
    expired = run.lease_expire_at is None or _as_utc(run.lease_expire_at) <= now
    if run.owner_pod and run.owner_pod != pod_name and not expired:
        return None

    new_fence = (run.fence_token or 0) + 1
    new_expire = now + timedelta(seconds=lease_ttl)
    result = await session.execute(
        update(FlowRun)
        .where(FlowRun.id == run_id, FlowRun.fence_token == (run.fence_token or 0))
        .values(owner_pod=pod_name, fence_token=new_fence, lease_expire_at=new_expire)
    )
    await session.commit()
    if result.rowcount != 1:
        return None  # 并发被他人抢占
    logger.info("flow_run_claimed", run_id=run_id, pod=pod_name, fence=new_fence)
    return new_fence


async def renew_lease(
    session: AsyncSession, run_id: str, pod_name: str, fence_token: int,
    *, lease_ttl: int = LEASE_TTL_SECONDS,
) -> bool:
    """心跳续租：CAS 校验 fence_token + owner，被接管即失败（决策 7）。"""
    new_expire = _now() + timedelta(seconds=lease_ttl)
    result = await session.execute(
        update(FlowRun)
        .where(
            FlowRun.id == run_id,
            FlowRun.fence_token == fence_token,
            FlowRun.owner_pod == pod_name,
        )
        .values(lease_expire_at=new_expire)
    )
    await session.commit()
    return result.rowcount == 1


async def release_lease(session: AsyncSession, run_id: str, pod_name: str, fence_token: int) -> None:
    """优雅停机：释放 lease 让其他副本可接管。"""
    await session.execute(
        update(FlowRun)
        .where(
            FlowRun.id == run_id,
            FlowRun.fence_token == fence_token,
            FlowRun.owner_pod == pod_name,
        )
        .values(lease_expire_at=_now())
    )
    await session.commit()


async def scan_resumable(session: AsyncSession, limit: int = 20) -> list[FlowRun]:
    """扫描可续跑的 FlowRun（status=running 且 lease 过期）。"""
    now = _now()
    rows = (await session.execute(
        select(FlowRun)
        .where(FlowRun.status == "running")
        .order_by(FlowRun.created_at)
        .limit(limit)
    )).scalars().all()
    return [r for r in rows if r.lease_expire_at is None or _as_utc(r.lease_expire_at) <= now]


def completed_nodes(run: FlowRun) -> set[str]:
    """从 node_states 中提取已完成（done/skipped）节点，续跑时不重跑。"""
    return {
        nid for nid, st in (run.node_states or {}).items()
        if isinstance(st, dict) and st.get("status") in ("done", "skipped")
    }


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
