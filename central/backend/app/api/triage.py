"""POST /triage/submit — 트리아지 제출 엔드포인트."""
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

        return {
            "patient_id": patient_id,
            "encounter_id": encounter_id,
            "chief_complaint_id": cc_res["id"],
            "status": "created",
        }

    except Exception as e:
        logger.exception("Triage submit failed")
        raise HTTPException(status_code=500, detail=str(e))
