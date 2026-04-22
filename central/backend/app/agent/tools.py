"""Agent tool 4종 — Bedrock Agent가 호출하는 함수들."""
from __future__ import annotations

import logging
from app.fhir import client as fhir
from app.fhir.resources import build_service_request
from app.fhir.codes import LOINC_MODALITY

logger = logging.getLogger(__name__)


async def propose_order(
    patient_id: str,
    encounter_id: str,
    modality: str,
    reason_text: str,
    priority: str = "routine",
) -> dict:
    """Agent가 다음 모달을 제안 → ServiceRequest(draft) 생성."""
    modality_key = modality.lower()
    code_coding = {
        "system": "http://loinc.org",
        **(LOINC_MODALITY.get(modality_key, {"code": "unknown", "display": modality})),
    }
    sr = build_service_request(
        patient_id, encounter_id, code_coding, reason_text, priority
    )
    result = await fhir.create("ServiceRequest", sr)
    logger.info(f"Agent proposed order: SR/{result['id']} for {modality}")
    return result


async def get_encounter_context(encounter_id: str) -> dict:
    """Agent가 현재 Encounter 상태를 읽어 반환."""
    encounter = await fhir.read("Encounter", encounter_id)
    observations = await fhir.search(
        "Observation", {"encounter": f"Encounter/{encounter_id}"}
    )
    conditions = await fhir.search(
        "Condition", {"encounter": f"Encounter/{encounter_id}"}
    )
    service_requests = await fhir.search(
        "ServiceRequest", {"encounter": f"Encounter/{encounter_id}"}
    )
    return {
        "encounter": encounter,
        "observations": observations,
        "conditions": conditions,
        "service_requests": service_requests,
    }
