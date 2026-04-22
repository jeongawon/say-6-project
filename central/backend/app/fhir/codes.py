"""
§5 코드 시스템 사전 — LOINC / ICD-10 / SNOMED 매핑 테이블.

[이 파일이 하는 일]
의료 코드 사전. FHIR에서는 "심박수"를 그냥 "심박수"라고 안 쓰고
LOINC 코드 8867-4로 써야 해요. 이 파일이 그 매핑 테이블.

[코드 시스템 3종]
- LOINC: 검사/측정 항목 코드 (심박수=8867-4, Troponin=6598-7 등)
- ICD-10: 진단/증상 코드 (흉통=R07.9, 고혈압=I10 등)
- SNOMED: 확정 진단 코드 (STEMI=401303003, 폐렴=233604007 등)

[ECG 24개 + CXR 7개 레이블]
각 모달 서비스에서 나오는 레이블(acute_mi, Cardiomegaly 등)에 대응하는
SNOMED 코드가 SNOMED_DIAGNOSIS에 전부 들어있음.
"""

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
# ECG 24개 + CXR 7개 레이블에 대응하는 SNOMED 코드
SNOMED_DIAGNOSIS = {
    # ── ECG 레이블 (24개) ────────────────────────────────
    "afib_flutter":           {"code": "49436004",  "display": "Atrial fibrillation/flutter"},
    "heart_failure":          {"code": "84114007",  "display": "Heart failure"},
    "hypertension":           {"code": "38341003",  "display": "Hypertension"},
    "chronic_ihd":            {"code": "413838009", "display": "Chronic ischemic heart disease"},
    "acute_mi":               {"code": "401303003", "display": "Acute ST elevation MI"},
    "paroxysmal_tachycardia": {"code": "67198005",  "display": "Paroxysmal tachycardia"},
    "av_block_lbbb":          {"code": "6374002",   "display": "AV block / LBBB"},
    "other_conduction":       {"code": "44808001",  "display": "Conduction disorder"},
    "pulmonary_embolism":     {"code": "59282003",  "display": "Pulmonary embolism"},
    "cardiac_arrest":         {"code": "410429000", "display": "Cardiac arrest"},
    "angina":                 {"code": "194828000", "display": "Angina pectoris"},
    "pericardial_disease":    {"code": "3238004",   "display": "Pericardial disease"},
    "afib_detail":            {"code": "49436004",  "display": "Atrial fibrillation (detail)"},
    "hf_detail":              {"code": "84114007",  "display": "Heart failure (detail)"},
    "dm2":                    {"code": "44054006",  "display": "Type 2 diabetes mellitus"},
    "acute_kidney_failure":   {"code": "14669001",  "display": "Acute kidney failure"},
    "hypothyroidism":         {"code": "40930008",  "display": "Hypothyroidism"},
    "copd":                   {"code": "13645005",  "display": "COPD"},
    "chronic_kidney":         {"code": "709044004", "display": "Chronic kidney disease"},
    "hyperkalemia":           {"code": "14140009",  "display": "Hyperkalemia"},
    "hypokalemia":            {"code": "43339004",  "display": "Hypokalemia"},
    "respiratory_failure":    {"code": "409623005", "display": "Respiratory failure"},
    "sepsis":                 {"code": "91302008",  "display": "Sepsis"},
    "calcium_disorder":       {"code": "88092000",  "display": "Calcium metabolism disorder"},
    # ── CXR 레이블 (7개) ─────────────────────────────────
    "cardiomegaly":                {"code": "8186001",   "display": "Cardiomegaly"},
    "enlarged_cardiomediastinum":  {"code": "274098007", "display": "Enlarged cardiomediastinum"},
    "edema":                       {"code": "19242006",  "display": "Pulmonary edema"},
    "atelectasis":                 {"code": "46621007",  "display": "Atelectasis"},
    "pleural_effusion":            {"code": "60046008",  "display": "Pleural effusion"},
    "pneumothorax":                {"code": "36118008",  "display": "Pneumothorax"},
    "tension_pneumothorax":        {"code": "63269006",  "display": "Tension pneumothorax"},
    "pneumonia":                   {"code": "233604007", "display": "Pneumonia"},
    "no_finding":                  {"code": "260413007", "display": "No abnormality detected"},
    # ── 기타 (FHIR 문서 원본) ────────────────────────────
    "stemi":                  {"code": "401303003", "display": "Acute ST elevation MI"},
    "appendicitis":           {"code": "74400008",  "display": "Appendicitis"},
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
