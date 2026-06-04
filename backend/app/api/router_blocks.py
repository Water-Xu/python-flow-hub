"""/api/blocks — Block CRUD + 执行 + 副本创建。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import Role, require_role
from app.core.execution_service import execute_block
from app.core.mq.validation import validate_mq_config
from app.db import get_session
from app.errors import (
    PYFLOW_API_LOCKED,
    PYFLOW_BLOCK_NOT_FOUND,
    PYFLOW_EXEC_INPUT_INVALID,
    BusinessException,
)
from pyflow_runtime.executor import discover_entrypoints

from app.models.api_portal import PublishedApi
from app.models.block import Block
from app.models.flow import FlowNode
from app.schemas.block import (
    BlockCreateRequest,
    BlockResponse,
    BlockRunRequest,
    BlockUpdateRequest,
)

router = APIRouter(prefix="/api/blocks", tags=["blocks"])


def _compute_entrypoints(code: str, existing: list | None = None) -> list[dict]:
    """由脚本源码静态扫描入口函数，保留既有的人工描述。

    :param code: Block 脚本源码
    :param existing: 已存储的 entrypoints（用于沿用其 description）
    :return: [{name, description, params}]
    """
    prior_desc = {
        e.get("name"): e.get("description", "")
        for e in (existing or [])
        if isinstance(e, dict)
    }
    result: list[dict] = []
    for ep in discover_entrypoints(code or ""):
        result.append({
            "name": ep["name"],
            "description": prior_desc.get(ep["name"]) or ep.get("docstring", ""),
            "params": ep.get("params", []),
        })
    return result

# 疑似密钥正则（决策 15：env_vars 仅允许非敏感值）
import re
from app.models.base_mixin import gen_uuid

_SECRET_PATTERN = re.compile(r"(SECRET|TOKEN|PASSWORD|PASSWD|KEY|CREDENTIAL|PRIVATE)", re.I)


def _check_env_vars(env_vars: dict[str, str]) -> None:
    for k in env_vars:
        if _SECRET_PATTERN.search(k):
            raise BusinessException(PYFLOW_EXEC_INPUT_INVALID, f"sensitive env key forbidden: {k}")


async def _assert_block_not_locked(session: AsyncSession, block_id: str) -> None:
    """若该块被任何已锁定接口关联的流程引用，则拒绝写操作。"""
    nodes = (await session.execute(
        select(FlowNode).where(FlowNode.block_id == block_id)
    )).scalars().all()
    flow_ids = {n.flow_id for n in nodes}
    if not flow_ids:
        return
    for flow_id in flow_ids:
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
                f"块被锁定接口 [{api_names}] 引用，禁止修改。如需变更请创建副本。",
            )


async def _get_block(session: AsyncSession, block_id: str) -> Block:
    block = await session.get(Block, block_id)
    if block is None:
        raise BusinessException(PYFLOW_BLOCK_NOT_FOUND, block_id)
    return block


@router.get("", response_model=list[BlockResponse])
async def list_blocks(
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    rows = (await session.execute(select(Block).order_by(Block.updated_at.desc()))).scalars().all()
    return rows


@router.post("", response_model=BlockResponse)
async def save_block(
    req: BlockCreateRequest,
    session: AsyncSession = Depends(get_session),
    login_id: str = Depends(require_role(Role.EDITOR)),
):
    _check_env_vars(req.env_vars)
    validate_mq_config(req.mq_config, req.execution_mode)
    block = Block(
        name=req.name,
        description=req.description,
        owner_login_id=login_id,
        type=req.type,
        draft_code=req.draft_code,
        input_ports=[p.model_dump() for p in req.input_ports],
        output_ports=[p.model_dump() for p in req.output_ports],
        entrypoints=_compute_entrypoints(req.draft_code),
        env_vars=req.env_vars,
        execution_mode=req.execution_mode,
        mq_config=req.mq_config,
        compute_config=req.compute_config.model_dump(),
    )
    session.add(block)
    await session.commit()
    await session.refresh(block)
    return block


@router.get("/{block_id}", response_model=BlockResponse)
async def get_block(
    block_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    return await _get_block(session, block_id)


@router.put("/{block_id}", response_model=BlockResponse)
async def update_block(
    block_id: str,
    req: BlockUpdateRequest,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.EDITOR)),
):
    await _assert_block_not_locked(session, block_id)
    block = await _get_block(session, block_id)
    data = req.model_dump(exclude_unset=True)
    if "env_vars" in data and data["env_vars"]:
        _check_env_vars(data["env_vars"])
    # 校验 MQ 配置（决策 1/6/10）：以更新后的 execution_mode + mq_config 为准
    if "mq_config" in data or "execution_mode" in data:
        exec_mode = data.get("execution_mode", block.execution_mode)
        mq_cfg = data.get("mq_config", block.mq_config)
        validate_mq_config(mq_cfg, exec_mode)
    for key, value in data.items():
        if key in {"input_ports", "output_ports"} and value is not None:
            value = [p.model_dump() if hasattr(p, "model_dump") else p for p in value]
        if key == "compute_config" and value is not None and hasattr(value, "model_dump"):
            value = value.model_dump()
        setattr(block, key, value)
    # 代码变更时重扫入口函数，沿用既有人工描述
    if "draft_code" in data and data["draft_code"] is not None:
        block.entrypoints = _compute_entrypoints(data["draft_code"], block.entrypoints)
    await session.commit()
    await session.refresh(block)
    return block


@router.delete("/{block_id}")
async def remove_block(
    block_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.EDITOR)),
):
    await _assert_block_not_locked(session, block_id)
    block = await _get_block(session, block_id)
    await session.delete(block)
    await session.commit()
    return {"deleted": block_id}


@router.post("/{block_id}/copy", response_model=BlockResponse)
async def copy_block(
    block_id: str,
    session: AsyncSession = Depends(get_session),
    login_id: str = Depends(require_role(Role.EDITOR)),
):
    """创建块的副本（锁定状态下也允许）。副本不被原接口锁定约束。"""
    src = await _get_block(session, block_id)
    copy = Block(
        id=gen_uuid(),
        name=f"{src.name} (副本)",
        description=src.description,
        owner_login_id=login_id,
        type=src.type,
        draft_code=src.draft_code,
        draft_notebook=src.draft_notebook,
        input_ports=list(src.input_ports),
        output_ports=list(src.output_ports),
        entrypoints=list(src.entrypoints or []),
        env_vars=dict(src.env_vars),
        execution_mode=src.execution_mode,
        mq_config=dict(src.mq_config) if src.mq_config else {},
        compute_config=dict(src.compute_config) if src.compute_config else {},
    )
    session.add(copy)
    await session.commit()
    await session.refresh(copy)
    return copy


@router.post("/{block_id}/discover-entrypoints")
async def discover_block_entrypoints(
    block_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.EDITOR)),
):
    """静态扫描块脚本暴露的入口函数清单（供前端节点选择调用哪个函数）。

    扫描已保存的 draft_code（不执行用户代码）；同时把结果回填到 Block.entrypoints。
    """
    block = await _get_block(session, block_id)
    entrypoints = _compute_entrypoints(block.draft_code or "", block.entrypoints)
    block.entrypoints = entrypoints
    await session.commit()
    return {"block_id": block_id, "entrypoints": entrypoints}


@router.post("/{block_id}/run")
async def run_block_endpoint(
    block_id: str,
    req: BlockRunRequest,
    session: AsyncSession = Depends(get_session),
    login_id: str = Depends(require_role(Role.EDITOR)),
):
    """触发 HTTP 执行（dev 本地 Docker 沙箱）。返回 execution_id + 结果。"""
    block = await _get_block(session, block_id)
    record = await execute_block(
        session, block_id=block.id, code=block.draft_code,
        inputs=req.inputs, login_id=login_id,
        entrypoint=req.entrypoint or "run",
    )
    return {
        "execution_id": record.id,
        "status": record.status,
        "output": record.output,
        "stdout": record.stdout,
        "stderr": record.stderr,
        "duration_ms": record.duration_ms,
    }
