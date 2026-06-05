"""K8s 同步编排（决策 10，Phase 4a）。

flow_runner 按 DAG 拓扑序依次调用各 Block 的 K8s Service /invoke，内存传递 output→input；
FlowRun 用 lease+fence 防双副本同时驱动，心跳续租；控制面重启/被驱逐后从最后完成节点下游续跑。
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.flow import flow_run_store
from app.core.flow.flow_runner import run_flow
from app.core.k8s.manifest_generator import BlockDeploySpec, DeployContext, deployment_name
from app.errors import PYFLOW_EXEC_SANDBOX_ERROR, BusinessException
from app.models.block import Block
from app.models.execution import FlowRun
from app.models.flow import Flow, FlowEdge, FlowNode
from app.observability.logging import get_logger

logger = get_logger("pyflow.flow.k8s")
settings = get_settings()

POD_NAME = os.getenv("HOSTNAME", "pyflow-hub-local")
INVOKE_TIMEOUT = 120.0


def service_url(name: str, namespace: str, port: int = 8000) -> str:
    return f"http://{name}.{namespace}.svc.cluster.local:{port}/invoke"


async def invoke_block_service(
    deployment_name_: str, namespace: str, inputs: dict[str, Any],
    *, entrypoint: str = "run",
) -> dict[str, Any]:
    """调用 Block K8s Service /invoke（决策 10 同步编排）。

    :param entrypoint: 调用脚本中的哪个入口函数（默认 ``run``，支持一脚本多函数）
    """
    url = service_url(deployment_name_, namespace)
    async with httpx.AsyncClient(timeout=INVOKE_TIMEOUT) as cli:
        resp = await cli.post(url, json={"inputs": inputs, "entrypoint": entrypoint})
        resp.raise_for_status()
        data = resp.json()
    output = data.get("output")
    if data.get("error"):
        raise BusinessException(PYFLOW_EXEC_SANDBOX_ERROR, str(data["error"])[:500])
    return output if isinstance(output, dict) else {"value": output}


async def _load_graph(session: AsyncSession, flow_id: str) -> tuple[list[dict], list[dict]]:
    nodes = [
        {"id": n.id, "node_type": n.node_type, "block_id": n.block_id,
         "config": n.config, "position": n.position}
        for n in (await session.execute(
            select(FlowNode).where(FlowNode.flow_id == flow_id)
        )).scalars().all()
    ]
    edges = [
        {"id": e.id, "source_node_id": e.source_node_id, "target_node_id": e.target_node_id,
         "source_port": e.source_port, "target_port": e.target_port}
        for e in (await session.execute(
            select(FlowEdge).where(FlowEdge.flow_id == flow_id)
        )).scalars().all()
    ]
    return nodes, edges


async def drive_flow_run(
    session: AsyncSession, run: FlowRun, flow_id: str, inputs: dict[str, Any], namespace: str
) -> dict[str, Any]:
    """驱动一个 FlowRun（首次执行或续跑），返回 {status, outputs}。"""
    fence = await flow_run_store.claim_run(session, run.id, POD_NAME)
    if fence is None:
        return {"status": run.status, "outputs": {}, "claimed": False}

    nodes, edges = await _load_graph(session, flow_id)
    flow_obj = await session.get(Flow, flow_id)
    entry_node_id = flow_obj.entry_node_id if flow_obj else None

    # 预取 block（resource_prefix 用于推导 service 名）
    ctx = DeployContext(namespace=namespace, resource_prefix=f"flow-{flow_id[:8]}")
    block_cache: dict[str, Block] = {}
    for n in nodes:
        if n.get("block_id") and n["block_id"] not in block_cache:
            b = await session.get(Block, n["block_id"])
            if b is not None:
                block_cache[n["block_id"]] = b

    # 续跑：还原已完成节点输出 / 分支决策 / 跳过集合
    prior_outputs: dict[str, dict] = {}
    prior_active: dict[str, str] = {}
    prior_skipped: set[str] = set()
    for nid, st in (run.node_states or {}).items():
        if not isinstance(st, dict):
            continue
        if st.get("status") == "skipped":
            prior_skipped.add(nid)
        elif st.get("status") == "done":
            if "hit_port" in st:
                prior_active[nid] = st["hit_port"]
            elif "output" in st:
                prior_outputs[nid] = st["output"]

    stop_heartbeat = asyncio.Event()

    async def _heartbeat() -> None:
        while not stop_heartbeat.is_set():
            await asyncio.sleep(flow_run_store.LEASE_TTL_SECONDS // 2)
            ok = await flow_run_store.renew_lease(session, run.id, POD_NAME, fence)
            if not ok:
                logger.warning("flow_run_lease_lost", run_id=run.id)
                stop_heartbeat.set()
                return

    async def node_executor(node: dict, node_inputs: dict) -> dict:
        if stop_heartbeat.is_set():
            raise BusinessException(PYFLOW_EXEC_SANDBOX_ERROR, "lease lost, aborting")
        block = block_cache.get(node.get("block_id"))
        if block is None:
            raise BusinessException(PYFLOW_EXEC_SANDBOX_ERROR, f"block missing for node {node['id']}")
        spec = BlockDeploySpec(block_id=block.id, name=block.name, type=block.type)
        entrypoint = (node.get("config") or {}).get("entrypoint") or "run"
        return await invoke_block_service(
            deployment_name(ctx, spec), namespace, node_inputs, entrypoint=entrypoint
        )

    async def checkpoint(node_id: str, status: str, output: dict) -> None:
        states = dict(run.node_states or {})
        entry: dict[str, Any] = {"status": status}
        if status == "done":
            entry["output"] = output
        states[node_id] = entry
        run.node_states = states
        await session.commit()

    hb_task = asyncio.create_task(_heartbeat())
    try:
        outputs = await run_flow(
            nodes, edges, inputs, node_executor, checkpoint,
            prior_outputs=prior_outputs, prior_active_ports=prior_active, prior_skipped=prior_skipped,
            entry_node_id=entry_node_id,
        )
        run.status = "succeeded"
    except Exception:
        run.status = "failed"
        await session.commit()
        raise
    finally:
        stop_heartbeat.set()
        hb_task.cancel()
    await session.commit()
    return {"status": run.status, "outputs": outputs, "claimed": True}


async def resume_pending_once(namespace: str) -> int:
    """扫描可续跑的 FlowRun 并接管续跑（控制面重启/被驱逐后调用，决策 10）。

    续跑入口节点已完成，无需原始 inputs（下游从已落库的上游输出取值）。返回续跑数。
    """
    from app.db import SessionLocal

    resumed = 0
    async with SessionLocal() as session:
        runs = await flow_run_store.scan_resumable(session)
    for run in runs:
        try:
            async with SessionLocal() as session:
                fresh = await session.get(FlowRun, run.id)
                if fresh is None or fresh.status != "running":
                    continue
                result = await drive_flow_run(session, fresh, fresh.flow_id, {}, namespace)
                if result.get("claimed"):
                    resumed += 1
        except Exception as exc:  # noqa: BLE001 单 run 续跑失败不影响其他
            logger.warning("flow_run_resume_failed", run_id=run.id, error=str(exc))
    if resumed:
        logger.info("flow_run_resumed", count=resumed)
    return resumed


async def resume_loop(namespace: str, interval: int = 60) -> None:
    """周期性续跑扫描（k8s 多副本，控制面重启不丢进行中 flow）。"""
    while True:
        try:
            await resume_pending_once(namespace)
        except Exception as exc:  # noqa: BLE001
            logger.warning("flow_run_resume_loop_error", error=str(exc))
        await asyncio.sleep(interval)
