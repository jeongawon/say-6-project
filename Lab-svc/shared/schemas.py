from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from pydantic import BaseModel


# ── 입력 스키마 ───────────────────────────────────────────────────

class LabValues(BaseModel):
    """12개 Value_Feature — 모두 Optional (미측정 허용)"""

    wbc: Optional[float] = None          # K/uL
    hemoglobin: Optional[float] = None   # g/dL
    platelet: Optional[float] = None     # K/uL
    creatinine: Optional[float] = None   # mg/dL
    bun: Optional[float] = None          # mg/dL
    sodium: Optional[float] = None       # mEq/L
    potassium: Optional[float] = None    # mEq/L
    glucose: Optional[float] = None      # mg/dL
    ast: Optional[float] = None          # U/L
    albumin: Optional[float] = None      # g/dL
    lactate: Optional[float] = None      # mmol/L
    calcium: Optional[float] = None      # mg/dL


class PatientInfo(BaseModel):
    """환자 기본 정보 — CXR/ECG 스키마 통일"""
    age: Optional[float] = None
    sex: Optional[str] = None            # "M" / "F"
    chief_complaint: str = ""
    history: List[str] = []


class LabData(BaseModel):
    """혈액검사 데이터 래핑 — CXR/ECG data 필드 패턴 통일"""
    lab_values: LabValues


class PredictRequest(BaseModel):
    """변경 #2: patient_info + data 래핑 (CXR/ECG 스키마 통일)"""
    patient_id: str
    patient_info: Optional[PatientInfo] = None
    data: LabData
    context: dict = {}                   # 다른 모달 소견 (Cross-modal Confirmer용)


# ── Finding 스키마 ────────────────────────────────────────────────

class Measurement(BaseModel):
    """변경 #4: 구조화 수치 — FHIR valueQuantity 매핑, 프론트 파싱용"""
    value: Optional[float] = None
    unit: str = ""
    reference_low: Optional[float] = None
    reference_high: Optional[float] = None
    status: str = "normal"               # normal / low / high / critical_low / critical_high


class Finding(BaseModel):
    name: str
    confidence: float = 1.0              # Rule Engine에서는 항상 1.0
    detail: str = ""
    severity: Optional[str] = None       # mild / moderate / severe / critical
    recommendation: Optional[str] = None
    category: str = "primary"            # critical / primary / secondary
    measurement: Optional[Measurement] = None  # 변경 #4


# ── Cross-modal → SuggestedNextAction ─────────────────────────────

class SuggestedNextAction(BaseModel):
    """변경 #3: CrossModalHint → SuggestedNextAction 리네이밍 (CXR 통일)"""
    target_modal: str                    # "ECG" 또는 "CXR"
    reason: str
    urgency: str = "routine"             # routine / urgent
    priority: int = 0                    # 변경 #3: 우선순위 (0=기본, 높을수록 긴급)


# ── Lab Summary Item ──────────────────────────────────────────────

class LabSummaryItem(BaseModel):
    """변경 #5: 15개 항목 전체 테이블 — 프론트 Lab Summary 테이블용"""
    feature: str                         # "wbc", "hemoglobin", ...
    value: Optional[float] = None
    unit: str = ""
    reference_low: Optional[float] = None
    reference_high: Optional[float] = None
    status: str = "normal"               # normal / low / high / critical_low / critical_high / not_measured
    measured: bool = False


# ── 응답 스키마 ───────────────────────────────────────────────────

class PredictResponse(BaseModel):
    status: str
    modal: str = "lab"
    findings: List[Finding] = []
    summary: str = ""
    risk_level: str = "routine"          # 변경 #1: 소문자 (critical/urgent/watch/routine)
    suggested_next_actions: List[SuggestedNextAction] = []  # 변경 #3
    complaint_profile: str = "GENERAL"
    lab_summary: List[LabSummaryItem] = []   # 변경 #5: 15개 항목 전체 테이블
    measurements: dict = {}              # 변경 #6: CXR 패턴 동일 요약 지표
    metadata: dict = {}
    error: Optional[str] = None


# ── 내부 처리 모델 ────────────────────────────────────────────────

@dataclass
class ProcessedInput:
    """Layer 1 출력 — 정규화된 입력 데이터"""

    normalized_values: dict[str, Optional[float]]  # 12개 Value_Feature
    indicators: dict[str, int]                      # 7개 Indicator (0 or 1)
    complaint_profile: str                          # 7개 Profile 중 하나
    validation_warnings: list[str] = field(default_factory=list)
    context: dict = field(default_factory=dict)     # 다른 모달 소견 (pass-through)
