"""/api/versions — Block/Flow 版本快照（Phase 3，决策 8）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import Role, require_role
from app.core.versioning import diff_service, version_manager
from app.db import get_session
from app.errors import (
    PYFLOW_BLOCK_NOT_FOUND,
    PYFLOW_FLOW_NOT_FOUND,
    PYFLOW_VERSION_NOT_STABLE,
    BusinessException,
)
from app.models.block import Block
from app.models.flow import Flow, FlowEdge, FlowNode
from app.models.version import BlockVersion, FlowVersion

router = APIRouter(prefix="/api/versions", tags=["versions"])


class BlockVersionCreateRequest(BaseModel):
    version_tag: str
    commit_message: str = ""
    requirements_text: str = ""
    set_stable: bool = True


class FlowVersionCreateRequest(BaseModel):
    version_tag: str
    commit_message: str = ""
    set_stable: bool = True


def _bv_dict(v: BlockVersion) -> dict:
    return {
        "id": v.id, "block_id": v.block_id, "version_tag": v.version_tag,
        "commit_message": v.commit_message, "is_stable": v.is_stable,
        "created_by": v.created_by, "created_at": v.created_at,
        "requirements_hash": v.requirements_hash, "content_sha256": v.content_sha256,
    }


def _fv_dict(v: FlowVersion) -> dict:
    return {
        "id": v.id, "flow_id": v.flow_id, "version_tag": v.version_tag,
        "commit_message": v.commit_message, "is_stable": v.is_stable,
        "created_by": v.created_by, "created_at": v.created_at,
        "node_count": v.node_count, "edge_count": v.edge_count,
    }


# ------------------------- Block 版本 -------------------------

@router.post("/blocks/{block_id}")
async def create_block_version(
    block_id: str,
    req: BlockVersionCreateRequest,
    session: AsyncSession = Depends(get_session),
    login_id: str = Depends(require_role(Role.EDITOR)),
):
    block = await session.get(Block, block_id)
    if block is None:
        raise BusinessException(PYFLOW_BLOCK_NOT_FOUND, block_id)
    version = await version_manager.create_block_version(
        session, block,
        version_tag=req.version_tag, commit_message=req.commit_message,
        login_id=login_id, requirements_text=req.requirements_text,
        set_stable=req.set_stable,
    )
    return _bv_dict(version)


@router.get("/blocks/{block_id}")
async def list_block_versions(
    block_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    rows = (await session.execute(
        select(BlockVersion).where(BlockVersion.block_id == block_id)
        .order_by(BlockVersion.created_at.desc())
    )).scalars().all()
    return [_bv_dict(v) for v in rows]


@router.get("/block-versions/{version_id}")
async def get_block_version(
    version_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    version = await session.get(BlockVersion, version_id)
    if version is None:
        raise BusinessException(PYFLOW_VERSION_NOT_STABLE, version_id)
    content = await version_manager.get_block_version_content(version)
    return {**_bv_dict(version), **content}


@router.post("/block-versions/{version_id}/stable")
async def set_block_stable(
    version_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.EDITOR)),
):
    version = await session.get(BlockVersion, version_id)
    if version is None:
        raise BusinessException(PYFLOW_VERSION_NOT_STABLE, version_id)
    rows = (await session.execute(
        select(BlockVersion).where(
            BlockVersion.block_id == version.block_id, BlockVersion.is_stable.is_(True)
        )
    )).scalars().all()
    for r in rows:
        r.is_stable = False
    version.is_stable = True
    block = await session.get(Block, version.block_id)
    if block is not None:
        block.stable_version_id = version.id
    await session.commit()
    return {"id": version.id, "is_stable": True}


@router.get("/blocks/{block_id}/diff")
async def diff_block_versions(
    block_id: str,
    from_version: str,
    to_version: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    a = await session.get(BlockVersion, from_version)
    b = await session.get(BlockVersion, to_version)
    if a is None or b is None:
        raise BusinessException(PYFLOW_VERSION_NOT_STABLE, "version not found")
    old = (await version_manager.get_block_version_content(a)).get("code", "")
    new = (await version_manager.get_block_version_content(b)).get("code", "")
    return diff_service.diff_payload(
        old, new, old_label=a.version_tag or a.id[:8], new_label=b.version_tag or b.id[:8]
    )


# ------------------------- Flow 版本 -------------------------

@router.post("/flows/{flow_id}")
async def create_flow_version(
    flow_id: str,
    req: FlowVersionCreateRequest,
    session: AsyncSession = Depends(get_session),
    login_id: str = Depends(require_role(Role.EDITOR)),
):
    flow = await session.get(Flow, flow_id)
    if flow is None:
        raise BusinessException(PYFLOW_FLOW_NOT_FOUND, flow_id)
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
    version = await version_manager.create_flow_version(
        session, flow, nodes, edges,
        version_tag=req.version_tag, commit_message=req.commit_message,
        login_id=login_id, set_stable=req.set_stable,
    )
    return _fv_dict(version)


@router.get("/flows/{flow_id}")
async def list_flow_versions(
    flow_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    rows = (await session.execute(
        select(FlowVersion).where(FlowVersion.flow_id == flow_id)
        .order_by(FlowVersion.created_at.desc())
    )).scalars().all()
    return [_fv_dict(v) for v in rows]


@router.get("/flow-versions/{version_id}")
async def get_flow_version(
    version_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    version = await session.get(FlowVersion, version_id)
    if version is None:
        raise BusinessException(PYFLOW_VERSION_NOT_STABLE, version_id)
    snapshot = await version_manager.get_flow_snapshot(version)
    return {**_fv_dict(version), "snapshot": snapshot}


@router.get("/reconcile")
async def reconcile(
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.ADMIN)),
):
    """对账任务（手动触发 / 定时调度）：孤儿对象 + 悬挂指针 + 损坏统计。"""
    return await version_manager.reconcile_orphans(session)
