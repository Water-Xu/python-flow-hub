"""DAG 无环校验 + 拓扑排序（决策 10）。

纯逻辑已下沉到 pyflow_runtime.flow_dag（控制面与 runner 共享单一来源）；
本模块仅把 DagError 翻译为平台错误码 PYFLOW_FLOW_DAG_INVALID。
"""

from __future__ import annotations

from typing import Any

from pyflow_runtime.flow_dag import DagError
from pyflow_runtime.flow_dag import topological_order as _topological_order

from app.errors import PYFLOW_FLOW_DAG_INVALID, BusinessException


def topological_order(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[str]:
    """返回拓扑序节点 ID 列表；成环抛 PYFLOW_FLOW_DAG_INVALID。"""
    try:
        return _topological_order(nodes, edges)
    except DagError as exc:
        raise BusinessException(PYFLOW_FLOW_DAG_INVALID, str(exc)) from exc


def validate_dag(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    """仅校验无环（保存/发布时）。"""
    topological_order(nodes, edges)
