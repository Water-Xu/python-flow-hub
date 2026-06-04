"""DAG 拓扑排序执行（dev-local 同步编排，决策 10 等价路径）。

按 DAG 拓扑序在控制面用 docker_executor 依次执行各 Block，内存中传递 output→input，
条件分支由 condition_executor 在控制面求值后只激活命中路径。
每个节点完成即 checkpoint 落库（FlowRun）。
"""

from __future__ import annotations

from typing import Any, Callable, Awaitable

from app.core.flow.condition_executor import resolve_branch
from app.core.flow.dag import topological_order

# 节点执行回调：(node, inputs) -> output dict
NodeExecutor = Callable[[dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any]]]
# checkpoint 回调：(node_id, status, output) -> None
Checkpoint = Callable[[str, str, dict[str, Any]], Awaitable[None]]


async def run_flow(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    initial_inputs: dict[str, Any],
    node_executor: NodeExecutor,
    checkpoint: Checkpoint | None = None,
) -> dict[str, dict[str, Any]]:
    """执行整流，返回 {node_id: output}。"""
    order = topological_order(nodes, edges)
    node_map = {n["id"]: n for n in nodes}

    # 入边：target -> [(source, source_port, target_port)]
    in_edges: dict[str, list[dict[str, Any]]] = {nid: [] for nid in node_map}
    for e in edges:
        in_edges[e["target_node_id"]].append(e)

    outputs: dict[str, dict[str, Any]] = {}
    # 被分支节点剪枝掉的端口：{node_id: 命中端口}，决定下游是否激活
    active_ports: dict[str, str] = {}
    skipped: set[str] = set()

    for node_id in order:
        node = node_map[node_id]
        incoming = in_edges[node_id]

        # 上游若被剪枝（分支未命中本端口），则本节点跳过
        if incoming and _all_inactive(incoming, active_ports, skipped, outputs):
            skipped.add(node_id)
            if checkpoint:
                await checkpoint(node_id, "skipped", {})
            continue

        node_inputs = _gather_inputs(incoming, outputs, initial_inputs)

        if node.get("node_type") == "condition_branch":
            hit_port = resolve_branch(node.get("config", {}), node_inputs)
            active_ports[node_id] = hit_port
            outputs[node_id] = node_inputs  # 透传给命中下游
            if checkpoint:
                await checkpoint(node_id, "done", {"hit_port": hit_port})
            continue

        if checkpoint:
            await checkpoint(node_id, "running", {})
        output = await node_executor(node, node_inputs)
        outputs[node_id] = output
        if checkpoint:
            await checkpoint(node_id, "done", output)

    return outputs


def _gather_inputs(
    incoming: list[dict[str, Any]],
    outputs: dict[str, dict[str, Any]],
    initial_inputs: dict[str, Any],
) -> dict[str, Any]:
    if not incoming:
        return dict(initial_inputs)
    merged: dict[str, Any] = {}
    for e in incoming:
        src_out = outputs.get(e["source_node_id"], {})
        if isinstance(src_out, dict):
            merged.update(src_out)
    return merged or dict(initial_inputs)


def _all_inactive(
    incoming: list[dict[str, Any]],
    active_ports: dict[str, str],
    skipped: set[str],
    outputs: dict[str, dict[str, Any]],
) -> bool:
    """判断本节点所有入边是否都"未激活"（上游被跳过或分支未命中该端口）。"""
    for e in incoming:
        src = e["source_node_id"]
        if src in skipped:
            continue
        if src in active_ports and active_ports[src] != e["source_port"]:
            continue
        return False  # 至少一条入边激活
    return True
