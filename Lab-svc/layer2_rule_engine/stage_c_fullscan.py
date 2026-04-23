"""Stage C: Full Scan — Stage B 미검사 항목 전체 스캔.

Stage B에서 검사하지 않은 나머지 Value_Feature에 대해
임상 정상 범위(thresholds.py)와 비교하여 이상 소견을 탐지한다.
생성되는 Finding의 category는 "secondary"로 설정된다.
"""

from __future__ import annotations

from typing import List, Set

from shared.schemas import Finding, ProcessedInput
from thresholds import NORMAL_RANGES

# 12개 Value_Feature 전체 목록
ALL_VALUE_FEATURES: set[str] = {
    "wbc", "hemoglobin", "platelet", "creatinine", "bun",
    "sodium", "potassium", "glucose", "ast", "albumin",
    "lactate", "calcium",
}


class FullScanStage:
    """Stage C: Stage B 미검사 항목에 대한 전체 스캔."""

    def run(
        self,
        processed_input: ProcessedInput,
        excluded_features: Set[str],
    ) -> List[Finding]:
        """Stage B에서 검사하지 않은 나머지 Feature를 스캔한다.

        Args:
            processed_input: Layer 1 출력 데이터
            excluded_features: Stage B에서 이미 검사한 Feature 집합

        Returns:
            category="secondary"인 Finding 리스트
        """
        findings: List[Finding] = []
        values = processed_input.normalized_values

        # Stage B에서 검사하지 않은 Feature만 대상
        remaining = ALL_VALUE_FEATURES - excluded_features

        for feature in sorted(remaining):  # 정렬하여 결정론적 순서 보장
            value = values.get(feature)
            if value is None:
                continue

            nr = NORMAL_RANGES.get(feature)
            if nr is None:
                continue

            low = nr["low"]
            high = nr["high"]
            unit = nr.get("unit", "")

            if value < low:
                severity = self._determine_severity(feature, value, low, high, "low")
                findings.append(Finding(
                    name=f"secondary_{feature}_low",
                    confidence=1.0,
                    detail=f"{feature} {value} {unit} — 정상 범위({low}–{high}) 미만",
                    severity=severity,
                    recommendation=f"{feature} 수치 저하 원인 평가 필요",
                    category="secondary",
                ))
            elif value > high:
                severity = self._determine_severity(feature, value, low, high, "high")
                findings.append(Finding(
                    name=f"secondary_{feature}_high",
                    confidence=1.0,
                    detail=f"{feature} {value} {unit} — 정상 범위({low}–{high}) 초과",
                    severity=severity,
                    recommendation=f"{feature} 수치 상승 원인 평가 필요",
                    category="secondary",
                ))

        return findings

    @staticmethod
    def _determine_severity(
        feature: str, value: float, low: float, high: float, direction: str,
    ) -> str:
        """이탈 정도에 따라 severity를 결정한다.

        정상 범위 대비 이탈 비율:
        - < 50% 이탈: mild
        - 50~100% 이탈: moderate
        - > 100% 이탈: severe
        """
        if direction == "high":
            range_span = high - low if high > low else 1
            deviation = (value - high) / range_span
        else:
            range_span = high - low if high > low else 1
            deviation = (low - value) / range_span

        if deviation > 1.0:
            return "severe"
        if deviation > 0.5:
            return "moderate"
        return "mild"
