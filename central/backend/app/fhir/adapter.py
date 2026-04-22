"""FHIR ↔ central 포맷 변환 어댑터.

central FusionDecisionEngine이 기대하는 포맷:
{
    "patient": {
        "age": 65,
        "sex": "Male",
        "chief_complaint": "chest pain",
        "vitals": {"HR": "112 bpm", "BP": "148/92 mmHg", ...},
        "history": "...",
    }
}

central 모달 결과 포맷:
{
    "modality": "CXR",
    "finding": "Cardiomegaly ...",
    "confidence": 0.82,
    "details": {...},
    "rationale": "...",
}
"""
from __future__ import annotations

from datetime import datetime


# ── FHIR → central ──────────────────────────────────────

def fhir_to_central_patient(
    patient_res: dict,
    encounter_res: dict,
    vitals_obs: list[dict],
    conditions: list[dict],
) -> dict:
    """FHIR 리소스들 → central FusionDecisionEngine이 기대하는 patient dict."""

    # age: birthDate → 나이 계산
    birth_date = patient_res.get("birthDate", "")
    age = _calc_age(birth_date)

    # sex: gender → 대문자 첫글자
    gender = patient_res.get("gender", "unknown")
    sex_map = {"male": "Male", "female": "Female", "other": "Other"}
    sex = sex_map.get(gender, gender.capitalize())

    # chief_complaint: Encounter.reasonCode 또는 Condition(encounter-diagnosis)
    chief_complaint = ""
    reason_codes = encounter_res.get("reasonCode", [])
    if reason_codes:
        coding = reason_codes[0].get("coding", [])
        if coding:
            chief_complaint = coding[0].get("display", "")
        if not chief_complaint:
            chief_complaint = reason_codes[0].get("text", "")

    # Condition에서 주호소 텍스트 보완
    if not chief_complaint:
        for cond in conditions:
            cats = cond.get("category", [])
            for cat in cats:
                for c in cat.get("coding", []):
                    if c.get("code") == "encounter-diagnosis":
                        chief_complaint = cond.get("code", {}).get("text", "")
                        break

    # vitals: Observation 리스트 → {"HR": "112 bpm", "BP": "148/92 mmHg", ...}
    vitals = _convert_vitals(vitals_obs)

    # history: Condition(problem-list-item) → 텍스트
    history_parts = []
    for cond in conditions:
        cats = cond.get("category", [])
        for cat in cats:
            for c in cat.get("coding", []):
                if c.get("code") == "problem-list-item":
                    text = cond.get("code", {}).get("text", "")
                    if text:
                        history_parts.append(text)

    return {
        "age": age,
        "sex": sex,
        "chief_complaint": chief_complaint,
        "vitals": vitals,
        "history": ", ".join(history_parts) if history_parts else "",
    }


def _calc_age(birth_date: str) -> int:
    """birthDate 문자열 → 나이."""
    if not birth_date:
        return 60  # 기본값
    try:
        birth_year = int(birth_date[:4])
        return datetime.now().year - birth_year
    except (ValueError, IndexError):
        return 60


def _convert_vitals(observations: list[dict]) -> dict:
    """FHIR Observation(vital-signs) 리스트 → central vitals dict."""
    vitals = {}

    # LOINC 코드 → central 키 매핑
    loinc_map = {
        "8867-4": ("HR", "bpm"),
        "59408-5": ("SpO2", "%"),
        "9279-1": ("RR", "/min"),
        "8310-5": ("Temp", "°C"),
        "9269-2": ("GCS", ""),
        "85354-9": None,  # BP panel — component에서 처리
        "8480-6": ("SBP", "mmHg"),
        "8462-4": ("DBP", "mmHg"),
    }

    sbp = None
    dbp = None

    for obs in observations:
        # category가 vital-signs인지 확인
        is_vital = False
        for cat in obs.get("category", []):
            for c in cat.get("coding", []):
                if c.get("code") == "vital-signs":
                    is_vital = True
        if not is_vital:
            continue

        code = obs.get("code", {}).get("coding", [{}])[0].get("code", "")

        # BP panel — component에서 SBP/DBP 추출
        if code == "85354-9":
            for comp in obs.get("component", []):
                comp_code = comp.get("code", {}).get("coding", [{}])[0].get("code", "")
                val = comp.get("valueQuantity", {}).get("value")
                if comp_code == "8480-6" and val is not None:
                    sbp = val
                elif comp_code == "8462-4" and val is not None:
                    dbp = val
            if sbp is not None and dbp is not None:
                vitals["BP"] = f"{int(sbp)}/{int(dbp)} mmHg"
            continue

        # 단일 값
        mapping = loinc_map.get(code)
        if mapping:
            key, unit = mapping
            val = obs.get("valueQuantity", {}).get("value")
            if val is not None:
                if unit:
                    vitals[key] = f"{val} {unit}"
                else:
                    vitals[key] = str(val)

    return vitals


# ── central 모달 결과 → FHIR 호환 포맷 ──────────────────

def fhir_observations_to_central_results(observations: list[dict]) -> list[dict]:
    """FHIR Observation(imaging/lab) 리스트 → central inference_results 포맷."""
    results = []
    seen_modalities = set()

    for obs in observations:
        # category에서 모달 종류 판별
        modality = _detect_modality_from_obs(obs)
        if not modality or modality in seen_modalities:
            continue

        finding = obs.get("valueString", "")
        confidence = 0.0

        # component에서 confidence 추출
        for comp in obs.get("component", []):
            unit = comp.get("valueQuantity", {}).get("unit", "")
            if unit == "probability":
                confidence = max(confidence, comp.get("valueQuantity", {}).get("value", 0.0))

        # risk_level 추출 (note에서)
        risk_level = "unknown"
        for note in obs.get("note", []):
            text = note.get("text", "")
            if text.startswith("risk_level:"):
                risk_level = text.replace("risk_level:", "").strip()

        if finding:
            results.append({
                "modality": modality,
                "finding": finding,
                "confidence": confidence,
                "details": {},
                "rationale": finding,
            })
            seen_modalities.add(modality)

    return results


def _detect_modality_from_obs(obs: dict) -> str | None:
    """Observation의 code/category에서 모달 종류 추출."""
    code = obs.get("code", {}).get("coding", [{}])[0].get("code", "")

    if code == "11524-6":
        return "ECG"
    if code == "36643-5":
        return "CXR"

    # category로 판별
    for cat in obs.get("category", []):
        for c in cat.get("coding", []):
            cat_code = c.get("code", "")
            if cat_code == "laboratory":
                return "LAB"
            if cat_code == "imaging":
                # code로 구분 못 하면 display로
                display = obs.get("code", {}).get("coding", [{}])[0].get("display", "").lower()
                if "ecg" in display or "ekg" in display:
                    return "ECG"
                if "chest" in display or "cxr" in display:
                    return "CXR"
                return "CXR"  # 기본 imaging = CXR

    return None
