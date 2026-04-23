"""Chief Complaint → Complaint Profile 매핑 모듈.

자유텍스트 주호소를 7개 표준 Profile 중 하나로 매핑한다.
1. Abbreviation Dictionary로 약어 확장
2. 키워드 매칭으로 Profile 후보 선택
3. 다중 매칭 시 위험도 순 선택: CARDIAC > SEPSIS > RESPIRATORY > RENAL > GI > NEUROLOGICAL > GENERAL
4. 매칭 없으면 GENERAL 기본값
"""

from __future__ import annotations

import math
import re
from typing import Optional

# ── Abbreviation Dictionary (30+ 의료 약어 → 정식 명칭) ──────────
ABBREVIATIONS: dict[str, str] = {
    "cp": "chest pain",
    "sob": "shortness of breath",
    "ams": "altered mental status",
    "loc": "loss of consciousness",
    "n/v": "nausea and vomiting",
    "ha": "headache",
    "abd": "abdominal",
    "htn": "hypertension",
    "dm": "diabetes mellitus",
    "chf": "congestive heart failure",
    "copd": "chronic obstructive pulmonary disease",
    "gi": "gastrointestinal",
    "uri": "upper respiratory infection",
    "uti": "urinary tract infection",
    "dvt": "deep vein thrombosis",
    "pe": "pulmonary embolism",
    "mi": "myocardial infarction",
    "cva": "cerebrovascular accident",
    "tia": "transient ischemic attack",
    "etoh": "alcohol",
    "sz": "seizure",
    "hx": "history",
    "dx": "diagnosis",
    "tx": "treatment",
    "rx": "prescription",
    "bid": "twice daily",
    "prn": "as needed",
    "po": "by mouth",
    "iv": "intravenous",
    "im": "intramuscular",
    "afib": "atrial fibrillation",
    "nstemi": "non st elevation myocardial infarction",
    "stemi": "st elevation myocardial infarction",
    "acs": "acute coronary syndrome",
    "cad": "coronary artery disease",
    "dka": "diabetic ketoacidosis",
    "uti": "urinary tract infection",
    "bph": "benign prostatic hyperplasia",
    "lle": "left lower extremity",
    "rle": "right lower extremity",
}

# 약어를 길이 내림차순으로 정렬 (긴 약어 우선 매칭)
_SORTED_ABBREVS = sorted(ABBREVIATIONS.keys(), key=len, reverse=True)

# 약어 매칭용 정규식 패턴 (단어 경계 기반)
_ABBREV_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(rf"\b{re.escape(abbr)}\b", re.IGNORECASE), expansion)
    for abbr, expansion in sorted(ABBREVIATIONS.items(), key=lambda x: len(x[0]), reverse=True)
]

# ── 7개 Profile별 트리거 키워드 ───────────────────────────────────
# 우선순위 순서: CARDIAC > SEPSIS > RESPIRATORY > RENAL > GI > NEUROLOGICAL > GENERAL
PROFILE_KEYWORDS: dict[str, set[str]] = {
    "CARDIAC": {
        "chest pain", "angina", "palpitation", "palpitations",
        "dyspnea on exertion", "cardiac", "heart",
        "myocardial infarction", "acute coronary syndrome",
        "atrial fibrillation", "arrhythmia", "tachycardia",
        "bradycardia", "congestive heart failure", "heart failure",
        "coronary artery disease", "st elevation",
        "non st elevation myocardial infarction",
        "st elevation myocardial infarction",
        "cardiac arrest", "cardiomyopathy",
    },
    "SEPSIS": {
        "fever", "chills", "infection", "sepsis", "septic",
        "bacteremia", "febrile", "rigors", "infected",
        "abscess", "cellulitis", "pneumonia",
        "urinary tract infection", "meningitis",
    },
    "RESPIRATORY": {
        "shortness of breath", "cough", "wheezing", "dyspnea",
        "respiratory", "asthma", "bronchitis",
        "chronic obstructive pulmonary disease",
        "pulmonary embolism", "hemoptysis", "pleurisy",
        "upper respiratory infection", "respiratory distress",
        "oxygen", "hypoxia",
    },
    "RENAL": {
        "flank pain", "oliguria", "anuria", "edema",
        "renal", "kidney", "dialysis", "hematuria",
        "urinary", "dysuria", "nephrolithiasis",
        "kidney stone", "renal failure", "acute kidney",
    },
    "GI": {
        "abdominal pain", "nausea", "vomiting", "diarrhea",
        "melena", "hematemesis", "gastrointestinal",
        "rectal bleeding", "constipation", "bloating",
        "pancreatitis", "hepatitis", "jaundice",
        "abdominal", "stomach", "bowel", "gi bleed",
        "nausea and vomiting", "epigastric",
    },
    "NEUROLOGICAL": {
        "headache", "seizure", "altered mental status",
        "syncope", "dizziness", "vertigo", "stroke",
        "cerebrovascular accident", "transient ischemic attack",
        "numbness", "weakness", "confusion",
        "loss of consciousness", "unresponsive",
        "facial droop", "slurred speech", "tremor",
    },
    "GENERAL": set(),  # fallback — 키워드 매칭 불필요
}

# 우선순위 순서 (인덱스가 낮을수록 높은 우선순위)
PRIORITY_ORDER: list[str] = [
    "CARDIAC",
    "SEPSIS",
    "RESPIRATORY",
    "RENAL",
    "GI",
    "NEUROLOGICAL",
    "GENERAL",
]


class ComplaintMapper:
    """자유텍스트 주호소 → 7개 Complaint Profile 매핑."""

    def expand_abbreviations(self, text: str) -> str:
        """약어를 정식 명칭으로 확장한다. 멱등(idempotent)."""
        if not isinstance(text, str) or not text.strip():
            return text if isinstance(text, str) else ""
        result = text
        for pattern, expansion in _ABBREV_PATTERNS:
            result = pattern.sub(expansion, result)
        return result

    def map_to_profile(self, chief_complaint: Optional[str] = None) -> str:
        """주호소 텍스트를 7개 Profile 중 하나로 매핑한다.

        NaN, None, float 등 비정상 입력은 GENERAL로 처리한다.
        """
        # NaN / None / float 등 비정상 입력 처리
        if chief_complaint is None:
            return "GENERAL"
        if isinstance(chief_complaint, float):
            if math.isnan(chief_complaint):
                return "GENERAL"
            return "GENERAL"
        if not isinstance(chief_complaint, str):
            return "GENERAL"
        if not chief_complaint.strip():
            return "GENERAL"

        # 약어 확장 후 소문자 변환
        expanded = self.expand_abbreviations(chief_complaint).lower()

        # 우선순위 순서대로 키워드 매칭
        matched_profiles: list[str] = []
        for profile in PRIORITY_ORDER:
            if profile == "GENERAL":
                continue
            keywords = PROFILE_KEYWORDS[profile]
            for keyword in keywords:
                if keyword in expanded:
                    matched_profiles.append(profile)
                    break

        if not matched_profiles:
            return "GENERAL"

        # 우선순위가 가장 높은 Profile 반환
        for profile in PRIORITY_ORDER:
            if profile in matched_profiles:
                return profile

        return "GENERAL"
