"""§6.2 빌더 함수 — 폼 → FHIR 리소스 변환."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

from app.fhir.codes import (
    LOINC_VITALS, OBS_CATEGORY_VITAL, ENCOUNTER_CLASS_EMER,
)
from app.fhir.code_mapper import map_text_to_icd10

KST = timezone(timedelta(hours=9))


def _now_iso() -> str:
    return datetime.now(KST).isoformat()


def _gen_id(prefix: str = "") -> str:
    short = str(uuid.uuid4())[:8]
    return f"{prefix}-{short}" if prefix else short


# ── Patient ──────────────────────────────────────────────
def build_patient(patient_form: dict) -> dict:
    gender = patient_form["gender"]
    age = patient_form["age"]
    birth_year = datetime.now().year - age
    birth_date = f"{birth_year}-01-01"
    name_text = patient_form.get("name") or "Anonymous"

    return {
        "resourceType": "Patient",
        "identifier": [
            {
                "system": "http://hospital.example.org/mrn",
                "value": f"MRN-{_gen_id()}",
            }
        ],
        "name": [{"use": "official", "text": name_text}],
        "gender": gender,
        "birthDate": birth_date,
    }


# ── Encounter ────────────────────────────────────────────
def build_encounter(patient_id: str, chief_complaint_form: dict) -> dict:
    reason_coding = map_text_to_icd10(chief_complaint_form.get("text", ""))
    reason_code = []
    if reason_coding:
        reason_code = [{"coding": [reason_coding]}]

    return {
        "resourceType": "Encounter",
        "status": "in-progress",
        "class": ENCOUNTER_CLASS_EMER,
        "subject": {"reference": f"Patient/{patient_id}"},
        "period": {"start": _now_iso()},
        "reasonCode": reason_code,
    }


# ── Vitals Bundle ────────────────────────────────────────
def build_vitals_bundle(
    patient_id: str, encounter_id: str, vitals_form: dict
) -> dict:
    """각 vitals 필드마다 Observation 1개 (BP만 component 묶음)."""
    entries: list[dict] = []
    now = _now_iso()

    # BP — component 방식
    if "sbp" in vitals_form and "dbp" in vitals_form:
        bp_obs = _build_bp_observation(
            patient_id, encounter_id, vitals_form["sbp"], vitals_form["dbp"], now
        )
        entries.append(_bundle_entry(bp_obs))

    # 나머지 단일 vitals
    single_keys = {"hr", "spo2", "rr", "temp", "gcs"}
    for key in single_keys:
        if key not in vitals_form:
            continue
        loinc = LOINC_VITALS[key]
        obs = {
            "resourceType": "Observation",
            "status": "final",
            "category": [{"coding": [OBS_CATEGORY_VITAL]}],
            "code": {"coding": [{"system": "http://loinc.org", **loinc}]},
            "subject": {"reference": f"Patient/{patient_id}"},
            "encounter": {"reference": f"Encounter/{encounter_id}"},
            "effectiveDateTime": now,
            "valueQuantity": {
                "value": vitals_form[key],
                "unit": loinc["unit"],
                "system": "http://unitsofmeasure.org",
                "code": loinc["unit"],
            },
        }
        entries.append(_bundle_entry(obs))

    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": entries,
    }


def _build_bp_observation(
    patient_id: str, encounter_id: str, sbp: float, dbp: float, effective: str
) -> dict:
    bp_loinc = LOINC_VITALS["bp"]
    sbp_loinc = LOINC_VITALS["sbp"]
    dbp_loinc = LOINC_VITALS["dbp"]
    return {
        "resourceType": "Observation",
        "status": "final",
        "category": [{"coding": [OBS_CATEGORY_VITAL]}],
        "code": {"coding": [{"system": "http://loinc.org", **bp_loinc}]},
        "subject": {"reference": f"Patient/{patient_id}"},
        "encounter": {"reference": f"Encounter/{encounter_id}"},
        "effectiveDateTime": effective,
        "component": [
            {
                "code": {"coding": [{"system": "http://loinc.org", **sbp_loinc}]},
                "valueQuantity": {"value": sbp, "unit": "mm[Hg]",
                                  "system": "http://unitsofmeasure.org", "code": "mm[Hg]"},
            },
            {
                "code": {"coding": [{"system": "http://loinc.org", **dbp_loinc}]},
                "valueQuantity": {"value": dbp, "unit": "mm[Hg]",
                                  "system": "http://unitsofmeasure.org", "code": "mm[Hg]"},
            },
        ],
    }


def _bundle_entry(resource: dict) -> dict:
    rtype = resource["resourceType"]
    return {
        "resource": resource,
        "request": {"method": "POST", "url": rtype},
    }


# ── Chief Complaint (Condition) ──────────────────────────
def build_chief_complaint(
    patient_id: str, encounter_id: str, cc_form: dict
) -> dict:
    code_hint = cc_form.get("code_hint")
    text = cc_form.get("text", "")

    coding = []
    if code_hint:
        coding = [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": code_hint}]
    else:
        mapped = map_text_to_icd10(text)
        if mapped:
            coding = [mapped]

    return {
        "resourceType": "Condition",
        "clinicalStatus": {
            "coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                         "code": "active"}]
        },
        "verificationStatus": {
            "coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                         "code": "provisional"}]
        },
        "category": [
            {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-category",
                          "code": "encounter-diagnosis"}]}
        ],
        "code": {"coding": coding, "text": text},
        "subject": {"reference": f"Patient/{patient_id}"},
        "encounter": {"reference": f"Encounter/{encounter_id}"},
        "recordedDate": _now_iso(),
    }


# ── Past History (Bundle[Condition]) ─────────────────────
def build_past_history(patient_id: str, history_list: list[dict]) -> dict:
    entries = []
    for item in history_list:
        text = item.get("text", "")
        code_hint = item.get("code_hint")

        coding = []
        if code_hint:
            coding = [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": code_hint}]
        else:
            mapped = map_text_to_icd10(text)
            if mapped:
                coding = [mapped]

        cond = {
            "resourceType": "Condition",
            "clinicalStatus": {
                "coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                             "code": "active"}]
            },
            "verificationStatus": {
                "coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                             "code": "confirmed"}]
            },
            "category": [
                {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-category",
                              "code": "problem-list-item"}]}
            ],
            "code": {"coding": coding, "text": text},
            "subject": {"reference": f"Patient/{patient_id}"},
            "recordedDate": _now_iso(),
        }
        entries.append(_bundle_entry(cond))

    return {"resourceType": "Bundle", "type": "transaction", "entry": entries}


# ── ServiceRequest (Agent 제안) ──────────────────────────
def build_service_request(
    patient_id: str,
    encounter_id: str,
    code_coding: dict,
    reason_text: str = "",
    priority: str = "routine",
) -> dict:
    return {
        "resourceType": "ServiceRequest",
        "status": "draft",
        "intent": "proposal",
        "priority": priority,
        "subject": {"reference": f"Patient/{patient_id}"},
        "encounter": {"reference": f"Encounter/{encounter_id}"},
        "code": {"coding": [code_coding]},
        "requester": {"display": "Dr.AI Agent"},
        "authoredOn": _now_iso(),
        "note": [{"text": reason_text}] if reason_text else [],
    }


# ── DiagnosticReport (SOAP) ──────────────────────────────
def build_diagnostic_report(
    patient_id: str,
    encounter_id: str,
    observation_ids: list[str],
    conclusion: str,
) -> dict:
    return {
        "resourceType": "DiagnosticReport",
        "status": "preliminary",
        "category": [
            {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0074",
                          "code": "OTH", "display": "Other"}]}
        ],
        "code": {"coding": [{"system": "http://loinc.org",
                              "code": "11488-4", "display": "Consultation note"}]},
        "subject": {"reference": f"Patient/{patient_id}"},
        "encounter": {"reference": f"Encounter/{encounter_id}"},
        "effectiveDateTime": _now_iso(),
        "issued": _now_iso(),
        "performer": [{"display": "Dr.AI Agent"}],
        "result": [{"reference": f"Observation/{oid}"} for oid in observation_ids],
        "conclusion": conclusion,
    }


# =====================================================================
# 모달 아웃풋 → FHIR Observation 변환 함수
# =====================================================================

def convert_ecg_to_observations(
    patient_id: str,
    encounter_id: str,
    ecg_response: dict,
    docref_id: str | None = None,
) -> list[dict]:
    """
    ECG 서비스 PredictResponse → FHIR Observation 리스트.

    ECG 아웃풋 구조:
      status, modal, findings[], summary, risk_level,
      ecg_vitals{heart_rate, bradycardia, tachycardia, irregular_rhythm},
      all_probs{}, waveform[][], metadata{}
    """
    now = _now_iso()
    patient_ref = f"Patient/{patient_id}"
    encounter_ref = f"Encounter/{encounter_id}"
    derived_from = [{"reference": f"DocumentReference/{docref_id}"}] if docref_id else []

    observations: list[dict] = []

    # ── 1) 각 finding → Observation (질환별 확률) ────────
    for f in ecg_response.get("findings", []):
        components = [
            {
                "code": {"text": f["name"]},
                "valueQuantity": {
                    "value": f["confidence"],
                    "unit": "probability",
                },
            }
        ]
        obs = {
            "resourceType": "Observation",
            "status": "preliminary",
            "category": [{"coding": [OBS_CATEGORY_IMAGING]}],
            "code": {"coding": [{
                "system": "http://loinc.org",
                "code": "11524-6",
                "display": "EKG study",
            }]},
            "subject": {"reference": patient_ref},
            "encounter": {"reference": encounter_ref},
            "effectiveDateTime": now,
            "valueString": f.get("detail", f["name"]),
            "component": components,
            "derivedFrom": derived_from,
        }
        # severity → interpretation
        if f.get("severity"):
            obs["note"] = [{"text": f"severity: {f['severity']}"}]
            if f.get("recommendation"):
                obs["note"].append({"text": f"recommendation: {f['recommendation']}"})

        observations.append(obs)

    # ── 2) ecg_vitals → Observation (HR) ────────────────
    vitals = ecg_response.get("ecg_vitals") or {}
    if vitals.get("heart_rate") is not None:
        hr_loinc = LOINC_VITALS["hr"]
        hr_obs = {
            "resourceType": "Observation",
            "status": "preliminary",
            "category": [{"coding": [OBS_CATEGORY_VITAL]}],
            "code": {"coding": [{"system": "http://loinc.org", **hr_loinc}]},
            "subject": {"reference": patient_ref},
            "encounter": {"reference": encounter_ref},
            "effectiveDateTime": now,
            "valueQuantity": {
                "value": vitals["heart_rate"],
                "unit": "/min",
                "system": "http://unitsofmeasure.org",
                "code": "/min",
            },
            "derivedFrom": derived_from,
        }
        observations.append(hr_obs)

    # ── 3) 전체 요약 Observation ─────────────────────────
    summary_obs = {
        "resourceType": "Observation",
        "status": "preliminary",
        "category": [{"coding": [OBS_CATEGORY_IMAGING]}],
        "code": {"coding": [{
            "system": "http://loinc.org",
            "code": "11524-6",
            "display": "EKG study",
        }]},
        "subject": {"reference": patient_ref},
        "encounter": {"reference": encounter_ref},
        "effectiveDateTime": now,
        "valueString": ecg_response.get("summary", ""),
        "derivedFrom": derived_from,
        "note": [{"text": f"risk_level: {ecg_response.get('risk_level', 'routine')}"}],
    }
    observations.append(summary_obs)

    return observations


def convert_cxr_to_observations(
    patient_id: str,
    encounter_id: str,
    cxr_response: dict,
    docref_id: str | None = None,
) -> list[dict]:
    """
    CXR 서비스 PredictResponse → FHIR Observation 리스트.

    CXR 아웃풋 구조:
      status, modal, findings[], summary, risk_level,
      findings_text, impression, measurements{},
      rag_query_hints[], metadata{mask_base64}
    """
    now = _now_iso()
    patient_ref = f"Patient/{patient_id}"
    encounter_ref = f"Encounter/{encounter_id}"
    derived_from = [{"reference": f"DocumentReference/{docref_id}"}] if docref_id else []

    observations: list[dict] = []

    # ── 1) 각 finding → Observation (질환별) ─────────────
    for f in cxr_response.get("findings", []):
        if not f.get("detected", False):
            continue

        components = [
            {
                "code": {"text": f["name"]},
                "valueQuantity": {
                    "value": f["confidence"],
                    "unit": "probability",
                },
            }
        ]
        # location이 있으면 component 추가
        if f.get("location"):
            components.append({
                "code": {"text": "location"},
                "valueString": f["location"],
            })

        obs = {
            "resourceType": "Observation",
            "status": "preliminary",
            "category": [{"coding": [OBS_CATEGORY_IMAGING]}],
            "code": {"coding": [{
                "system": "http://loinc.org",
                "code": "36643-5",
                "display": "Chest X-ray",
            }]},
            "subject": {"reference": patient_ref},
            "encounter": {"reference": encounter_ref},
            "effectiveDateTime": now,
            "valueString": f.get("impression_text") or f.get("detail") or f["name"],
            "component": components,
            "derivedFrom": derived_from,
        }

        notes = []
        if f.get("severity"):
            notes.append({"text": f"severity: {f['severity']}"})
        if f.get("recommendation"):
            notes.append({"text": f"recommendation: {f['recommendation']}"})
        if f.get("evidence"):
            notes.append({"text": f"evidence: {'; '.join(f['evidence'])}"})
        if notes:
            obs["note"] = notes

        observations.append(obs)

    # ── 2) measurements → Observation (CTR 등) ──────────
    measurements = cxr_response.get("measurements", {})
    if measurements.get("ctr") is not None:
        ctr_obs = {
            "resourceType": "Observation",
            "status": "preliminary",
            "category": [{"coding": [OBS_CATEGORY_IMAGING]}],
            "code": {"coding": [{
                "system": "http://loinc.org",
                "code": "36643-5",
                "display": "Chest X-ray",
            }], "text": "Cardiothoracic Ratio"},
            "subject": {"reference": patient_ref},
            "encounter": {"reference": encounter_ref},
            "effectiveDateTime": now,
            "valueQuantity": {
                "value": measurements["ctr"],
                "unit": "ratio",
            },
            "derivedFrom": derived_from,
        }
        observations.append(ctr_obs)

    # ── 3) 전체 요약 Observation ─────────────────────────
    summary_parts = []
    if cxr_response.get("findings_text"):
        summary_parts.append(cxr_response["findings_text"])
    if cxr_response.get("impression"):
        summary_parts.append(cxr_response["impression"])
    summary_text = cxr_response.get("summary", "")
    if summary_parts:
        summary_text = "\n".join(summary_parts)

    summary_obs = {
        "resourceType": "Observation",
        "status": "preliminary",
        "category": [{"coding": [OBS_CATEGORY_IMAGING]}],
        "code": {"coding": [{
            "system": "http://loinc.org",
            "code": "36643-5",
            "display": "Chest X-ray",
        }]},
        "subject": {"reference": patient_ref},
        "encounter": {"reference": encounter_ref},
        "effectiveDateTime": now,
        "valueString": summary_text,
        "derivedFrom": derived_from,
        "note": [{"text": f"risk_level: {cxr_response.get('risk_level', 'routine')}"}],
    }
    observations.append(summary_obs)

    return observations
