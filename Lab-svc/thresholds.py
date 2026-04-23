"""
임상 정상 범위, Critical Flag 임계값, 생리학적 유효 범위 중앙 관리 모듈.

모든 혈액검사 해석 규칙이 참조하는 단일 설정 파일.
코드 변경 없이 임계값을 조정할 수 있도록 딕셔너리로 관리한다.
"""

# ── 12개 Value_Feature 임상 정상 범위 ──────────────────────────────
NORMAL_RANGES: dict[str, dict] = {
    "wbc":        {"low": 4.5,  "high": 11.0,  "unit": "K/uL"},
    "hemoglobin": {"low": 12.0, "high": 17.5,  "unit": "g/dL"},
    "platelet":   {"low": 150,  "high": 400,   "unit": "K/uL"},
    "creatinine": {"low": 0.7,  "high": 1.2,   "unit": "mg/dL"},
    "bun":        {"low": 7,    "high": 20,    "unit": "mg/dL"},
    "sodium":     {"low": 136,  "high": 145,   "unit": "mEq/L"},
    "potassium":  {"low": 3.5,  "high": 5.0,   "unit": "mEq/L"},
    "glucose":    {"low": 70,   "high": 100,   "unit": "mg/dL"},
    "ast":        {"low": 0,    "high": 40,    "unit": "U/L"},
    "albumin":    {"low": 3.5,  "high": 5.5,   "unit": "g/dL"},
    "lactate":    {"low": 0.5,  "high": 2.0,   "unit": "mmol/L"},
    "calcium":    {"low": 8.5,  "high": 10.5,  "unit": "mg/dL"},
}

# ── 8개 Critical Flag 규칙 ─────────────────────────────────────────
CRITICAL_FLAGS: dict[str, dict] = {
    "potassium_high": {"feature": "potassium",  "op": ">", "value": 6.5, "flag": "심정지 위험"},
    "potassium_low":  {"feature": "potassium",  "op": "<", "value": 2.5, "flag": "치명적 부정맥 위험"},
    "sodium_low":     {"feature": "sodium",     "op": "<", "value": 120, "flag": "경련/뇌부종 위험"},
    "glucose_high":   {"feature": "glucose",    "op": ">", "value": 500, "flag": "DKA/HHS 의심"},
    "glucose_low":    {"feature": "glucose",    "op": "<", "value": 40,  "flag": "즉시 포도당 투여"},
    "lactate_high":   {"feature": "lactate",    "op": ">", "value": 4.0, "flag": "조직 저관류/쇼크"},
    "hemoglobin_low": {"feature": "hemoglobin", "op": "<", "value": 7.0, "flag": "수혈 고려"},
    "platelet_low":   {"feature": "platelet",   "op": "<", "value": 20,  "flag": "자발 출혈 위험"},
}

# ── 12개 Feature 생리학적 유효 범위 (불가능한 값 필터링) ──────────
VALID_RANGES: dict[str, dict] = {
    "wbc":        {"min": 0.1,  "max": 500},
    "hemoglobin": {"min": 1.0,  "max": 25.0},
    "platelet":   {"min": 1,    "max": 2000},
    "creatinine": {"min": 0.1,  "max": 30.0},
    "bun":        {"min": 1,    "max": 300},
    "sodium":     {"min": 100,  "max": 200},
    "potassium":  {"min": 1.0,  "max": 12.0},
    "glucose":    {"min": 10,   "max": 2000},
    "ast":        {"min": 0,    "max": 10000},
    "albumin":    {"min": 0.5,  "max": 7.0},
    "lactate":    {"min": 0.1,  "max": 30.0},
    "calcium":    {"min": 3.0,  "max": 18.0},
}
