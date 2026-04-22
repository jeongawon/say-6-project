"""
GET /encounters/* — Encounter 조회.

[이 파일이 하는 일]
프론트엔드에서 환자 데이터를 가져올 때 쓰는 조회 API.
FHIR 서버에서 해당 Encounter에 속한 데이터를 검색해서 반환.

[엔드포인트]
GET /encounters/{id}                  → Encounter 자체 정보
GET /encounters/{id}/observations     → 바이탈 + 모달 결과 (ECG/CXR)
GET /encounters/{id}/conditions       → 주호소 + 과거력
GET /encounters/{id}/service-requests → AI 제안 목록 (승인/기각 대기 중인 것)

[호출하는 곳]
프론트엔드 대시보드에서 환자 선택 시
"""
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
