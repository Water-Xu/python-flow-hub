"""版本快照创建与 MinIO 大字段存取（决策 8）。

双写一致性（先 MinIO 后 DB + 对账）：
1. 先写 MinIO（幂等：对象 key 含 version_id，可重复 PUT），校验返回 sha256；
2. 再写 DB 指针（带 content_sha256），DB 事务提交成功才算"版本发布完成"，is_stable 才置位；
3. DB 提交失败 → MinIO 对象成为孤儿，由对账任务清理；绝不出现悬挂指针；
4. 读路径按 content_sha256 校验，不一致即报 PYFLOW_VERSION_NOT_STABLE。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage.minio_client import ObjectStorage, get_storage, sha256_hex
from app.errors import PYFLOW_VERSION_NOT_STABLE, BusinessException
from app.models.base_mixin import gen_uuid
from app.models.block import Block
from app.models.flow import Flow
from app.models.version import BlockVersion, FlowVersion
from app.observability.logging import get_logger

logger = get_logger("pyflow.version")


def requirements_hash(requirements_text: str) -> str:
    """归一化（去空行/排序）后取 sha256，用于镜像分层缓存键（决策 11）。"""
    lines = sorted(
        line.strip()
        for line in requirements_text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _block_key(block_id: str, version_id: str, filename: str) -> str:
    return f"blocks/{block_id}/{version_id}/{filename}"


def _flow_key(flow_id: str, version_id: str) -> str:
    return f"flows/{flow_id}/{version_id}/snapshot.json"


async def create_block_version(
    session: AsyncSession,
    block: Block,
    *,
    version_tag: str,
    commit_message: str = "",
    login_id: str = "",
    requirements_text: str = "",
    set_stable: bool = True,
    storage: ObjectStorage | None = None,
    auto_commit: bool = True,
) -> BlockVersion:
    """创建 Block 版本快照：先写 MinIO，再写 DB 指针。"""
    storage = storage or get_storage()
    version_id = gen_uuid()

    code = block.draft_code or ""
    code_bytes = code.encode("utf-8")
    content_sha = sha256_hex(code_bytes)

    # 1) 先写 MinIO（幂等 PUT）
    code_key = _block_key(block.id, version_id, "code.py")
    await storage.put(code_key, code_bytes, "text/x-python")

    req_key: str | None = None
    req_hash = block.requirements_hash or ""
    if requirements_text.strip():
        from app.config import get_settings
        from app.core.k8s.requirements_policy import validate_requirements

        validate_requirements(requirements_text, get_settings())
        req_key = _block_key(block.id, version_id, "requirements.txt")
        await storage.put(req_key, requirements_text.encode("utf-8"), "text/plain")
        req_hash = requirements_hash(requirements_text)

    nb_key: str | None = None
    if block.draft_notebook:
        nb_key = _block_key(block.id, version_id, "notebook.ipynb")
        nb_bytes = json.dumps(block.draft_notebook, ensure_ascii=False).encode("utf-8")
        await storage.put(nb_key, nb_bytes, "application/json")

    # 2) 再写 DB 指针
    version = BlockVersion(
        id=version_id,
        block_id=block.id,
        version_tag=version_tag,
        commit_message=commit_message,
        created_by=login_id,
        code_path=code_key,
        requirements_path=req_key,
        notebook_path=nb_key,
        input_ports=list(block.input_ports or []),
        output_ports=list(block.output_ports or []),
        requirements_hash=req_hash,
        content_sha256=content_sha,
        is_stable=False,
    )
    session.add(version)
    await session.flush()

    if set_stable:
        # 清除旧 stable 标记
        rows = (await session.execute(
            select(BlockVersion).where(
                BlockVersion.block_id == block.id, BlockVersion.is_stable.is_(True)
            )
        )).scalars().all()
        for r in rows:
            r.is_stable = False
        version.is_stable = True
        block.stable_version_id = version.id
        if req_hash:
            block.requirements_hash = req_hash

    await session.flush()
    if auto_commit:
        await session.commit()
    await session.refresh(version)
    logger.info("block_version_created", block_id=block.id, version_id=version_id, tag=version_tag)
    return version


async def delete_block_with_versions(
    session: AsyncSession,
    block: Block,
    *,
    storage: ObjectStorage | None = None,
) -> None:
    """删除 Block 及其全部版本快照（含 MinIO 对象）。调用方负责 commit。"""
    storage = storage or get_storage()
    versions = (await session.execute(
        select(BlockVersion).where(BlockVersion.block_id == block.id)
    )).scalars().all()
    for v in versions:
        # 清理 MinIO 对象（best-effort，失败不阻断）
        for key in [v.code_path, v.requirements_path, v.notebook_path]:
            if key:
                try:
                    await storage.delete(key)
                except Exception:  # noqa: BLE001
                    pass
        await session.delete(v)
    await session.delete(block)
    logger.info("block_deleted_with_versions", block_id=block.id, versions=len(versions))


async def get_block_version_content(
    version: BlockVersion, storage: ObjectStorage | None = None
) -> dict[str, Any]:
    """读取版本内容并按 content_sha256 校验，损坏即报 PYFLOW_VERSION_NOT_STABLE。"""
    storage = storage or get_storage()
    code_bytes = await storage.get(version.code_path)
    if sha256_hex(code_bytes) != version.content_sha256:
        raise BusinessException(
            PYFLOW_VERSION_NOT_STABLE, f"content sha mismatch for version {version.id}"
        )
    result: dict[str, Any] = {"code": code_bytes.decode("utf-8")}
    if version.requirements_path:
        result["requirements"] = (await storage.get(version.requirements_path)).decode("utf-8")
    if version.notebook_path:
        result["notebook"] = json.loads((await storage.get(version.notebook_path)).decode("utf-8"))
    return result


async def create_flow_version(
    session: AsyncSession,
    flow: Flow,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    version_tag: str,
    commit_message: str = "",
    login_id: str = "",
    set_stable: bool = True,
    storage: ObjectStorage | None = None,
) -> FlowVersion:
    """创建 Flow 版本快照：完整 JSON（节点 + 边 + 分支配置）存 MinIO。"""
    storage = storage or get_storage()
    version_id = gen_uuid()

    snapshot = {
        "flow_id": flow.id,
        "name": flow.name,
        "description": flow.description,
        "nodes": nodes,
        "edges": edges,
        "tree": flow.tree or {},
        "resources": flow.resources or {},
    }
    snapshot_bytes = json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8")
    content_sha = sha256_hex(snapshot_bytes)
    snapshot_key = _flow_key(flow.id, version_id)
    await storage.put(snapshot_key, snapshot_bytes, "application/json")

    version = FlowVersion(
        id=version_id,
        flow_id=flow.id,
        version_tag=version_tag,
        commit_message=commit_message,
        created_by=login_id,
        snapshot_path=snapshot_key,
        content_sha256=content_sha,
        node_count=len(nodes),
        edge_count=len(edges),
        is_stable=False,
    )
    session.add(version)
    await session.flush()

    if set_stable:
        rows = (await session.execute(
            select(FlowVersion).where(
                FlowVersion.flow_id == flow.id, FlowVersion.is_stable.is_(True)
            )
        )).scalars().all()
        for r in rows:
            r.is_stable = False
        version.is_stable = True
        flow.stable_version_id = version.id

    await session.commit()
    await session.refresh(version)
    logger.info("flow_version_created", flow_id=flow.id, version_id=version_id, tag=version_tag)
    return version


async def get_flow_snapshot(
    version: FlowVersion, storage: ObjectStorage | None = None
) -> dict[str, Any]:
    storage = storage or get_storage()
    raw = await storage.get(version.snapshot_path)
    if sha256_hex(raw) != version.content_sha256:
        raise BusinessException(
            PYFLOW_VERSION_NOT_STABLE, f"content sha mismatch for flow version {version.id}"
        )
    return json.loads(raw.decode("utf-8"))


async def reconcile_orphans(
    session: AsyncSession, storage: ObjectStorage | None = None
) -> dict[str, int]:
    """对账任务：扫描 MinIO 无对应 DB 记录的对象 + DB 指针对象缺失/sha 不符。

    返回 {orphan_objects, missing_objects, corrupted}，供 Prometheus 上报与告警。
    """
    storage = storage or get_storage()
    block_versions = (await session.execute(select(BlockVersion))).scalars().all()
    flow_versions = (await session.execute(select(FlowVersion))).scalars().all()

    known_keys: set[str] = set()
    missing = 0
    corrupted = 0
    for bv in block_versions:
        for key in (bv.code_path, bv.requirements_path, bv.notebook_path):
            if key:
                known_keys.add(key)
        if not await storage.exists(bv.code_path):
            missing += 1
        else:
            if sha256_hex(await storage.get(bv.code_path)) != bv.content_sha256:
                corrupted += 1
    for fv in flow_versions:
        known_keys.add(fv.snapshot_path)
        if not await storage.exists(fv.snapshot_path):
            missing += 1

    all_keys = set(await storage.list_keys("blocks/")) | set(await storage.list_keys("flows/"))
    orphan = len(all_keys - known_keys)

    try:
        from app.observability.metrics import VERSION_RECONCILE

        VERSION_RECONCILE.labels(kind="orphan_objects").set(orphan)
        VERSION_RECONCILE.labels(kind="missing_objects").set(missing)
        VERSION_RECONCILE.labels(kind="corrupted").set(corrupted)
    except Exception:  # noqa: BLE001 指标上报失败不影响对账主流程
        pass

    logger.info("version_reconcile", orphan=orphan, missing=missing, corrupted=corrupted)
    return {"orphan_objects": orphan, "missing_objects": missing, "corrupted": corrupted}
