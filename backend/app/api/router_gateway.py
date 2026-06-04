"""同步调用入口（决策 4/10）：Flow 同步编排入口 + 单 Block /invoke。

- POST /flow/{deployment_id}/invoke：K8s 同步编排，依次调各 Block Service /invoke，FlowRun 续跑落库。
- POST /invoke/{block_id}：单 Block 同步调用（local 走 docker_executor；k8s 走 Block Service）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import Role, require_role
from app.config import get_settings
from app.core.execution_service import execute_block
from app.core.flow import k8s_orchestration
from app.core.k8s.manifest_generator import BlockDeploySpec, DeployContext, deployment_name
from app.db import get_session
from app.errors import (
    PYFLOW_BLOCK_NOT_FOUND,
    PYFLOW_EXEC_SANDBOX_ERROR,
    PYFLOW_FLOW_NOT_FOUND,
    BusinessException,
)
from app.models.block import Block
from app.models.deployment import FlowDeployment
from app.models.execution import FlowRun

router = APIRouter(tags=["gateway"])
settings = get_settings()


class InvokeRequest(BaseModel):
    inputs: dict = {}


@router.post("/flow/{deployment_id}/invoke")
async def invoke_flow(
    deployment_id: str,
    req: InvokeRequest,
    session: AsyncSession = Depends(get_session),
    login_id: str = Depends(require_role(Role.EDITOR)),
):
    """Flow 同步编排入口。"""
    deployment = await session.get(FlowDeployment, deployment_id)
    if deployment is None:
        raise BusinessException(PYFLOW_FLOW_NOT_FOUND, deployment_id)

    nodes_snapshot = {"deployment_id": deployment_id}
    run = FlowRun(
        flow_deployment_id=deployment_id, flow_id=deployment.flow_id,
        status="running", dag_snapshot=nodes_snapshot, node_states={},
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    if deployment.environment == "k8s":
        result = await k8s_orchestration.drive_flow_run(
            session, run, deployment.flow_id, req.inputs, settings.k8s_namespace
        )
        return {"flow_run_id": run.id, **result}

    # local：复用 dev 整流（控制面 docker_executor）
    from app.api.router_flows import run_flow_endpoint
    from app.schemas.flow import FlowRunRequest

    out = await run_flow_endpoint(
        deployment.flow_id, FlowRunRequest(inputs=req.inputs), session, login_id
    )
    return {"flow_run_id": run.id, "delegated": out}


@router.post("/invoke/{block_id}")
async def invoke_block(
    block_id: str,
    req: InvokeRequest,
    session: AsyncSession = Depends(get_session),
    login_id: str = Depends(require_role(Role.EDITOR)),
):
    """单 Block 同步调用入口。"""
    block = await session.get(Block, block_id)
    if block is None:
        raise BusinessException(PYFLOW_BLOCK_NOT_FOUND, block_id)

    if settings.deployment_mode == "k8s":
        ctx = DeployContext(namespace=settings.k8s_namespace)
        spec = BlockDeploySpec(block_id=block.id, name=block.name, type=block.type,
                               execution_mode=block.execution_mode)
        output = await k8s_orchestration.invoke_block_service(
            deployment_name(ctx, spec), settings.k8s_namespace, req.inputs
        )
        return {"output": output}

    record = await execute_block(
        session, block_id=block.id, code=block.draft_code or "",
        inputs=req.inputs, login_id=login_id,
    )
    if record.status != "success":
        raise BusinessException(PYFLOW_EXEC_SANDBOX_ERROR, (record.stderr or "")[:500])
    return {"output": record.output, "execution_id": record.id}
