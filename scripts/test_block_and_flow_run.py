#!/usr/bin/env python3
"""PyFlowHub 块执行与 Flow 整流执行测试脚本。

环境变量：
  PYFLOW_BASE_URL   控制面地址，默认 http://localhost:8000
  PYFLOW_TOKEN      Bearer Token（PYFLOW_AUTH_ENABLED=true 时必填）

可选：
  PYFLOW_SKIP_FLOW  设为 1 时仅测单块执行，跳过 Flow /run

用户 Block 代码须定义：def run(inputs): 并 return {"echo": inputs} 等可断言结果

前置：
  1. docker compose up -d（PostgreSQL 等）
  2. 控制面已启动并完成 Alembic 迁移
  3. Windows 无 Docker 时会降级 in-process 执行（仅 dev）

运行：
  python scripts/test_block_and_flow_run.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE_URL = os.environ.get("PYFLOW_BASE_URL", "http://localhost:8000").rstrip("/")
TOKEN = os.environ.get("PYFLOW_TOKEN", "").strip()
SKIP_FLOW = os.environ.get("PYFLOW_SKIP_FLOW", "").strip() in ("1", "true", "yes")

# 约定见 pyflow_runtime.executor：必须定义 run(inputs)
SAMPLE_CODE = '''def run(inputs):
    return {"echo": inputs}
'''


def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if TOKEN:
        h["Authorization"] = f"Bearer {TOKEN}"
    return h


def _api(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{BASE_URL}{path}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_headers(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            err = json.loads(raw)
        except json.JSONDecodeError:
            err = {"raw": raw}
        raise RuntimeError(f"{method} {path} -> HTTP {exc.code}: {err}") from exc


def test_block_run() -> str:
    """创建脚本块、执行、删除；返回 block_id 供 Flow 图复用。"""
    print("\n--- 1. 单块执行 POST /api/blocks/{id}/run ---")
    block = _api("POST", "/api/blocks", {
        "name": "script-test-echo",
        "description": "scripts/test_block_and_flow_run.py 自动创建",
        "type": "script",
        "draft_code": SAMPLE_CODE,
        "input_ports": [{"name": "inputs", "type": "any", "required": False}],
        "output_ports": [{"name": "output", "type": "any", "required": False}],
        "execution_mode": "sync_http",
    })
    block_id = block["id"]
    print(f"  已创建 block_id={block_id}")

    block_inputs = {"a": 3, "b": 7}
    result = _api("POST", f"/api/blocks/{block_id}/run", {"inputs": block_inputs})
    print(f"  execution_id={result.get('execution_id')}  status={result.get('status')}")
    print(f"  output={json.dumps(result.get('output'), ensure_ascii=False)}")

    out = result.get("output") or {}
    echo = out.get("echo")
    print(f"  echo={json.dumps(echo, ensure_ascii=False)}")
    if result.get("status") != "success" or echo != block_inputs:
        raise RuntimeError(f"块执行结果不符合预期（echo 应回显 inputs）: {result}")

    _api("DELETE", f"/api/blocks/{block_id}")
    print("  已清理测试块")
    return block_id


def test_flow_run() -> None:
    """创建 Flow + 单节点画布 + POST /api/flows/{id}/run。"""
    print("\n--- 2. Flow 整流执行 POST /api/flows/{flow_id}/run ---")
    flow = _api("POST", "/api/flows", {
        "name": "flow-test-run",
        "description": "scripts/test_block_and_flow_run.py 自动创建",
    })
    flow_id = flow["id"]
    print(f"  已创建 flow_id={flow_id}")

    block = _api("POST", "/api/blocks", {
        "name": "flow-node-echo",
        "type": "script",
        "draft_code": SAMPLE_CODE,
        "input_ports": [{"name": "inputs", "type": "any"}],
        "output_ports": [{"name": "output", "type": "any"}],
        "execution_mode": "sync_http",
    })
    block_id = block["id"]
    node_id = "node-test-1"

    _api("PUT", f"/api/flows/{flow_id}/graph", {
        "nodes": [{
            "id": node_id,
            "node_type": "block",
            "block_id": block_id,
            "config": {"label": "echo"},
            "position": {"x": 100, "y": 100},
        }],
        "edges": [],
    })
    print(f"  已保存画布（单节点 block_id={block_id}）")

    flow_inputs = {"a": 1, "b": 2}
    run_result = _api("POST", f"/api/flows/{flow_id}/run", {
        "inputs": flow_inputs,
    })
    print(f"  flow_run_id={run_result.get('flow_run_id')}  status={run_result.get('status')}")
    print(f"  outputs={json.dumps(run_result.get('outputs'), ensure_ascii=False)}")

    if run_result.get("status") != "succeeded":
        raise RuntimeError(f"Flow 执行未成功: {run_result}")

    node_out = (run_result.get("outputs") or {}).get(node_id) or {}
    echo = node_out.get("echo")
    print(f"  node echo={json.dumps(echo, ensure_ascii=False)}")
    if echo != flow_inputs:
        raise RuntimeError(f"Flow 节点 echo 不符合预期: {run_result}")

    _api("DELETE", f"/api/blocks/{block_id}")
    print("  已清理 Flow 测试块（Flow 记录保留，可在控制台查看）")


def main() -> int:
    print(f"PyFlowHub 执行测试  base_url={BASE_URL}")
    try:
        test_block_run()
        if not SKIP_FLOW:
            test_flow_run()
        else:
            print("\n（已跳过 Flow 测试：PYFLOW_SKIP_FLOW=1）")
    except RuntimeError as exc:
        print(f"\n失败: {exc}", file=sys.stderr)
        print("提示：确认 DB/迁移、鉴权 Token、Docker 或 in-process 降级是否可用。", file=sys.stderr)
        return 1
    print("\n全部执行测试通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
