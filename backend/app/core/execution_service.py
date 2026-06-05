"""执行服务：单块执行 + 历史落库 + WS 输出推送。"""

from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sandbox.docker_executor import run_block, run_block_stream
from app.core.ws.ws_hub import hub
from app.errors import BusinessException
from app.models.execution import ExecutionRecord
from app.observability.metrics import EXEC_COUNT, EXEC_DURATION


async def execute_block(
    session: AsyncSession,
    *,
    block_id: str,
    code: str,
    inputs: dict[str, Any],
    login_id: str,
    flow_run_id: str | None = None,
    entrypoint: str = "run",
    invoke_service: str | None = None,
) -> ExecutionRecord:
    """执行单个块，落库历史，输出经 WS Hub 推送。

    :param entrypoint: 调用脚本中的哪个入口函数（默认 ``run``，支持一脚本多函数）
    :param invoke_service: 该块已部署的常驻 invoke Service 名（k8s 模式命中时复用 warm Pod，免冷启动）
    """
    record = ExecutionRecord(
        block_id=block_id, login_id=login_id, flow_run_id=flow_run_id,
        status="running", inputs=inputs,
    )
    session.add(record)
    await session.flush()
    execution_id = record.id

    start = time.perf_counter()
    try:
        result = await run_block(code, inputs, entrypoint=entrypoint, invoke_service=invoke_service)
        await hub.publish_output(execution_id, result.stdout or "", "stdout")
        if result.stderr:
            await hub.publish_output(execution_id, result.stderr, "stderr")
        record.output = result.output if isinstance(result.output, dict) else {"value": result.output}
        record.stdout = result.stdout
        record.stderr = result.stderr
        record.status = "failed" if result.error else "success"
        EXEC_COUNT.labels(block_id=block_id, status=record.status).inc()
    except BusinessException as exc:
        # 业务异常（如沙箱/K8s Job 失败）：保留 detail 诊断信息，避免只剩 code:msgKey
        record.status = "failed"
        record.stderr = exc.detail or f"{exc.code}:{exc.msg_key}"
        await hub.publish_output(execution_id, record.stderr, "stderr")
        EXEC_COUNT.labels(block_id=block_id, status="failed").inc()
    except Exception as exc:  # noqa: BLE001
        record.status = "failed"
        record.stderr = str(exc)
        await hub.publish_output(execution_id, record.stderr, "stderr")
        EXEC_COUNT.labels(block_id=block_id, status="failed").inc()
    finally:
        record.duration_ms = int((time.perf_counter() - start) * 1000)
        EXEC_DURATION.labels(block_id=block_id).observe(record.duration_ms / 1000)
        await hub.publish_output(execution_id, "__PYFLOW_DONE__", "control")

    await session.commit()
    return record


async def execute_block_stream(
    session: AsyncSession,
    *,
    block_id: str,
    code: str,
    inputs: dict[str, Any],
    login_id: str,
    flow_run_id: str | None = None,
    entrypoint: str = "run",
) -> AsyncIterator[dict[str, Any]]:
    """流式执行单个块：逐 chunk 产出（同时经 WS Hub 旁路推送），末尾产出 result 并落库。

    产出事件结构与底层一致：``{"type": "chunk", "data": ...}`` 若干 + 末尾 ``{"type": "result", ...}``。
    底层异常被收敛为带 ``error`` 字段的 result 事件（不向调用方抛出），由上层据此决定是否中断流程。

    :param entrypoint: 调用脚本中的哪个入口函数（默认 ``run``）
    """
    record = ExecutionRecord(
        block_id=block_id, login_id=login_id, flow_run_id=flow_run_id,
        status="running", inputs=inputs,
    )
    session.add(record)
    await session.flush()
    execution_id = record.id

    start = time.perf_counter()
    result_event: dict[str, Any] | None = None
    error_detail: str | None = None
    try:
        async for event in run_block_stream(code, inputs, entrypoint=entrypoint):
            if event.get("type") == "chunk":
                data = event.get("data")
                line = data if isinstance(data, str) else json.dumps(data, default=str)
                await hub.publish_output(execution_id, line, "stdout")
                yield event
            else:
                result_event = event
    except BusinessException as exc:
        error_detail = exc.detail or f"{exc.code}:{exc.msg_key}"
    except Exception as exc:  # noqa: BLE001
        error_detail = str(exc)[:500]

    if error_detail is not None:
        record.status = "failed"
        record.stderr = error_detail
        EXEC_COUNT.labels(block_id=block_id, status="failed").inc()
        out_event: dict[str, Any] = {
            "type": "result", "output": None, "stdout": "",
            "stderr": error_detail, "error": error_detail,
        }
    elif result_event is None:
        record.status = "failed"
        record.stderr = "no result emitted by stream"
        EXEC_COUNT.labels(block_id=block_id, status="failed").inc()
        out_event = {
            "type": "result", "output": None, "stdout": "",
            "stderr": record.stderr, "error": record.stderr,
        }
    else:
        output = result_event.get("output")
        record.output = output if isinstance(output, dict) else {"value": output}
        record.stdout = result_event.get("stdout")
        record.stderr = result_event.get("stderr")
        record.status = "failed" if result_event.get("error") else "success"
        EXEC_COUNT.labels(block_id=block_id, status=record.status).inc()
        out_event = result_event

    record.duration_ms = int((time.perf_counter() - start) * 1000)
    EXEC_DURATION.labels(block_id=block_id).observe(record.duration_ms / 1000)
    await hub.publish_output(execution_id, "__PYFLOW_DONE__", "control")
    await session.commit()
    yield out_event
