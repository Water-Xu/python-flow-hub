"""DAG 无环校验 + 拓扑排序（决策 10）。

保存/发布/部署 Flow 时强制做拓扑无环校验（含分支节点与回边），成环返回 PYFLOW_FLOW_DAG_INVALID。
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from app.errors import PYFLOW_FLOW_DAG_INVALID, BusinessException


def topological_order(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[str]:
    """返回拓扑序节点 ID 列表；成环抛 PYFLOW_FLOW_DAG_INVALID。"""
    node_ids = {n["id"] for n in nodes}
    indegree: dict[str, int] = {nid: 0 for nid in node_ids}
    adj: dict[str, list[str]] = defaultdict(list)

    for e in edges:
        src, dst = e["source_node_id"], e["target_node_id"]
        if src not in node_ids or dst not in node_ids:
            raise BusinessException(PYFLOW_FLOW_DAG_INVALID, "edge references unknown node")
        adj[src].append(dst)
        indegree[dst] += 1

    queue = deque(nid for nid, d in indegree.items() if d == 0)
    order: list[str] = []
    while queue:
        cur = queue.popleft()
        order.append(cur)
        for nxt in adj[cur]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    if len(order) != len(node_ids):
        raise BusinessException(PYFLOW_FLOW_DAG_INVALID, "flow graph contains a cycle")
    return order


def validate_dag(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    """仅校验无环（保存/发布时）。"""
    topological_order(nodes, edges)
