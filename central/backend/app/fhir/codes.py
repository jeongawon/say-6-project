"""§5 코드 시스템 사전 — LOINC / ICD-10 / SNOMED 매핑 테이블."""

# ── 5.1 LOINC — Vitals ───────────────────────────────────
LOINC_VITALS = {
    "hr":   {"code": "8867-4",  "display": "Heart rate",           "unit": "/min"},
    "sbp":  {"code": "8480-6",  "display": "Systolic blood pressure",  "unit": "mm[Hg]"},
    "dbp":  {"code": "8462-4",  "display": "Diastolic blood pressure", "unit": "mm[Hg]"},
    "bp":   {"code": "85354-9", "display": "Blood pressure panel", "unit": "(component)"},
    "spo2": {"code": "59408-5", "display": "Oxygen saturation",   "unit": "%"},
    "rr":   {"code": "9279-1",  "display": "Respiratory rate",    "unit": "/min"},
    "temp": {"code": "8310-5",  "display": "Body temperature",    "unit": "Cel"},
    "gcs":  {"code": "9269-2",  "display": "Glasgow coma score total", "unit": "{score}"},
}

# ── 5.2 LOINC — Lab ──────────────────────────────────────
LOINC_LAB = {
    "troponin":   {"code": "6598-7", "display": "Troponin T cardiac", "unit": "ng/mL"},
    "hemoglobin": {"code": "718-7",  "display": "Hemoglobin",         "unit": "g/dL"},
    "creatinine": {"code": "2160-0", "display": "Creatinine",         "unit": "mg/dL"},
    "potassium":  {"code": "2823-3", "display": "Potassium",          "unit": "mmol/L"},
    "sodium":     {"code": "2951-2", "display": "Sodium",             "unit": "mmol/L"},
    "lactate":    {"code": "2524-7", "display": "Lactate",            "unit": "mmol/L"},
    "wbc":        {"code": "6690-2", "display": "WBC count",          "unit": "10*3/uL"},
    "bun":        {"code": "3094-0", "display": "BUN",                "unit": "mg/dL"},
    "glucose":    {"code": "2345-7", "display": "Glucose",            "unit": "mg/dL"},
}

# ── 5.3 LOINC — Modality ─────────────────────────────────
LOINC_MODALITY = {
    "cxr":          {"code": "36643-5", "display": "Chest X-ray PA and Lateral"},
    "ecg":          {"code": "11524-6", "display": "EKG study"},
    "consultation": {"code": "11488-4", "display": "Consultation note"},
}

# ── 5.4 ICD-10-CM — 주호소/과거력 ────────────────────────
ICD10_MAP = {
    "흉통":       {"code": "R07.9",   "display": "Chest pain, unspecified"},
    "호흡곤란":   {"code": "R06.02",  "display": "Shortness of breath"},
    "기침":       {"code": "R05.9",   "display": "Cough"},
    "우하복부 통증": {"code": "R10.31", "display": "RLQ pain"},
    "패혈증":     {"code": "R65.21",  "display": "Severe sepsis"},
    "고혈압":     {"code": "I10",     "display": "Essential hypertension"},
    "제2형 당뇨": {"code": "E11.9",   "display": "Type 2 DM"},
    "흡연":       {"code": "F17.210", "display": "Nicotine dependence"},
}

# ── 5.5 SNOMED CT — 확정 진단 ────────────────────────────
SNOMED_DIAGNOSIS = {
    "stemi":                {"code": "401303003", "display": "Acute ST elevation MI"},
    "tension_pneumothorax": {"code": "63269006",  "display": "Tension pneumothorax"},
    "pneumonia":            {"code": "233604007", "display": "Pneumonia"},
    "appendicitis":         {"code": "74400008",  "display": "Appendicitis"},
    "sepsis":               {"code": "91302008",  "display": "Sepsis"},
}

# ── 5.6 category / status 고정 코드 ──────────────────────
OBS_CATEGORY_VITAL = {
    "system": "http://terminology.hl7.org/CodeSystem/observation-category",
    "code": "vital-signs",
}
OBS_CATEGORY_LAB = {
    "system": "http://terminology.hl7.org/CodeSystem/observation-category",
    "code": "laboratory",
}
OBS_CATEGORY_IMAGING = {
    "system": "http://terminology.hl7.org/CodeSystem/observation-category",
    "code": "imaging",
}
ENCOUNTER_CLASS_EMER = {
    "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
    "code": "EMER",
}
