"""POST /reports/{id}/sign — DiagnosticReport 서명."""
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
