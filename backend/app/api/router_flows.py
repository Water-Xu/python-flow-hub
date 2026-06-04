"""/api/flows — Flow CRUD + 画布保存（DAG 校验）+ dev-local 整流执行。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import Role, require_role
from app.core.execution_service import execute_block
from app.core.flow.dag import validate_dag
from app.core.flow.flow_runner import run_flow
from app.db import get_session
from app.errors import PYFLOW_BLOCK_NOT_FOUND, PYFLOW_FLOW_NOT_FOUND, BusinessException
from app.models.block import Block
from app.models.execution import FlowRun
from app.models.flow import Flow, FlowEdge, FlowNode
from app.schemas.flow import (
    FlowCreateRequest,
    FlowDetailResponse,
    FlowGraphRequest,
    FlowResponse,
    FlowRunRequest,
)

router = APIRouter(prefix="/api/flows", tags=["flows"])


async def _get_flow(session: AsyncSession, flow_id: str) -> Flow:
    flow = await session.get(Flow, flow_id)
    if flow is None:
        raise BusinessException(PYFLOW_FLOW_NOT_FOUND, flow_id)
    return flow


@router.get("", response_model=list[FlowResponse])
async def list_flows(
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    return (await session.execute(select(Flow).order_by(Flow.updated_at.desc()))).scalars().all()


@router.post("", response_model=FlowResponse)
async def save_flow(
    req: FlowCreateRequest,
    session: AsyncSession = Depends(get_session),
    login_id: str = Depends(require_role(Role.EDITOR)),
):
    flow = Flow(name=req.name, description=req.description, owner_login_id=login_id)
    session.add(flow)
    await session.commit()
    await session.refresh(flow)
    return flow


@router.get("/{flow_id}", response_model=FlowDetailResponse)
async def get_flow(
    flow_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    flow = await _get_flow(session, flow_id)
    nodes = (await session.execute(
        select(FlowNode).where(FlowNode.flow_id == flow_id)
    )).scalars().all()
    edges = (await session.execute(
        select(FlowEdge).where(FlowEdge.flow_id == flow_id)
    )).scalars().all()
    resp = FlowDetailResponse.model_validate(flow)
    resp.nodes = [_node_dict(n) for n in nodes]
    resp.edges = [_edge_dict(e) for e in edges]
    return resp


@router.put("/{flow_id}/graph", response_model=FlowDetailResponse)
async def save_flow_graph(
    flow_id: str,
    req: FlowGraphRequest,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.EDITOR)),
):
    """保存画布：保存/发布时强制 DAG 无环校验（决策 10）。"""
    flow = await _get_flow(session, flow_id)

    # 生成节点 ID 后做 DAG 校验
    nodes_in = []
    id_map: dict[str, str] = {}
    for idx, n in enumerate(req.nodes):
        nid = n.id or f"node-{idx}"
        id_map[nid] = nid
        nodes_in.append({"id": nid, **n.model_dump()})
    edges_in = [e.model_dump() for e in req.edges]
    validate_dag([{"id": n["id"]} for n in nodes_in], edges_in)

    # 全量替换
    await session.execute(delete(FlowNode).where(FlowNode.flow_id == flow_id))
    await session.execute(delete(FlowEdge).where(FlowEdge.flow_id == flow_id))
    for n in nodes_in:
        session.add(FlowNode(
            id=n["id"], flow_id=flow_id, node_type=n["node_type"],
            block_id=n.get("block_id"), config=n.get("config", {}),
            position=n.get("position", {}),
        ))
    for e in edges_in:
        session.add(FlowEdge(
            flow_id=flow_id, source_node_id=e["source_node_id"],
            target_node_id=e["target_node_id"],
            source_port=e.get("source_port", "output"),
            target_port=e.get("target_port", "input"),
        ))
    await session.commit()
    return await get_flow(flow_id, session, flow.owner_login_id)


@router.post("/{flow_id}/run")
async def run_flow_endpoint(
    flow_id: str,
    req: FlowRunRequest,
    session: AsyncSession = Depends(get_session),
    login_id: str = Depends(require_role(Role.EDITOR)),
):
    """dev-local 整流执行（同步编排等价路径，决策 10）。"""
    flow = await _get_flow(session, flow_id)
    nodes = [_node_dict(n) for n in (await session.execute(
        select(FlowNode).where(FlowNode.flow_id == flow_id)
    )).scalars().all()]
    edges = [_edge_dict(e) for e in (await session.execute(
        select(FlowEdge).where(FlowEdge.flow_id == flow_id)
    )).scalars().all()]

    flow_run = FlowRun(
        flow_id=flow_id, status="running",
        dag_snapshot={"nodes": nodes, "edges": edges}, node_states={},
    )
    session.add(flow_run)
    await session.commit()
    await session.refresh(flow_run)

    # 预取各 block 代码
    block_cache: dict[str, Block] = {}
    for n in nodes:
        if n.get("block_id") and n["block_id"] not in block_cache:
            b = await session.get(Block, n["block_id"])
            if b is None:
                raise BusinessException(PYFLOW_BLOCK_NOT_FOUND, n["block_id"])
            block_cache[n["block_id"]] = b

    async def node_executor(node: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
        block = block_cache[node["block_id"]]
        record = await execute_block(
            session, block_id=block.id, code=block.draft_code,
            inputs=inputs, login_id=login_id, flow_run_id=flow_run.id,
        )
        out = record.output if isinstance(record.output, dict) else {"value": record.output}
        return out

    async def checkpoint(node_id: str, status: str, output: dict[str, Any]) -> None:
        states = dict(flow_run.node_states)
        states[node_id] = {"status": status}
        flow_run.node_states = states
        await session.commit()

    try:
        outputs = await run_flow(nodes, edges, req.inputs, node_executor, checkpoint)
        flow_run.status = "succeeded"
    except Exception:
        flow_run.status = "failed"
        await session.commit()
        raise
    await session.commit()
    return {"flow_run_id": flow_run.id, "status": flow_run.status, "outputs": outputs}


def _node_dict(n: FlowNode) -> dict[str, Any]:
    return {
        "id": n.id, "node_type": n.node_type, "block_id": n.block_id,
        "config": n.config, "position": n.position,
    }


def _edge_dict(e: FlowEdge) -> dict[str, Any]:
    return {
        "id": e.id, "source_node_id": e.source_node_id,
        "target_node_id": e.target_node_id,
        "source_port": e.source_port, "target_port": e.target_port,
    }
