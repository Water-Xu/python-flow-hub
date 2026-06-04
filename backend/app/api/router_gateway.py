"""同步调用入口（决策 4/10）：仅 Flow 同步编排入口。

- POST /flow/{deployment_id}/invoke：K8s 同步编排，依次调各 Block Service /invoke，FlowRun 续跑落库。

说明（决策 3.1 Flow 级模型 A）：块不再对外暴露独立 HTTP 触发，仅作为 Flow 内的 invoke 服务被编排
驱动（Flow-Consumer / 同步编排调各块 Service /invoke）；对外 HTTP/MQ 触发统一收口到「接口管理」。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import Role, require_role
from app.config import get_settings
from app.core.flow import k8s_orchestration
from app.db import get_session
from app.errors import PYFLOW_FLOW_NOT_FOUND, BusinessException
from app.models.deployment import FlowDeployment
from app.models.execution import FlowRun

router = APIRouter(tags=["gateway"])
settings = get_settings()


class InvokeRequest(BaseModel):
    inputs: dict = {}
    # 调用脚本中的哪个入口函数（默认 run，支持一脚本多函数）
    entrypoint: str | None = None


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
