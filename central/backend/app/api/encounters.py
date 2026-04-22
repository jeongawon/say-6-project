"""GET /encounters/* — Encounter 조회."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from app.fhir import client as fhir

router = APIRouter()


@router.get("/{encounter_id}")
async def get_encounter(encounter_id: str):
    """단일 Encounter 조회."""
    try:
        return await fhir.read("Encounter", encounter_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{encounter_id}/observations")
async def get_encounter_observations(encounter_id: str):
    """해당 Encounter에 속한 Observation 목록."""
    try:
        return await fhir.search(
            "Observation", {"encounter": f"Encounter/{encounter_id}"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{encounter_id}/conditions")
async def get_encounter_conditions(encounter_id: str):
    """해당 Encounter에 속한 Condition 목록."""
    try:
        return await fhir.search(
            "Condition", {"encounter": f"Encounter/{encounter_id}"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{encounter_id}/service-requests")
async def get_encounter_service_requests(encounter_id: str):
    """해당 Encounter에 속한 ServiceRequest 목록."""
    try:
        return await fhir.search(
            "ServiceRequest", {"encounter": f"Encounter/{encounter_id}"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
