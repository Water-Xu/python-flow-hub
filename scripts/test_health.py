#!/usr/bin/env python3
"""PyFlowHub 连通性与健康检查脚本。

环境变量（均可选，有默认值）：
  PYFLOW_BASE_URL   控制面地址，默认 http://localhost:8000
                    经网关时示例：http://localhost:8201/lhy-styon-pyflow
  PYFLOW_TOKEN      Bearer Token；仅当服务端 PYFLOW_AUTH_ENABLED=true 时必填
                    本地 dev 默认关闭鉴权，可不设置

前置：控制面已启动（如 backend 目录 uvicorn app.main:app --port 8000）

运行：
  python scripts/test_health.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE_URL = os.environ.get("PYFLOW_BASE_URL", "http://localhost:8000").rstrip("/")
TOKEN = os.environ.get("PYFLOW_TOKEN", "").strip()

ENDPOINTS = (
    ("/", "服务信息"),
    ("/health/live", "存活探针"),
    ("/health/ready", "就绪探针（依赖 PostgreSQL）"),
)


def _request(path: str) -> tuple[int, dict | str]:
    url = f"{BASE_URL}{path}"
    headers = {"Accept": "application/json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, body
    except urllib.error.URLError as exc:
        return 0, {"error": str(exc.reason)}


def main() -> int:
    print(f"PyFlowHub 健康检查  base_url={BASE_URL}")
    ok = True
    for path, label in ENDPOINTS:
        status, data = _request(path)
        if isinstance(data, dict) and "error" in data:
            passed = False
        else:
            passed = status == 200
            if path == "/health/ready" and isinstance(data, dict):
                passed = data.get("status") == "ready"
        mark = "OK" if passed else "FAIL"
        print(f"  [{mark}] {label}  GET {path}  -> HTTP {status}")
        print(f"        {json.dumps(data, ensure_ascii=False) if isinstance(data, dict) else data}")
        ok = ok and passed
    if not ok:
        print("\n提示：连接被拒绝时请先启动控制面（uvicorn app.main:app --port 8000）。")
        print("      就绪失败时请确认 docker compose up -d 且 Alembic 迁移已执行。")
        return 1
    print("\n全部检查通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
