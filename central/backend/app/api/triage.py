"""
POST /triage/submit — 트리아지 제출 엔드포인트.

[이 파일이 하는 일]
간호사가 환자 정보를 입력하면 이 API가 받아서:
1. Patient (환자 정보) → FHIR 서버에 저장
2. Encounter (이번 ED 방문) → FHIR 서버에 저장
3. Observation (바이탈 6개) → FHIR 서버에 저장
4. Condition (주호소 + 과거력) → FHIR 서버에 저장
5. FusionDecisionEngine 호출 → "어떤 검사할지" AI가 판단
6. ServiceRequest (검사 제안) → FHIR 서버에 저장
7. WebSocket으로 프론트에 "AI가 CXR, ECG를 권고합니다" 푸시

[호출하는 곳]
프론트엔드 트리아지 폼에서 POST /triage/submit 호출

[FHIR 설명]
FHIR은 의료 데이터 국제 표준 규격이에요.
이 파일에서 build_patient(), build_encounter() 등을 호출하면
resources.py가 우리 데이터를 FHIR 규격 JSON으로 변환하고,
client.py가 그 JSON을 HAPI FHIR 서버(=DB)에 저장합니다.
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.fhir import client as fhir
from app.fhir.resources import (
    build_patient,
    build_encounter,
    build_vitals_bundle,
    build_chief_complaint,
    build_past_history,
)
from app.agent.decision_engine import FusionDecisionEngine
from app.agent.tools import propose_order
from app.api.ws import broadcast

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request Schema (§6.1) ────────────────────────────────
class PatientForm(BaseModel):
    age: int
    gender: str  # male | female | other
    name: Optional[str] = None


class VitalsForm(BaseModel):
    hr: float
    sbp: float
    dbp: float
    spo2: float
    rr: float
    temp: float
    gcs: float


class ChiefComplaintForm(BaseModel):
    text: str
    onset_minutes_ago: Optional[int] = None
    code_hint: Optional[str] = None


class PastHistoryItem(BaseModel):
    text: str
    code_hint: Optional[str] = None


class TriageSubmission(BaseModel):
    patient: PatientForm
    vitals: VitalsForm
    chief_complaint: ChiefComplaintForm
    past_history: list[PastHistoryItem] = []


@router.post("/submit")
async def submit_triage(form: TriageSubmission):
    """
    §7.1 POST 순서:
    1. Patient (참조 없음)
    2. Encounter (Patient 참조)
    3. 나머지 (Observation, Condition)
    """
    try:
        # 1) Patient
        patient_res = await fhir.create(
            "Patient", build_patient(form.patient.model_dump())
        )
        patient_id = patient_res["id"]

        # 2) Encounter
        encounter_res = await fhir.create(
            "Encounter",
            build_encounter(patient_id, form.chief_complaint.model_dump()),
        )
        encounter_id = encounter_res["id"]

        # 3-a) Vitals Bundle (transaction)
        vitals_bundle = build_vitals_bundle(
            patient_id, encounter_id, form.vitals.model_dump()
        )
        await fhir.transaction(vitals_bundle)

        # 3-b) Chief Complaint (Condition)
        cc_res = await fhir.create(
            "Condition",
            build_chief_complaint(
                patient_id, encounter_id, form.chief_complaint.model_dump()
            ),
        )

        # 3-c) Past History (Bundle)
        if form.past_history:
            history_bundle = build_past_history(
                patient_id,
                [h.model_dump() for h in form.past_history],
            )
            await fhir.transaction(history_bundle)

        # ── 4) FusionDecisionEngine 호출 → 초기 모달 제안 ──
        central_patient = {
            "age": form.patient.age,
            "sex": form.patient.gender.capitalize(),
            "chief_complaint": form.chief_complaint.text,
            "vitals": form.vitals.model_dump(),
        }

        engine = FusionDecisionEngine(
            patient=central_patient,
            modalities_completed=[],
            inference_results=[],
            iteration=1,
        )
        decision = engine.decide()

        # 제안된 모달마다 ServiceRequest(draft) 생성
        proposed_sr_ids = []
        for modality in decision.get("next_modalities", []):
            sr_res = await propose_order(
                patient_id=patient_id,
                encounter_id=encounter_id,
                modality=modality,
                reason_text=decision.get("rationale", ""),
                priority="urgent" if decision.get("risk_level") == "high" else "routine",
            )
            proposed_sr_ids.append(sr_res["id"])

        # WebSocket으로 프론트에 푸시
        await broadcast(encounter_id, {
            "event": "initial_proposals",
            "service_request_ids": proposed_sr_ids,
            "next_modalities": decision.get("next_modalities", []),
            "rationale": decision.get("rationale", ""),
            "risk_level": decision.get("risk_level", "unknown"),
        })

        return {
            "patient_id": patient_id,
            "encounter_id": encounter_id,
            "chief_complaint_id": cc_res["id"],
            "proposed_modalities": decision.get("next_modalities", []),
            "service_request_ids": proposed_sr_ids,
            "status": "created",
        }

    except Exception as e:
        logger.exception("Triage submit failed")
        raise HTTPException(status_code=500, detail=str(e))
