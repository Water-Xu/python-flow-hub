"""Flow DAG 编排（共享执行库，决策 10）。

控制面（dev-local / 公共 HTTP / K8s 同步编排）与 runner 镜像（prod Flow-Consumer）
单一来源共享这套纯逻辑：拓扑无环校验 + 拓扑序执行 + 条件分支剪枝 + 续跑。

不依赖后端 app，错误用本模块 DagError 表达；调用方按需翻译为自身错误码体系。
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Awaitable, Callable

from pyflow_runtime.condition_engine import evaluate_condition, extract_path

# 节点执行回调：(node, inputs) -> output dict
NodeExecutor = Callable[[dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any]]]
# checkpoint 回调：(node_id, status, output) -> None
Checkpoint = Callable[[str, str, dict[str, Any]], Awaitable[None]]


class DagError(Exception):
    """DAG 非法（成环 / 引用未知节点）。"""


def topological_order(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[str]:
    """返回拓扑序节点 ID 列表；成环抛 DagError。"""
    node_ids = {n["id"] for n in nodes}
    indegree: dict[str, int] = {nid: 0 for nid in node_ids}
    adj: dict[str, list[str]] = defaultdict(list)

    for e in edges:
        src, dst = e["source_node_id"], e["target_node_id"]
        if src not in node_ids or dst not in node_ids:
            raise DagError("edge references unknown node")
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
        raise DagError("flow graph contains a cycle")
    return order


def validate_dag(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    """仅校验无环（保存/发布时）。"""
    topological_order(nodes, edges)


def resolve_branch(node_config: dict[str, Any], payload: dict[str, Any]) -> str:
    """对条件分支节点求值，返回命中的输出端口名。"""
    subtype = node_config.get("subtype", "if_else")
    language = node_config.get("condition_language", "jmespath")

    if subtype == "if_else":
        expr = node_config.get("condition_expression", "")
        hit = evaluate_condition(expr, language, payload)
        return node_config.get("true_port" if hit else "false_port", "")

    # switch_case
    switch_field = node_config.get("switch_field", "")
    value = extract_path(switch_field, payload, language)
    for case in node_config.get("branches", []):
        if str(case.get("value")) == str(value):
            return case.get("port", "")
    return node_config.get("default_port", "")


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
) -> dict[str, dict[str, Any]]:
    """执行整流，返回 {node_id: output}。

    续跑（决策 10，4a 多副本）：传入 prior_* 还原已完成节点的输出 / 分支决策 / 跳过集合，
    已完成节点不重跑（其下游幂等 key 含 run_id:node_id）。
    """
    order = topological_order(nodes, edges)
    node_map = {n["id"]: n for n in nodes}

    # 入边：target -> [(source, source_port, target_port)]
    in_edges: dict[str, list[dict[str, Any]]] = {nid: [] for nid in node_map}
    for e in edges:
        in_edges[e["target_node_id"]].append(e)

    outputs: dict[str, dict[str, Any]] = dict(prior_outputs or {})
    # 被分支节点剪枝掉的端口：{node_id: 命中端口}，决定下游是否激活
    active_ports: dict[str, str] = dict(prior_active_ports or {})
    skipped: set[str] = set(prior_skipped or set())

    for node_id in order:
        node = node_map[node_id]
        incoming = in_edges[node_id]

        # 续跑：已完成（有输出 / 已判分支 / 已跳过）的节点不重跑
        if node_id in skipped:
            continue
        if node_id in active_ports or (node_id in outputs and node.get("node_type") != "condition_branch"):
            continue

        # 上游若被剪枝（分支未命中本端口），则本节点跳过
        if incoming and _all_inactive(incoming, active_ports, skipped, outputs):
            skipped.add(node_id)
            if checkpoint:
                await checkpoint(node_id, "skipped", {})
            continue

        node_inputs = _gather_inputs(incoming, outputs, initial_inputs)

        # 测试输入节点：不执行代码，仅把配置的键值作为输出向下游注入
        if node.get("node_type") == "input":
            outputs[node_id] = _input_payload(node.get("config", {}))
            if checkpoint:
                await checkpoint(node_id, "done", outputs[node_id])
            continue

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


def _input_payload(config: dict[str, Any]) -> dict[str, Any]:
    """测试输入节点 → 输出字典。"""
    key = config.get("key")
    value = config.get("value")
    if key:
        return {key: value}
    if isinstance(value, dict):
        return dict(value)
    return {"value": value}


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
