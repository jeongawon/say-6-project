"""Layer 1: Input Processor — 입력 검증, 정규화, Indicator 생성.

책임:
1. 12개 Value_Feature 수치 타입 검증 + 유효 범위 검증
2. 유효 범위 이탈 시 None 처리 + validation_warnings 추가
3. 7개 Indicator 자동 생성 (has_ast, has_albumin, has_lactate, has_calcium,
   has_troponin_t, has_bnp, has_amylase)
4. Chief Complaint → Complaint Profile 매핑 (ComplaintMapper 위임)

출력: ProcessedInput(normalized_values, indicators, complaint_profile, validation_warnings)
"""

from __future__ import annotations

from typing import Optional

from layer1_input_processor.complaint_mapper import ComplaintMapper
from shared.schemas import LabValues, PredictRequest, ProcessedInput
from thresholds import VALID_RANGES

# 12개 Value_Feature 이름 목록
VALUE_FEATURES: list[str] = [
    "wbc", "hemoglobin", "platelet", "creatinine", "bun",
    "sodium", "potassium", "glucose", "ast", "albumin",
    "lactate", "calcium",
]

# Tier 2 항목 (값 + indicator 사용)
TIER2_FEATURES: set[str] = {"ast", "albumin", "lactate", "calcium"}

# Tier 3 항목 (indicator만 사용 — LabValues에 수치 필드 없음)
TIER3_FEATURES: set[str] = {"troponin_t", "bnp", "amylase"}

# Indicator 대상 Feature 매핑
INDICATOR_FEATURES: dict[str, str] = {
    "has_ast": "ast",
    "has_albumin": "albumin",
    "has_lactate": "lactate",
    "has_calcium": "calcium",
    "has_troponin_t": "troponin_t",
    "has_bnp": "bnp",
    "has_amylase": "amylase",
}


class InputProcessor:
    """입력 데이터 검증, 정규화, indicator 생성, Profile 매핑."""

    def __init__(self) -> None:
        self._mapper = ComplaintMapper()

    # ── public API ────────────────────────────────────────────────
    def process(self, request: PredictRequest) -> ProcessedInput:
        """PredictRequest → ProcessedInput 변환."""
        warnings: list[str] = []

        # 1) 수치 검증 + 정규화 (변경 #2: data.lab_values 래핑)
        lab_values = request.data.lab_values
        normalized = self._validate_and_normalize(lab_values, warnings)

        # 2) Indicator 생성
        indicators = self._generate_indicators(lab_values)

        # 3) Complaint Profile 매핑 (변경 #2: patient_info.chief_complaint)
        chief_complaint = ""
        if request.patient_info:
            chief_complaint = request.patient_info.chief_complaint
        profile = self._mapper.map_to_profile(chief_complaint)

        return ProcessedInput(
            normalized_values=normalized,
            indicators=indicators,
            complaint_profile=profile,
            validation_warnings=warnings,
            context=request.context,
        )

    # ── 내부 메서드 ───────────────────────────────────────────────
    def _validate_and_normalize(
        self,
        lab_values: LabValues,
        warnings: list[str],
    ) -> dict[str, Optional[float]]:
        """12개 Value_Feature에 대해 유효 범위 검증 후 정규화된 dict 반환."""
        normalized: dict[str, Optional[float]] = {}

        for feature in VALUE_FEATURES:
            value = getattr(lab_values, feature, None)

            if value is None:
                normalized[feature] = None
                continue

            # VALID_RANGES 기반 유효 범위 검증
            vr = VALID_RANGES.get(feature)
            if vr is None:
                # 유효 범위 정의가 없으면 그대로 통과
                normalized[feature] = value
                continue

            if value < vr["min"] or value > vr["max"]:
                warnings.append(
                    f"{feature} 값 {value}이(가) 유효 범위 "
                    f"[{vr['min']}, {vr['max']}]을 벗어남 → None 처리"
                )
                normalized[feature] = None
            else:
                normalized[feature] = value

        return normalized

    def _generate_indicators(self, lab_values: LabValues) -> dict[str, int]:
        """7개 Indicator 자동 생성.

        Tier 2 (ast, albumin, lactate, calcium): LabValues 필드 값이 None이 아니면 1
        Tier 3 (troponin_t, bnp, amylase): LabValues에 수치 필드가 없으므로 항상 0
              (향후 context 등에서 측정 여부를 전달받을 수 있도록 확장 가능)
        """
        indicators: dict[str, int] = {}

        for indicator_name, feature_name in INDICATOR_FEATURES.items():
            value = getattr(lab_values, feature_name, None)
            indicators[indicator_name] = 1 if value is not None else 0

        return indicators
