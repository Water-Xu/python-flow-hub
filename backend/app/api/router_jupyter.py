"""/api/jupyter — Jupyter 开发态内核（决策 9：仅 local 模式，与生产链路隔离）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.rbac import Role, require_role
from app.core.jupyter.kernel_manager import get_registry

router = APIRouter(prefix="/api/jupyter", tags=["jupyter"])


class ExecuteRequest(BaseModel):
    code: str


@router.post("/{block_id}/start")
async def start_kernel(block_id: str, _: str = Depends(require_role(Role.EDITOR))):
    await get_registry().get_or_start(block_id)
    return get_registry().status(block_id)


@router.post("/{block_id}/execute")
async def execute_cell(
    block_id: str, req: ExecuteRequest, _: str = Depends(require_role(Role.EDITOR))
):
    return await get_registry().execute(block_id, req.code)


@router.post("/{block_id}/interrupt")
async def interrupt_kernel(block_id: str, _: str = Depends(require_role(Role.EDITOR))):
    await get_registry().interrupt(block_id)
    return {"interrupted": True}


@router.post("/{block_id}/shutdown")
async def shutdown_kernel(block_id: str, _: str = Depends(require_role(Role.EDITOR))):
    await get_registry().shutdown(block_id)
    return {"shutdown": True}


@router.get("/{block_id}/status")
async def kernel_status(block_id: str, _: str = Depends(require_role(Role.VIEWER))):
    return get_registry().status(block_id)
