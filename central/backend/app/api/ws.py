"""WebSocket /ws/encounter/{id} — 실시간 상태 푸시."""
from __future__ import annotations

import logging
from typing import Dict, Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter()

# encounter_id → set of connected websockets
_connections: Dict[str, Set[WebSocket]] = {}


@router.websocket("/ws/encounter/{encounter_id}")
async def encounter_ws(websocket: WebSocket, encounter_id: str):
    await websocket.accept()
    _connections.setdefault(encounter_id, set()).add(websocket)
    logger.info(f"WS connected: encounter={encounter_id}")

    try:
        while True:
            # 클라이언트 ping/pong 유지
            await websocket.receive_text()
    except WebSocketDisconnect:
        _connections[encounter_id].discard(websocket)
        logger.info(f"WS disconnected: encounter={encounter_id}")


async def broadcast(encounter_id: str, message: dict):
    """해당 encounter 구독자 전원에게 메시지 전송."""
    sockets = _connections.get(encounter_id, set())
    closed = set()
    for ws in sockets:
        try:
            await ws.send_json(message)
        except Exception:
            closed.add(ws)
    sockets -= closed
