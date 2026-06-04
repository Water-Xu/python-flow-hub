"""WebSocket 执行输出路由（决策 5）。"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.ws.ws_hub import hub

router = APIRouter(tags=["ws"])


@router.websocket("/ws/exec/{execution_id}")
async def ws_exec(websocket: WebSocket, execution_id: str):
    """订阅执行输出。

    1b 起：accept 前校验 token（subprotocol）+ execution_id 可见性；
    1a：直连/port-forward，先不穿网关。
    """
    await websocket.accept()
    try:
        await hub.serve(websocket, execution_id)
    except WebSocketDisconnect:
        return
