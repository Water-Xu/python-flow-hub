"""执行服务：单块执行 + 历史落库 + WS 输出推送。"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sandbox.docker_executor import run_block
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
) -> ExecutionRecord:
    """执行单个块，落库历史，输出经 WS Hub 推送。"""
    record = ExecutionRecord(
        block_id=block_id, login_id=login_id, flow_run_id=flow_run_id,
        status="running", inputs=inputs,
    )
    session.add(record)
    await session.flush()
    execution_id = record.id

    start = time.perf_counter()
    try:
        result = await run_block(code, inputs)
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
