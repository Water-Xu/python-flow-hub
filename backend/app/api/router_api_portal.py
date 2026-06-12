"""/api/portal — 用户接口：发布流程为 HTTP 接口 + 查看自己的接口 + 调用接口。

调用路径：POST /api/public/{path}
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import Role, require_role
from app.config import get_settings
from app.core import crypto
from app.core.execution_service import execute_block, execute_block_stream
from app.core.flow.flow_runner import run_flow
from pyflow_runtime.flow_dag import select_entry_subgraph
from app.core.mq.invocation_doc import build_mq_invocation
from app.db import get_session
from app.errors import (
    PYFLOW_API_AUTH_FAILED,
    PYFLOW_API_AUTH_REQUIRED,
    PYFLOW_API_DECRYPT_FAILED,
    PYFLOW_API_ENCRYPTION_REQUIRED,
    PYFLOW_API_LOCKED,
    PYFLOW_API_NOT_FOUND,
    PYFLOW_API_PATH_EXISTS,
    PYFLOW_API_RATE_LIMITED,
    PYFLOW_AUTH_FORBIDDEN,
    PYFLOW_BLOCK_NOT_FOUND,
    PYFLOW_EXEC_SANDBOX_ERROR,
    BusinessException,
)
from app.core.mq.validation import validate_mq_config
from app.models.api_portal import PublishedApi
from app.models.block import Block
from app.models.deployment import FlowDeployment
from app.models.flow import Flow, FlowEdge, FlowNode
from app.schemas.api_portal import (
    ApiAuthResponse,
    ApiAuthToggleRequest,
    ApiEncryptionKeyResponse,
    ApiEncryptionRequest,
    ApiMqConfigRequest,
    ApiRemarksRequest,
    ApiResponse,
    PublishApiRequest,
)

router = APIRouter(tags=["api-portal"])
settings = get_settings()

# 内存限流计数器：{api_id: deque[timestamp]}（dev local；生产用 Redis）
_rate_counters: dict[str, deque[float]] = defaultdict(deque)


def _check_rate_limit(api: PublishedApi) -> None:
    """滑动窗口限流（60 秒）。dev 模式；生产使用 Redis。

    用 deque 仅从左端弹出过期时间戳（O(过期数)），避免每次请求重建整个列表。
    """
    if not api.rate_limit_enabled:
        return
    now = time.time()
    cutoff = now - 60.0
    window = _rate_counters[api.id]
    while window and window[0] <= cutoff:
        window.popleft()
    if len(window) >= api.rate_limit_per_minute:
        raise BusinessException(PYFLOW_API_RATE_LIMITED, f"限流 {api.rate_limit_per_minute} req/min")
    window.append(now)


def _resolve_inputs(api: PublishedApi, body: dict[str, Any]) -> dict[str, Any]:
    """根据接口加密配置与 HTTP input_mapping，从请求体中解出 Flow 明文输入。

    规则：
    - 接口要求强制加密（``require_encrypted_request``）但请求未带 ``encrypted=true`` → 拒绝。
    - 请求声明 ``encrypted=true`` 且接口已开启加密且配置了密钥 → 解密 ``inputs``（字符串密文）；
      加密模式不应用 input_mapping（调用方负责构造明文结构）。
    - 接口配置了 ``http_config.input_mapping`` → 以整条请求体为源，按 JSONPath 映射到 Flow 输入端口。
    - 其它情况 → 取 ``body.inputs``（兼容未加密、无 mapping 的传统调用）。

    :param api: 已发布接口
    :param body: 原始请求体
    :return: 明文 inputs（可直接传给 Flow）
    :raises BusinessException: 强制加密但未加密 / 解密失败
    """
    from pyflow_runtime.input_mapper import map_inputs  # 局部导入避免循环

    is_encrypted = bool(body.get("encrypted"))
    if api.require_encrypted_request and not is_encrypted:
        raise BusinessException(PYFLOW_API_ENCRYPTION_REQUIRED, f"接口 {api.path} 要求加密调用")
    if is_encrypted and api.encryption_enabled and api.encryption_key:
        cipher = body.get("inputs")
        if not isinstance(cipher, str):
            raise BusinessException(PYFLOW_API_DECRYPT_FAILED, "加密请求的 inputs 必须为密文字符串")
        try:
            decrypted = crypto.decrypt(api.encryption_key, cipher)
        except ValueError as exc:
            raise BusinessException(PYFLOW_API_DECRYPT_FAILED, str(exc)) from exc
        return decrypted if isinstance(decrypted, dict) else {}
    # HTTP input_mapping：以整条请求体为源，按 JSONPath 映射到 Flow 输入端口
    http_mapping = (api.http_config or {}).get("input_mapping")
    if http_mapping and isinstance(http_mapping, dict):
        return map_inputs(body, http_mapping)
    return body.get("inputs", {})


def _maybe_encrypt_outputs(api: PublishedApi, outputs: Any) -> tuple[Any, bool]:
    """开启加密时将 ``outputs`` 加密为密文字符串。

    :param api: 已发布接口
    :param outputs: 明文输出
    :return: (载荷, 是否已加密)；未开启加密时原样返回 (outputs, False)
    """
    if api.encryption_enabled and api.encryption_key:
        return crypto.encrypt(api.encryption_key, outputs), True
    return outputs, False


def _resolve_node_entrypoint(api: PublishedApi, node: dict[str, Any]) -> str:
    """解析某节点本次调用的入口函数。

    优先级：节点级 ``entrypoint_map[node_id]`` > API 级全局 ``entrypoint``
    > 节点 ``config.entrypoint`` > 默认 ``run``。

    节点级映射解决多个调用块含同名内置函数（如都含 ``run``）时需分别指定入口的场景。

    :param api: 已发布接口
    :param node: 流程节点 dict（含 id / config）
    :return: 入口函数名
    """
    node_id = node.get("id")
    return (
        (api.entrypoint_map or {}).get(node_id)
        or api.entrypoint
        or (node.get("config") or {}).get("entrypoint")
        or "run"
    )


async def _get_api(session: AsyncSession, api_id: str) -> PublishedApi:
    api = await session.get(PublishedApi, api_id)
    if api is None:
        raise BusinessException(PYFLOW_API_NOT_FOUND, api_id)
    return api


async def _get_api_by_path(session: AsyncSession, path: str) -> PublishedApi:
    result = await session.execute(
        select(PublishedApi).where(PublishedApi.path == path)
    )
    api = result.scalar_one_or_none()
    if api is None:
        raise BusinessException(PYFLOW_API_NOT_FOUND, path)
    return api


async def _resolve_block_services(session: AsyncSession, flow_id: str) -> dict[str, str]:
    """k8s 模式下，若该流程存在运行中的 block_mode 部署，返回 ``block_id -> 常驻 invoke Service 名`` 映射。

    命中后公开调用直接复用常驻 invoke Pod（稳定版本代码，无冷启动），免去每个块的一次性 Job；
    无运行部署 / 非 k8s 时返回空映射，调用回退到原一次性 Job 执行 draft 代码（行为不变）。
    Service 名与一键部署 :mod:`orchestrator` 完全一致，避免命名分叉。
    """
    if settings.deployment_mode != "k8s":
        return {}
    deployment = (await session.execute(
        select(FlowDeployment)
        .where(
            FlowDeployment.flow_id == flow_id,
            FlowDeployment.status.in_(["running", "partially_degraded"]),
            FlowDeployment.deployment_type == "block_mode",
        )
        .order_by(FlowDeployment.updated_at.desc())
    )).scalars().first()
    if deployment is None:
        return {}
    from app.core.k8s.manifest_generator import deployment_name
    from app.core.k8s.orchestrator import _build_context, build_specs

    specs = await build_specs(session, flow_id)
    ctx = _build_context(deployment)
    return {bs.block_id: deployment_name(ctx, bs) for bs in specs}


async def _resolve_flow_runner_service(session: AsyncSession, flow_id: str) -> str | None:
    """k8s flow_mode 已部署时，返回 FlowRunner Service 名，供控制面直接调用 /run 整流。

    命中时跳过控制面 run_flow + block 逐个执行，由 FlowRunner Pod in-process 完成整流，
    消除块间 HTTP 开销并使用稳定版本代码（而非 draft）。
    """
    if settings.deployment_mode != "k8s":
        return None
    deployment = (await session.execute(
        select(FlowDeployment)
        .where(
            FlowDeployment.flow_id == flow_id,
            FlowDeployment.status.in_(["running", "partially_degraded"]),
            FlowDeployment.deployment_type == "flow_mode",
        )
        .order_by(FlowDeployment.updated_at.desc())
    )).scalars().first()
    if deployment is None:
        return None
    from app.core.k8s.orchestrator import _build_context
    from app.core.k8s.manifest_generator import FlowRunnerSpec, flow_runner_name

    ctx = _build_context(deployment)
    flow_short = flow_id.replace("-", "")[:8]
    prefix = ctx.resource_prefix or f"flow-{flow_id[:8]}"
    return f"{prefix}-fr-{flow_short}"[:63]


async def _call_flow_runner(
    service: str, inputs: dict, entry_node_id: str | None
) -> dict:
    """调用 FlowRunner Pod 的 /run 端点执行整流（flow_mode k8s 路径）。"""
    import httpx

    url = f"http://{service}.{settings.k8s_namespace}:{8000}/run"
    payload: dict = {"inputs": inputs}
    if entry_node_id:
        payload["entry_node_id"] = entry_node_id
    async with httpx.AsyncClient(timeout=3600) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()


# ── 用户接口管理 ──────────────────────────────────────────────────────────────

@router.get("/api/portal/apis", response_model=list[ApiResponse])
async def list_my_apis(
    session: AsyncSession = Depends(get_session),
    login_id: str = Depends(require_role(Role.VIEWER)),
):
    """列出我发布的所有接口。"""
    rows = (await session.execute(
        select(PublishedApi)
        .where(PublishedApi.owner_login_id == login_id)
        .order_by(PublishedApi.created_at.desc())
    )).scalars().all()
    return rows


@router.get("/api/portal/apis/browse", response_model=list[ApiResponse])
async def browse_apis(
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    """浏览所有已发布且处于活跃状态的接口（对接口门户用户开放，不限制 owner）。"""
    rows = (await session.execute(
        select(PublishedApi)
        .where(PublishedApi.status == "active")
        .order_by(PublishedApi.created_at.desc())
    )).scalars().all()
    return rows


@router.post("/api/portal/apis", response_model=ApiResponse)
async def publish_flow_as_api(
    req: PublishApiRequest,
    session: AsyncSession = Depends(get_session),
    login_id: str = Depends(require_role(Role.EDITOR)),
):
    """将一个流程发布为接口（接口路径唯一）。"""
    # 校验流程存在
    flow = await session.get(Flow, req.flow_id)
    if flow is None:
        raise BusinessException(PYFLOW_BLOCK_NOT_FOUND, req.flow_id)

    # 校验路径唯一
    existing = (await session.execute(
        select(PublishedApi).where(PublishedApi.path == req.path)
    )).scalar_one_or_none()
    if existing is not None:
        raise BusinessException(PYFLOW_API_PATH_EXISTS, req.path)

    api = PublishedApi(
        name=req.name,
        description=req.description,
        path=req.path,
        tags=req.tags,
        flow_id=req.flow_id,
        active_flow_id=req.flow_id,
        owner_login_id=login_id,
        status="active",
        entry_node_id=req.entry_node_id or None,
        entrypoint=req.entrypoint or None,
        entrypoint_map=req.entrypoint_map or {},
    )
    session.add(api)
    await session.commit()
    await session.refresh(api)
    return api


@router.get("/api/portal/apis/{api_id}", response_model=ApiResponse)
async def get_my_api(
    api_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    return await _get_api(session, api_id)


@router.delete("/api/portal/apis/{api_id}")
async def unpublish_api(
    api_id: str,
    session: AsyncSession = Depends(get_session),
    login_id: str = Depends(require_role(Role.EDITOR)),
):
    """下线接口（如已锁定则拒绝）。"""
    api = await _get_api(session, api_id)
    if api.is_locked:
        raise BusinessException(PYFLOW_API_LOCKED, f"接口 {api.name} 已被管理员锁定，无法下线")
    await session.delete(api)
    await session.commit()
    return {"deleted": api_id}


@router.post("/api/portal/apis/{api_id}/pause")
async def pause_api(
    api_id: str,
    session: AsyncSession = Depends(get_session),
    login_id: str = Depends(require_role(Role.EDITOR)),
):
    api = await _get_api(session, api_id)
    if api.is_locked:
        raise BusinessException(PYFLOW_API_LOCKED, "接口已锁定")
    api.status = "paused"
    await session.commit()
    return {"status": "paused"}


@router.post("/api/portal/apis/{api_id}/activate")
async def activate_api(
    api_id: str,
    session: AsyncSession = Depends(get_session),
    login_id: str = Depends(require_role(Role.EDITOR)),
):
    api = await _get_api(session, api_id)
    api.status = "active"
    await session.commit()
    return {"status": "active"}


@router.put("/api/portal/apis/{api_id}/mq", response_model=ApiResponse)
async def update_api_mq_config(
    api_id: str,
    req: ApiMqConfigRequest,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.EDITOR)),
):
    """配置接口触发方式（http/mq/both）与 MQ 触发参数（队列/条件/映射/回复/重试）。

    MQ 触发已上移到接口/Flow 级（决策 3.1 重写为 Flow 级模型 A）：
    消费者按 flow.{api_id}.queue 消费，收到消息驱动整条 Flow 编排。
    """
    api = await _get_api(session, api_id)
    if api.is_locked:
        raise BusinessException(PYFLOW_API_LOCKED, f"接口 {api.name} 已锁定，无法修改触发配置")
    # 服务端校验（决策 1/6/10）：非法配置拦在运行期之外
    validate_mq_config(req.mq_config, req.trigger_type)
    api.trigger_type = req.trigger_type
    api.mq_config = req.mq_config if req.trigger_type in ("mq", "both") else {}
    # HTTP 输入映射：仅保存 input_mapping 字段（白名单写入，避免存入无关字段）
    http_input_mapping = req.http_config.get("input_mapping", {}) if req.http_config else {}
    api.http_config = {"input_mapping": http_input_mapping} if http_input_mapping else {}
    await session.commit()
    await session.refresh(api)
    return api


# ── 接口加密保护管理 ──────────────────────────────────────────────────────────

@router.put("/api/portal/apis/{api_id}/encryption", response_model=ApiEncryptionKeyResponse)
async def update_api_encryption(
    api_id: str,
    req: ApiEncryptionRequest,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.EDITOR)),
):
    """开启/关闭接口加密保护（AES-256-GCM）。

    首次开启自动生成 32 字节密钥并随响应返回（请妥善保存并配置到调用方）；
    关闭不清空密钥，便于再次启用复用。
    """
    api = await _get_api(session, api_id)
    if api.is_locked:
        raise BusinessException(PYFLOW_API_LOCKED, f"接口 {api.name} 已锁定，无法修改加密配置")
    api.encryption_enabled = req.enabled
    api.require_encrypted_request = req.require_encrypted_request if req.enabled else False
    new_key_returned = False
    if req.enabled and not api.encryption_key:
        api.encryption_key = crypto.generate_key()
        new_key_returned = True
    await session.commit()
    await session.refresh(api)
    return ApiEncryptionKeyResponse(
        api_id=api.id,
        encryption_enabled=api.encryption_enabled,
        require_encrypted_request=api.require_encrypted_request,
        # 仅在本次新生成密钥时返回完整密钥，避免普通开关操作反复下发明文密钥
        encryption_key=api.encryption_key if new_key_returned else None,
        key_hint=api.encryption_key[:8] if api.encryption_key else None,
    )


@router.post("/api/portal/apis/{api_id}/encryption/rotate", response_model=ApiEncryptionKeyResponse)
async def rotate_api_encryption_key(
    api_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.EDITOR)),
):
    """轮转接口密钥并返回新密钥。

    轮转后旧密钥立即失效，所有调用方需同步更新为新密钥，否则解密失败。
    """
    api = await _get_api(session, api_id)
    if api.is_locked:
        raise BusinessException(PYFLOW_API_LOCKED, f"接口 {api.name} 已锁定，无法轮转密钥")
    api.encryption_key = crypto.generate_key()
    if not api.encryption_enabled:
        api.encryption_enabled = True
    await session.commit()
    await session.refresh(api)
    return ApiEncryptionKeyResponse(
        api_id=api.id,
        encryption_enabled=api.encryption_enabled,
        require_encrypted_request=api.require_encrypted_request,
        encryption_key=api.encryption_key,
        key_hint=api.encryption_key[:8],
    )


@router.get("/api/portal/apis/{api_id}/encryption/key", response_model=ApiEncryptionKeyResponse)
async def get_api_encryption_key(
    api_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.EDITOR)),
):
    """查看接口当前完整密钥（用于配置调用方；EDITOR 角色）。"""
    api = await _get_api(session, api_id)
    return ApiEncryptionKeyResponse(
        api_id=api.id,
        encryption_enabled=api.encryption_enabled,
        require_encrypted_request=api.require_encrypted_request,
        encryption_key=api.encryption_key,
        key_hint=api.encryption_key[:8] if api.encryption_key else None,
    )


@router.get("/api/portal/apis/{api_id}/docs")
async def get_api_docs(
    api_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    """生成接口文档（从关联流程和块自动提取端口信息）。"""
    api = await _get_api(session, api_id)
    flow_id = api.active_flow_id or api.flow_id
    flow = await session.get(Flow, flow_id)

    nodes = (await session.execute(
        select(FlowNode).where(FlowNode.flow_id == flow_id)
    )).scalars().all()
    edges = (await session.execute(
        select(FlowEdge).where(FlowEdge.flow_id == flow_id)
    )).scalars().all()

    # 收集所有块的端口信息作为文档
    block_docs = []
    for node in nodes:
        if node.block_id:
            block = await session.get(Block, node.block_id)
            if block:
                block_docs.append({
                    "node_id": node.id,
                    "block_id": block.id,
                    "block_name": block.name,
                    "description": block.description,
                    "input_ports": block.input_ports,
                    "output_ports": block.output_ports,
                    "entrypoints": block.entrypoints,
                    # 该节点实际调用的入口函数（默认 run）
                    "entrypoint": (node.config or {}).get("entrypoint") or "run",
                })

    # 接口级 MQ 触发文档（trigger_type 为 mq/both 时非空），用流程入口块端口生成示例消息体
    # 入口节点优先级：API 级 > Flow 级
    effective_entry = api.entry_node_id or (flow.entry_node_id if flow else None)
    entry_ports = _entry_input_ports(nodes, edges, block_docs, effective_entry)
    mq_invocation = build_mq_invocation(api, entry_ports)

    return {
        "api_id": api_id,
        "name": api.name,
        "description": api.description,
        "path": f"{settings.public_api_prefix}/api/public/{api.path}",
        "method": "POST",
        "status": api.status,
        "trigger_type": api.trigger_type,
        "entry_node_id": api.entry_node_id,
        "entrypoint": api.entrypoint,
        "entrypoint_map": api.entrypoint_map or {},
        "flow_id": flow_id,
        "flow_name": flow.name if flow else "未知",
        "node_count": len(nodes),
        "edge_count": len(edges),
        "blocks": block_docs,
        "request_example": (
            {"inputs": "<base64_aes_gcm_ciphertext>", "encrypted": True}
            if api.encryption_enabled
            else {"inputs": {}}
        ),
        "response_example": (
            {"outputs": "<base64_aes_gcm_ciphertext>", "encrypted": True, "status": "succeeded"}
            if api.encryption_enabled
            else {"outputs": {}, "flow_run_id": "uuid", "status": "succeeded"}
        ),
        # ── 加密保护（接口级）──
        "encryption_enabled": api.encryption_enabled,
        "require_encrypted_request": api.require_encrypted_request,
        # ── MQ 触发支持（接口级）──
        "mq_supported": mq_invocation is not None,
        "mq_invocation": mq_invocation,
        # ── 开发者文档（可编辑） ──
        "remarks": api.remarks or "",
        "sample_request": api.sample_request or "",
        "sample_response": api.sample_response or "",
        "changelog": api.changelog or "",
        "is_locked": api.is_locked,
    }


@router.put("/api/portal/apis/{api_id}/remarks", response_model=ApiResponse)
async def update_api_remarks(
    api_id: str,
    req: ApiRemarksRequest,
    session: AsyncSession = Depends(get_session),
    login_id: str = Depends(require_role(Role.EDITOR)),
):
    """更新接口的开发者文档（备注、示例请求/响应、变更日志）。接口负责人或管理员可操作。"""
    api = await _get_api(session, api_id)
    if api.owner_login_id != login_id:
        from app.auth.rbac import Role, get_user_roles
        roles = await get_user_roles(login_id, session)
        if max(roles) < Role.ADMIN:
            raise BusinessException(PYFLOW_AUTH_FORBIDDEN, "只有接口负责人或管理员可编辑文档")
    if req.remarks is not None:
        api.remarks = req.remarks
    if req.sample_request is not None:
        api.sample_request = req.sample_request
    if req.sample_response is not None:
        api.sample_response = req.sample_response
    if req.changelog is not None:
        api.changelog = req.changelog
    await session.commit()
    await session.refresh(api)
    return api


def _entry_input_ports(
    nodes: list[Any],
    edges: list[Any],
    block_docs: list[dict[str, Any]],
    entry_node_id: str | None = None,
) -> list[Any]:
    """流程入口块的 input_ports 合集，用于生成 MQ 示例消息体。

    指定了 entry_node_id 时仅用该节点端口；否则取无入边的所有根节点。
    """
    if entry_node_id:
        entry_block_ids = {
            n.block_id for n in nodes
            if n.block_id and n.id == entry_node_id
        }
    else:
        targets = {e.target_node_id for e in edges}
        entry_block_ids = {
            n.block_id for n in nodes if n.block_id and n.id not in targets
        }
    ports: list[Any] = []
    for doc in block_docs:
        if doc["block_id"] in entry_block_ids:
            ports.extend(doc.get("input_ports") or [])
    return ports


# ── 流程入口函数查询 ──────────────────────────────────────────────────────────

@router.get("/api/portal/flows/{flow_id}/entrypoints")
async def get_flow_entrypoints(
    flow_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.VIEWER)),
):
    """查询指定流程中所有块的可用入口函数，用于发布对话框/MQ 配置时选择绑定函数。

    返回：
    - nodes: 每个节点当前配置的入口函数及所在块可用函数列表
    - all_entrypoints: 全流程所有块入口函数的去重并集（含 "run"）
    """
    flow = await session.get(Flow, flow_id)
    if flow is None:
        raise BusinessException(PYFLOW_BLOCK_NOT_FOUND, flow_id)

    nodes_rows = (await session.execute(
        select(FlowNode).where(FlowNode.flow_id == flow_id)
    )).scalars().all()

    block_ids = {n.block_id for n in nodes_rows if n.block_id}
    block_map: dict[str, Block] = {}
    if block_ids:
        rows = (await session.execute(
            select(Block).where(Block.id.in_(block_ids))
        )).scalars().all()
        block_map = {b.id: b for b in rows}

    nodes_info = []
    all_names: set[str] = {"run"}
    for node in nodes_rows:
        if not node.block_id:
            continue
        block = block_map.get(node.block_id)
        if not block:
            continue
        eps = [ep.get("name") for ep in (block.entrypoints or []) if ep.get("name")]
        if not eps:
            eps = ["run"]
        all_names.update(eps)
        nodes_info.append({
            "node_id": node.id,
            "block_id": block.id,
            "block_name": block.name,
            "is_entry": flow.entry_node_id == node.id,
            "configured_entrypoint": (node.config or {}).get("entrypoint") or "run",
            "available_entrypoints": [
                {"name": ep.get("name"), "description": ep.get("description", "")}
                for ep in (block.entrypoints or [])
            ] if block.entrypoints else [{"name": "run", "description": ""}],
        })

    # 保持 run 始终排第一
    all_sorted = ["run"] + sorted(all_names - {"run"})
    return {
        "flow_id": flow_id,
        "flow_name": flow.name,
        "entry_node_id": flow.entry_node_id,
        "nodes": nodes_info,
        "all_entrypoints": all_sorted,
        "has_multiple": len(all_names) > 1,
    }


# ── 公开调用入口 ───────────────────────────────────────────────────────────────

@router.post("/api/public/{path}")
async def invoke_api(
    path: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """公开调用接口（无需登录态校验；限流 + 降级 + 访问认证在此处理）。"""
    from app.core.auth_validator import validate_request as _validate_auth
    from app.models.execution import ExecutionRecord
    import secrets as _secrets

    api = await _get_api_by_path(session, path)

    if api.status != "active":
        raise BusinessException(PYFLOW_API_NOT_FOUND, f"接口 {path} 当前状态为 {api.status}")

    # 读取原始请求体（供 auth 校验和后续解析共用）
    raw_body: bytes = b""
    try:
        raw_body = await request.body()
    except Exception:
        pass

    # 访问认证（HMAC-SHA256）：开启后无有效签名直接拒绝并记录失败执行
    if api.auth_enabled and api.auth_secret:
        ts_header = request.headers.get("X-FlowHub-Timestamp")
        token_header = request.headers.get("X-FlowHub-Token")
        ok, reason = _validate_auth(api.auth_secret, path, raw_body, ts_header, token_header)
        if not ok:
            import logging as _logging
            _logging.getLogger("pyflow.auth").warning(
                "接口 %s 认证失败：%s  ts=%s  ip=%s",
                path, reason, ts_header, request.client.host if request.client else "unknown",
            )
            # 记录认证失败执行记录（显示在看板"最近执行"中）
            fail_rec = ExecutionRecord(
                id=_secrets.token_hex(18)[:36],
                block_id=None,
                flow_run_id=None,
                login_id=request.client.host if request.client else "unknown",
                status="auth_failed",
                inputs={"path": path, "reason": reason},
                output=None,
                stdout="",
                stderr=f"认证失败：{reason}",
                error_code=41817,
                duration_ms=0,
            )
            session.add(fail_rec)
            api.total_calls += 1
            api.error_calls += 1
            await session.commit()
            raise BusinessException(PYFLOW_API_AUTH_FAILED, reason)

    # 降级：返回 fallback
    if api.degradation_enabled and api.degradation_fallback:
        api.total_calls += 1
        api.success_calls += 1
        await session.commit()
        return {"degraded": True, "data": api.degradation_fallback}

    # 限流检查
    _check_rate_limit(api)

    body: dict[str, Any] = {}
    try:
        body = json.loads(raw_body) if raw_body else {}
    except Exception:
        body = {}
    # 加密保护 + HTTP input_mapping：从请求体解出明文 inputs
    inputs = _resolve_inputs(api, body)

    flow_id = api.active_flow_id or api.flow_id
    nodes_rows = (await session.execute(
        select(FlowNode).where(FlowNode.flow_id == flow_id)
    )).scalars().all()
    edges_rows = (await session.execute(
        select(FlowEdge).where(FlowEdge.flow_id == flow_id)
    )).scalars().all()

    nodes = [
        {"id": n.id, "node_type": n.node_type, "block_id": n.block_id,
         "config": n.config, "position": n.position}
        for n in nodes_rows
    ]
    edges = [
        {"id": e.id, "source_node_id": e.source_node_id,
         "target_node_id": e.target_node_id,
         "source_port": e.source_port, "target_port": e.target_port}
        for e in edges_rows
    ]

    # 入口节点优先级：API 级 entry_node_id > Flow 级 entry_node_id（兼容历史数据）
    flow_obj = await session.get(Flow, flow_id)
    effective_entry_node_id = (
        api.entry_node_id
        or (flow_obj.entry_node_id if flow_obj else None)
    )
    nodes, edges = select_entry_subgraph(nodes, edges, effective_entry_node_id)

    # k8s flow_mode 已部署时，直接调用 FlowRunner Pod /run，省去控制面逐块执行
    flow_runner_svc = await _resolve_flow_runner_service(session, flow_id)
    if flow_runner_svc:
        start_ts = time.time()
        try:
            runner_result = await _call_flow_runner(flow_runner_svc, inputs, effective_entry_node_id)
            if runner_result.get("status") == "failed":
                raise BusinessException(PYFLOW_EXEC_SANDBOX_ERROR, runner_result.get("error", "flow_runner failed")[:500])
            elapsed = (time.time() - start_ts) * 1000
            api.total_calls += 1
            api.success_calls += 1
            n = api.total_calls
            api.avg_latency_ms = (api.avg_latency_ms * (n - 1) + elapsed) / n
            await session.commit()
            outputs = runner_result.get("outputs", {})
            payload, encrypted = _maybe_encrypt_outputs(api, outputs)
            return {"outputs": payload, "encrypted": encrypted, "status": "succeeded", "latency_ms": round(elapsed, 2)}
        except BusinessException:
            api.total_calls += 1
            api.error_calls += 1
            await session.commit()
            raise
        except Exception as exc:
            api.total_calls += 1
            api.error_calls += 1
            await session.commit()
            raise BusinessException(PYFLOW_EXEC_SANDBOX_ERROR, str(exc)[:500]) from exc

    # 一次 IN 查询批量装载所有块，避免按节点 N+1 逐个 session.get
    block_ids = {n["block_id"] for n in nodes if n.get("block_id")}
    block_cache: dict[str, Block] = {}
    if block_ids:
        rows = (await session.execute(
            select(Block).where(Block.id.in_(block_ids))
        )).scalars().all()
        block_cache = {b.id: b for b in rows}
        missing = block_ids - block_cache.keys()
        if missing:
            raise BusinessException(PYFLOW_BLOCK_NOT_FOUND, next(iter(missing)))

    # k8s 模式且该流程已部署时，复用常驻 invoke Service（warm Pod），消除每块 Job 冷启动
    block_service = await _resolve_block_services(session, flow_id)

    start_ts = time.time()
    try:
        async def node_executor(node: dict, node_inputs: dict) -> dict:
            block_id = node.get("block_id")
            if not block_id:
                return {}
            block = block_cache[block_id]
            # 节点级 entrypoint_map 优先，其次 API 级全局，再次节点配置，最后默认 run
            entrypoint = _resolve_node_entrypoint(api, node)
            record = await execute_block(
                session, block_id=block.id, code=block.draft_code or "",
                inputs=node_inputs, login_id=api.owner_login_id,
                entrypoint=entrypoint,
                invoke_service=block_service.get(block.id),
            )
            if record.status != "success":
                detail = (record.stderr or "block execution failed").strip()[:500]
                raise BusinessException(PYFLOW_EXEC_SANDBOX_ERROR, detail)
            return record.output if isinstance(record.output, dict) else {"value": record.output}

        async def checkpoint(node_id: str, status: str, output: dict) -> None:
            pass

        outputs = await run_flow(nodes, edges, inputs, node_executor, checkpoint)
        elapsed = (time.time() - start_ts) * 1000

        api.total_calls += 1
        api.success_calls += 1
        # 滚动平均
        n = api.total_calls
        api.avg_latency_ms = (api.avg_latency_ms * (n - 1) + elapsed) / n
        await session.commit()

        # 加密保护：开启时将 outputs 加密为密文字符串并标记 encrypted=true
        payload, encrypted = _maybe_encrypt_outputs(api, outputs)
        return {
            "outputs": payload,
            "encrypted": encrypted,
            "status": "succeeded",
            "latency_ms": round(elapsed, 2),
        }

    except BusinessException:
        api.total_calls += 1
        api.error_calls += 1
        await session.commit()
        raise
    except Exception as exc:
        api.total_calls += 1
        api.error_calls += 1
        await session.commit()
        raise BusinessException(PYFLOW_EXEC_SANDBOX_ERROR, str(exc)[:500]) from exc


# ── 公开调用入口（流式 SSE）─────────────────────────────────────────────────────

def _terminal_node_ids(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> set[str]:
    """终止节点（无出边的 sink 节点）id 集合，其输出即流程"最终输出"，按流式推送。"""
    sources = {e["source_node_id"] for e in edges}
    return {n["id"] for n in nodes if n["id"] not in sources}


def _sse(event: str, data: dict[str, Any]) -> str:
    """格式化一个 SSE 帧（``event:`` + ``data:`` 两行 + 空行分隔）。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@router.post("/api/public/{path}/stream")
async def invoke_api_stream(
    path: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """流式调用接口（SSE）：终止节点用户代码 ``yield`` 的内容实时穿透为 ``event: data``。

    前置校验（状态/降级/限流/装载流程）与 :func:`invoke_api` 一致，且在进入流式响应前完成，
    以便仍能返回标准 HTTP 错误；进入流后统一以 ``event: error`` 反馈异常。
    """
    api = await _get_api_by_path(session, path)

    if api.status != "active":
        raise BusinessException(PYFLOW_API_NOT_FOUND, f"接口 {path} 当前状态为 {api.status}")

    # 限流检查（降级在流内处理：降级直接产出单个 result 事件）
    _check_rate_limit(api)

    body: dict[str, Any] = {}
    try:
        body = await request.json()
    except Exception:
        pass
    # 加密保护：进入流式响应前先完成 inputs 解密，使强制加密 / 解密失败仍返回标准 HTTP 错误
    inputs = _resolve_inputs(api, body)

    flow_id = api.active_flow_id or api.flow_id
    nodes_rows = (await session.execute(
        select(FlowNode).where(FlowNode.flow_id == flow_id)
    )).scalars().all()
    edges_rows = (await session.execute(
        select(FlowEdge).where(FlowEdge.flow_id == flow_id)
    )).scalars().all()

    nodes = [
        {"id": n.id, "node_type": n.node_type, "block_id": n.block_id,
         "config": n.config, "position": n.position}
        for n in nodes_rows
    ]
    edges = [
        {"id": e.id, "source_node_id": e.source_node_id,
         "target_node_id": e.target_node_id,
         "source_port": e.source_port, "target_port": e.target_port}
        for e in edges_rows
    ]

    # 入口节点优先级：API 级 entry_node_id > Flow 级 entry_node_id（兼容历史数据）
    flow_obj = await session.get(Flow, flow_id)
    effective_entry_node_id = (
        api.entry_node_id
        or (flow_obj.entry_node_id if flow_obj else None)
    )
    nodes, edges = select_entry_subgraph(nodes, edges, effective_entry_node_id)

    block_ids = {n["block_id"] for n in nodes if n.get("block_id")}
    block_cache: dict[str, Block] = {}
    if block_ids:
        rows = (await session.execute(
            select(Block).where(Block.id.in_(block_ids))
        )).scalars().all()
        block_cache = {b.id: b for b in rows}
        missing = block_ids - block_cache.keys()
        if missing:
            raise BusinessException(PYFLOW_BLOCK_NOT_FOUND, next(iter(missing)))

    terminal_ids = _terminal_node_ids(nodes, edges)
    # 非终止节点可复用常驻 invoke Service（终止节点需流式，仍走 Job 流式路径）
    block_service = await _resolve_block_services(session, flow_id)

    async def _event_stream() -> Any:
        yield _sse("running", {"status": "running"})

        # 降级：不执行流程，直接产出 fallback（前置已完成，无并发，安全操作 session）
        if api.degradation_enabled and api.degradation_fallback:
            api.total_calls += 1
            api.success_calls += 1
            await session.commit()
            yield _sse("result", {
                "degraded": True, "data": api.degradation_fallback, "status": "succeeded",
            })
            yield _sse("done", {})
            return

        # run_flow 在独立任务内执行整个 DAG；终止节点的 chunk 经 event_queue 实时回送本生成器。
        # 注意：流式期间本生成器不触碰 session（仅 run_task 内顺序使用），避免 AsyncSession 并发冲突。
        event_queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        start_ts = time.time()

        async def node_executor(node: dict, node_inputs: dict) -> dict:
            block_id = node.get("block_id")
            if not block_id:
                return {}
            block = block_cache[block_id]
            entrypoint = _resolve_node_entrypoint(api, node)

            # 非终止节点：常规一次性执行（命中部署时复用常驻 invoke Service）
            if node["id"] not in terminal_ids:
                record = await execute_block(
                    session, block_id=block.id, code=block.draft_code or "",
                    inputs=node_inputs, login_id=api.owner_login_id, entrypoint=entrypoint,
                    invoke_service=block_service.get(block.id),
                )
                if record.status != "success":
                    detail = (record.stderr or "block execution failed").strip()[:500]
                    raise BusinessException(PYFLOW_EXEC_SANDBOX_ERROR, detail)
                return record.output if isinstance(record.output, dict) else {"value": record.output}

            # 终止节点：流式执行，chunk 实时入队，末尾 result 作为节点输出
            final_output: dict[str, Any] = {}
            async for event in execute_block_stream(
                session, block_id=block.id, code=block.draft_code or "",
                inputs=node_inputs, login_id=api.owner_login_id, entrypoint=entrypoint,
            ):
                if event.get("type") == "chunk":
                    await event_queue.put(("data", event.get("data")))
                else:
                    if event.get("error"):
                        detail = str(event.get("error")).strip()[:500]
                        raise BusinessException(PYFLOW_EXEC_SANDBOX_ERROR, detail)
                    out = event.get("output")
                    final_output = out if isinstance(out, dict) else {"value": out}
            return final_output

        async def checkpoint(node_id: str, status: str, output: dict) -> None:
            pass

        async def _run() -> None:
            try:
                outputs = await run_flow(nodes, edges, inputs, node_executor, checkpoint)
                await event_queue.put(("outputs", outputs))
            except BusinessException as exc:
                await event_queue.put(("error", exc.detail or f"{exc.code}:{exc.msg_key}"))
            except Exception as exc:  # noqa: BLE001
                await event_queue.put(("error", str(exc)[:500]))
            finally:
                await event_queue.put(("__end__", None))

        run_task = asyncio.create_task(_run())
        final_outputs: dict[str, Any] | None = None
        error_detail: str | None = None
        try:
            while True:
                kind, val = await event_queue.get()
                if kind == "__end__":
                    break
                if kind == "data":
                    yield _sse("data", {"chunk": val})
                elif kind == "outputs":
                    final_outputs = val
                elif kind == "error":
                    error_detail = val
        finally:
            await run_task

        elapsed = (time.time() - start_ts) * 1000
        if error_detail is not None:
            api.total_calls += 1
            api.error_calls += 1
            await session.commit()
            yield _sse("error", {"error": error_detail})
            yield _sse("done", {})
            return

        api.total_calls += 1
        api.success_calls += 1
        n = api.total_calls
        api.avg_latency_ms = (api.avg_latency_ms * (n - 1) + elapsed) / n
        await session.commit()
        # 加密保护：仅最终 result 的 outputs 加密；中间 data chunk 不加密（保持实时性）
        result_payload, encrypted = _maybe_encrypt_outputs(api, final_outputs)
        yield _sse("result", {
            "outputs": result_payload, "encrypted": encrypted,
            "status": "succeeded", "latency_ms": round(elapsed, 2),
        })
        yield _sse("done", {})

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # 关闭反代缓冲（nginx），确保 chunk 即时下发
            "X-Accel-Buffering": "no",
        },
    )


# ── 访问认证（HMAC-SHA256）管理 ───────────────────────────────────────────────

@router.post("/api/portal/apis/{api_id}/auth", response_model=ApiAuthResponse)
async def generate_auth_secret(
    api_id: str,
    req: ApiAuthToggleRequest,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.EDITOR)),
):
    """生成/重置 HMAC 签名密钥，并控制开关。

    首次调用或重置时生成新密钥（完整密钥仅此一次返回）。关闭时仅禁用校验，不清除密钥。
    """
    import secrets as _secrets
    api = await _get_api(session, api_id)
    if api.is_locked:
        raise BusinessException(PYFLOW_API_LOCKED, f"接口 {api.name} 已锁定")
    new_secret: str | None = None
    if req.enabled and not api.auth_secret:
        # 首次开启：生成 256-bit 密钥
        new_secret = _secrets.token_hex(32)
        api.auth_secret = new_secret
    api.auth_enabled = req.enabled
    await session.commit()
    await session.refresh(api)
    return ApiAuthResponse(
        api_id=api.id,
        auth_enabled=api.auth_enabled,
        secret_hint=api.auth_secret[:8] if api.auth_secret else None,
        auth_secret=new_secret,  # 仅首次返回完整密钥
    )


@router.post("/api/portal/apis/{api_id}/auth/rotate", response_model=ApiAuthResponse)
async def rotate_auth_secret(
    api_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.EDITOR)),
):
    """轮转 HMAC 签名密钥（旧密钥立即失效，返回新密钥）。"""
    import secrets as _secrets
    api = await _get_api(session, api_id)
    if api.is_locked:
        raise BusinessException(PYFLOW_API_LOCKED, f"接口 {api.name} 已锁定")
    new_secret = _secrets.token_hex(32)
    api.auth_secret = new_secret
    api.auth_enabled = True
    await session.commit()
    await session.refresh(api)
    return ApiAuthResponse(
        api_id=api.id,
        auth_enabled=True,
        secret_hint=new_secret[:8],
        auth_secret=new_secret,
    )


@router.get("/api/portal/apis/{api_id}/auth", response_model=ApiAuthResponse)
async def get_auth_info(
    api_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_role(Role.EDITOR)),
):
    """查看访问认证状态（不返回完整密钥）。"""
    api = await _get_api(session, api_id)
    return ApiAuthResponse(
        api_id=api.id,
        auth_enabled=api.auth_enabled,
        secret_hint=api.auth_secret[:8] if api.auth_secret else None,
        auth_secret=None,
    )
