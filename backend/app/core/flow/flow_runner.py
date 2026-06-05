"""DAG 拓扑排序执行（dev-local 同步编排，决策 10 等价路径）。

纯编排逻辑已下沉到 pyflow_runtime.flow_dag（控制面与 runner 共享单一来源）；
本模块仅把 DagError 翻译为平台错误码 PYFLOW_FLOW_DAG_INVALID，保持对外签名不变。
"""

from __future__ import annotations

from typing import Any

from pyflow_runtime.flow_dag import Checkpoint, DagError, NodeExecutor
from pyflow_runtime.flow_dag import run_flow as _run_flow

from app.errors import PYFLOW_FLOW_DAG_INVALID, BusinessException

__all__ = ["run_flow", "NodeExecutor", "Checkpoint"]


async def run_flow(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    initial_inputs: dict[str, Any],
    node_executor: NodeExecutor,
    checkpoint: Checkpoint | None = None,
    *,
    prior_outputs: dict[str, dict[str, Any]] | None = None,
    prior_active_ports: dict[str, str] | None = None,
    prior_skipped: set[str] | None = None,
    entry_node_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    """执行整流，返回 {node_id: output}（成环翻译为 PYFLOW_FLOW_DAG_INVALID）。"""
    try:
        return await _run_flow(
            nodes,
            edges,
            initial_inputs,
            node_executor,
            checkpoint,
            prior_outputs=prior_outputs,
            prior_active_ports=prior_active_ports,
            prior_skipped=prior_skipped,
            entry_node_id=entry_node_id,
        )
    except DagError as exc:
        raise BusinessException(PYFLOW_FLOW_DAG_INVALID, str(exc)) from exc
