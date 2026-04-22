"""
WebSocket /ws/encounter/{id} — 실시간 상태 푸시.

[이 파일이 하는 일]
프론트엔드가 WebSocket으로 연결하면, 백엔드에서 이벤트 발생 시 즉시 알림.

[푸시되는 이벤트]
- initial_proposals: 트리아지 후 AI가 초기 모달 제안
- modal_completed: 모달 실행 완료 (결과 나옴)
- modal_failed: 모달 실행 실패
- new_proposal: AI가 새 모달 제안 (기각 후 대안)
- ready_for_report: 모든 모달 완료, 리포트 생성 가능

[호출하는 곳]
프론트엔드 대시보드에서 WS /ws/encounter/{id}로 연결
"""
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
