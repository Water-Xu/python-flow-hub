"""flow_runner 续跑单测（Phase 4a：已完成节点不重跑，决策 10）。"""

from __future__ import annotations

from app.core.flow.flow_runner import run_flow


async def test_resume_skips_completed_nodes():
    nodes = [
        {"id": "a", "node_type": "block", "block_id": "ba"},
        {"id": "b", "node_type": "block", "block_id": "bb"},
    ]
    edges = [{"source_node_id": "a", "target_node_id": "b", "source_port": "output", "target_port": "input"}]

    executed: list[str] = []

    async def node_executor(node, inputs):
        executed.append(node["id"])
        return {"v": node["id"]}

    # a 已完成（prior_outputs），续跑只应执行 b
    outputs = await run_flow(
        nodes, edges, {}, node_executor,
        prior_outputs={"a": {"v": "a"}},
    )
    assert executed == ["b"]
    assert outputs["a"] == {"v": "a"}
    assert outputs["b"]["v"] == "b"


async def test_full_run_executes_all():
    nodes = [{"id": "a", "node_type": "block", "block_id": "ba"}]
    edges = []
    executed: list[str] = []

    async def node_executor(node, inputs):
        executed.append(node["id"])
        return {"ok": True}

    await run_flow(nodes, edges, {"x": 1}, node_executor)
    assert executed == ["a"]
