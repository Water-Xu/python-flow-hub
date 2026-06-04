"""/api/flows — Flow CRUD + 画布保存（DAG 校验）+ dev-local 整流执行。"""

from __future__ import annotations

import posixpath
import zipfile
from typing import Any

from pyflow_runtime.executor import discover_entrypoints

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import Role, require_role
from app.core.execution_service import execute_block
from app.core.flow.dag import validate_dag
from app.core.flow.flow_runner import run_flow
from app.core.flow.zip_import import build_tree, parse_zip
from app.db import get_session
from app.errors import (
    PYFLOW_API_LOCKED,
    PYFLOW_BLOCK_NOT_FOUND,
    PYFLOW_EXEC_INPUT_INVALID,
    PYFLOW_EXEC_SANDBOX_ERROR,
    PYFLOW_FLOW_IN_USE,
    PYFLOW_FLOW_NOT_FOUND,
    BusinessException,
)
from app.models.api_portal import PublishedApi
from app.models.base_mixin import gen_uuid
from app.models.block import Block
from app.models.deployment import FlowDeployment
from app.models.execution import FlowRun
from app.models.flow import Flow, FlowEdge, FlowNode
from app.models.version import FlowVersion
from app.schemas.flow import (
    FlowCreateRequest,
    FlowDetailResponse,
    FlowGraphRequest,
    FlowImportResponse,
    FlowResponse,
    FlowRunRequest,
)

# 导入压缩包最大体积（10MB）
_MAX_ZIP_BYTES = 10 * 1024 * 1024
# 单流程最多导入的脚本块数量（防滥用）
_MAX_SCRIPT_BLOCKS = 200

router = APIRouter(prefix="/api/flows", tags=["flows"])


def _discover_script_entrypoints(code: str) -> list[dict[str, Any]]:
    """静态扫描脚本入口函数，回填导入块的 entrypoints（不执行用户代码）。"""
    return [
        {"name": ep["name"], "description": ep.get("docstring", ""),
         "params": ep.get("params", [])}
        for ep in discover_entrypoints(code or "")
    ]


async def _get_flow(session: AsyncSession, flow_id: str) -> Flow:
    flow = await session.get(Flow, flow_id)
    if flow is None:
        raise BusinessException(PYFLOW_FLOW_NOT_FOUND, flow_id)
    return flow


async def _assert_flow_not_locked(session: AsyncSession, flow_id: str) -> None:
    """若该流程被任何已锁定接口关联，则拒绝写操作。"""
    locked_apis = (await session.execute(
        select(PublishedApi).where(
            PublishedApi.active_flow_id == flow_id,
            PublishedApi.is_locked.is_(True),
        )
    )).scalars().all()
    if locked_apis:
        api_names = ", ".join(a.name for a in locked_apis)
        raise BusinessException(
            PYFLOW_API_LOCKED,
            f"流程被锁定接口 [{api_names}] 引用，禁止修改。如需变更请创建副本。",
        )


async def _assert_flow_deletable(session: AsyncSession, flow_id: str) -> None:
    """删除前校验：被锁定接口、已发布接口或部署实例引用的流程禁止删除。"""
    apis = (await session.execute(
        select(PublishedApi).where(
            or_(PublishedApi.flow_id == flow_id, PublishedApi.active_flow_id == flow_id)
        )
    )).scalars().all()
    locked_apis = [a for a in apis if a.is_locked]
    if locked_apis:
        api_names = ", ".join(a.name for a in locked_apis)
        raise BusinessException(
            PYFLOW_API_LOCKED,
            f"流程被锁定接口 [{api_names}] 引用，禁止删除。如需删除请先解锁。",
        )
    if apis:
        api_names = ", ".join(a.name for a in apis)
        raise BusinessException(
            PYFLOW_FLOW_IN_USE,
            f"流程已发布为接口 [{api_names}]，请先下线接口再删除。",
        )

    deployments = (await session.execute(
        select(FlowDeployment).where(FlowDeployment.flow_id == flow_id)
    )).scalars().all()
    if deployments:
        names = ", ".join(d.name for d in deployments)
        raise BusinessException(
            PYFLOW_FLOW_IN_USE,
            f"流程存在部署实例 [{names}]，请先销毁部署再删除。",
        )


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


@router.post("/import-zip", response_model=FlowImportResponse)
async def import_flow_zip(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    session: AsyncSession = Depends(get_session),
    login_id: str = Depends(require_role(Role.EDITOR)),
):
    """导入 Python 脚本压缩包：`.py` 解析为调用块，其余文件作为资源，整体生成 1 个流程。"""
    data = await file.read()
    if not data:
        raise BusinessException(PYFLOW_EXEC_INPUT_INVALID, "empty file")
    if len(data) > _MAX_ZIP_BYTES:
        raise BusinessException(PYFLOW_EXEC_INPUT_INVALID, "zip exceeds 10MB limit")
    try:
        parsed = parse_zip(data)
    except zipfile.BadZipFile:
        raise BusinessException(PYFLOW_EXEC_INPUT_INVALID, "invalid zip file")

    if not parsed.scripts and not parsed.resources:
        raise BusinessException(PYFLOW_EXEC_INPUT_INVALID, "zip has no importable files")
    if len(parsed.scripts) > _MAX_SCRIPT_BLOCKS:
        raise BusinessException(PYFLOW_EXEC_INPUT_INVALID, f"too many scripts (>{_MAX_SCRIPT_BLOCKS})")

    flow_name = (name or _strip_zip_ext(file.filename) or "导入流程").strip()[:128]
    flow = Flow(
        id=gen_uuid(),
        name=flow_name,
        description=f"由压缩包导入，{len(parsed.scripts)} 个脚本块 / {len(parsed.resources)} 个资源",
        owner_login_id=login_id,
        source="zip_import",
    )
    session.add(flow)

    leaves: list[dict[str, Any]] = []
    cols = 4
    for idx, (path, code) in enumerate(sorted(parsed.scripts.items())):
        block_id = gen_uuid()
        node_id = gen_uuid()
        filename = posixpath.basename(path)
        session.add(Block(
            id=block_id,
            name=path,
            description=f"导入自 {flow_name}",
            owner_login_id=login_id,
            type="script",
            draft_code=code,
            input_ports=[{"name": "inputs", "type": "any", "required": False}],
            output_ports=[{"name": "output", "type": "any", "required": False}],
            entrypoints=_discover_script_entrypoints(code),
        ))
        session.add(FlowNode(
            id=node_id,
            flow_id=flow.id,
            node_type="block",
            block_id=block_id,
            config={"label": filename, "mode": "sync_http", "path": path},
            position={"x": 120 + (idx % cols) * 240, "y": 120 + (idx // cols) * 150},
        ))
        leaves.append({"path": path, "kind": "block", "block_id": block_id, "node_id": node_id})

    for path in parsed.resources:
        leaves.append({"path": path, "kind": "resource"})

    flow.tree = build_tree(leaves)
    flow.resources = parsed.resources
    await session.commit()

    return FlowImportResponse(
        flow_id=flow.id,
        name=flow.name,
        block_count=len(parsed.scripts),
        resource_count=len(parsed.resources),
    )


def _strip_zip_ext(filename: str | None) -> str:
    if not filename:
        return ""
    base = posixpath.basename(filename)
    for ext in (".zip", ".tar", ".gz"):
        if base.lower().endswith(ext):
            return base[: -len(ext)]
    return base


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
    resp.tree = flow.tree or {}
    resp.resources = flow.resources or {}
    return resp


@router.put("/{flow_id}/graph", response_model=FlowDetailResponse)
async def save_flow_graph(
    flow_id: str,
    req: FlowGraphRequest,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.EDITOR)),
):
    """保存画布：保存/发布时强制 DAG 无环校验（决策 10）。"""
    await _assert_flow_not_locked(session, flow_id)
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


@router.post("/{flow_id}/copy", response_model=FlowDetailResponse)
async def copy_flow(
    flow_id: str,
    session: AsyncSession = Depends(get_session),
    login_id: str = Depends(require_role(Role.EDITOR)),
):
    """创建流程副本（锁定状态下也允许，副本不受原接口锁定约束）。"""
    src_flow = await _get_flow(session, flow_id)
    src_nodes = (await session.execute(
        select(FlowNode).where(FlowNode.flow_id == flow_id)
    )).scalars().all()
    src_edges = (await session.execute(
        select(FlowEdge).where(FlowEdge.flow_id == flow_id)
    )).scalars().all()

    new_flow = Flow(
        id=gen_uuid(),
        name=f"{src_flow.name} (副本)",
        description=src_flow.description,
        owner_login_id=login_id,
        source="blank",
    )
    session.add(new_flow)

    # node id 映射（旧 → 新）
    id_map: dict[str, str] = {}
    for n in src_nodes:
        new_id = gen_uuid()
        id_map[n.id] = new_id
        session.add(FlowNode(
            id=new_id, flow_id=new_flow.id,
            node_type=n.node_type, block_id=n.block_id,
            config=dict(n.config), position=dict(n.position),
        ))
    for e in src_edges:
        session.add(FlowEdge(
            flow_id=new_flow.id,
            source_node_id=id_map.get(e.source_node_id, e.source_node_id),
            target_node_id=id_map.get(e.target_node_id, e.target_node_id),
            source_port=e.source_port, target_port=e.target_port,
        ))

    await session.commit()
    return await get_flow(new_flow.id, session, login_id)


@router.delete("/{flow_id}")
async def remove_flow(
    flow_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.EDITOR)),
):
    """删除流程（未被锁定 / 发布 / 部署的流程），级联清理其节点、边、版本与运行记录。"""
    flow = await _get_flow(session, flow_id)
    await _assert_flow_deletable(session, flow_id)

    await session.execute(delete(FlowEdge).where(FlowEdge.flow_id == flow_id))
    await session.execute(delete(FlowNode).where(FlowNode.flow_id == flow_id))
    await session.execute(delete(FlowVersion).where(FlowVersion.flow_id == flow_id))
    await session.execute(delete(FlowRun).where(FlowRun.flow_id == flow_id))
    await session.delete(flow)
    await session.commit()
    return {"deleted": flow_id}


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
        block_id = node.get("block_id")
        if not block_id:
            raise BusinessException(PYFLOW_EXEC_INPUT_INVALID, f"node {node.get('id')} missing block_id")
        block = block_cache[block_id]
        entrypoint = (node.get("config") or {}).get("entrypoint") or "run"
        record = await execute_block(
            session, block_id=block.id, code=block.draft_code or "",
            inputs=inputs, login_id=login_id, flow_run_id=flow_run.id,
            entrypoint=entrypoint,
        )
        if record.status != "success":
            detail = (record.stderr or "block execution failed").strip()[:500]
            raise BusinessException(PYFLOW_EXEC_SANDBOX_ERROR, detail)
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
