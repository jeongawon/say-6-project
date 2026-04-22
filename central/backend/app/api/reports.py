"""
POST /reports/{id}/sign — DiagnosticReport 서명.

[이 파일이 하는 일]
AI가 생성한 최종 SOAP 리포트(DiagnosticReport)를 의사가 서명하는 API.
서명하면 상태가 preliminary(임시) → final(확정)로 바뀜.

[FHIR 설명]
DiagnosticReport = 여러 Observation을 묶은 최종 결론.
AI가 만들면 status: "preliminary" (확정 아님),
의사가 서명하면 status: "final" (확정).
이게 "AI가 독단적으로 결정하지 않는다"는 증거.
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException

from app.fhir.state_machine import (
    transition_diagnostic_report,
    InvalidTransitionError,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/{dr_id}/sign")
async def sign_report(dr_id: str):
    """의사 최종 서명: preliminary → final."""
    try:
        result = await transition_diagnostic_report(dr_id, "final")
        return {"diagnostic_report_id": dr_id, "status": "final"}
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.exception("Report sign failed")
        raise HTTPException(status_code=500, detail=str(e))
