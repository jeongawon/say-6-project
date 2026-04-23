"""Layer 3: Report Generator — Finding 분류, risk_level, suggested_next_actions, summary.

변경사항 반영:
#1 risk_level 소문자 (critical/urgent/watch/routine)
#3 CrossModalHint → SuggestedNextAction + priority
#4 Finding.measurement 추가
#5 lab_summary 추가 (15개 항목 전체 테이블)
#6 measurements 추가 (CXR 패턴 동일 요약 지표)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from shared.schemas import (
    Finding,
    LabSummaryItem,
    Measurement,
    PredictRequest,
    PredictResponse,
    ProcessedInput,
    SuggestedNextAction,
)
from thresholds import NORMAL_RANGES


class ReportGenerator:
    """Layer 3: 리포트 생성기."""

    def generate(
        self,
        findings: List[Finding],
        processed_input: ProcessedInput,
        request: PredictRequest,
    ) -> PredictResponse:
        risk_level = self._determine_risk_level(findings)

        # Finding에 measurement 추가 (#4)
        findings = self._attach_measurements(findings, processed_input.normalized_values)

        actions = self._generate_suggested_actions(
            processed_input.normalized_values,
            processed_input.indicators,
            processed_input.complaint_profile,
        )
        summary = self._generate_summary(findings, risk_level, processed_input.complaint_profile)
        lab_summary = self._generate_lab_summary(processed_input.normalized_values)
        measurements = self._generate_measurements(findings)

        return PredictResponse(
            status="ok",
            modal="lab",
            findings=findings,
            summary=summary,
            risk_level=risk_level,
            suggested_next_actions=actions,
            complaint_profile=processed_input.complaint_profile,
            lab_summary=lab_summary,
            measurements=measurements,
            metadata={
                "patient_id": request.patient_id,
                "latency_ms": 0.0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    # ── #1: risk_level 소문자 ─────────────────────────────────────
    @staticmethod
    def _determine_risk_level(findings: List[Finding]) -> str:
        critical_count = sum(1 for f in findings if f.category == "critical")
        if critical_count >= 1:
            return "critical"

        primary_abnormal = [
            f for f in findings
            if f.category == "primary" and not f.name.startswith("unmeasured_")
        ]
        unmeasured_warnings = [f for f in findings if f.name.startswith("unmeasured_")]

        if len(primary_abnormal) >= 2:
            return "urgent"
        if len(primary_abnormal) >= 1 or len(unmeasured_warnings) >= 1:
            return "watch"
        return "routine"

    # ── #4: Finding에 measurement 추가 ────────────────────────────
    @staticmethod
    def _attach_measurements(
        findings: List[Finding], values: dict,
    ) -> List[Finding]:
        for f in findings:
            # Finding name에서 feature 추출 (예: cardiac_potassium_high → potassium)
            for feat, nr in NORMAL_RANGES.items():
                if feat in f.name:
                    val = values.get(feat)
                    if val is not None:
                        status = "normal"
                        if val > nr["high"]:
                            status = "high"
                        elif val < nr["low"]:
                            status = "low"
                        f.measurement = Measurement(
                            value=val,
                            unit=nr.get("unit", ""),
                            reference_low=nr["low"],
                            reference_high=nr["high"],
                            status=status,
                        )
                    break
        return findings

    # ── #3: SuggestedNextAction ───────────────────────────────────
    @staticmethod
    def _generate_suggested_actions(
        values: dict, indicators: dict, profile: str,
    ) -> List[SuggestedNextAction]:
        actions: List[SuggestedNextAction] = []

        k = values.get("potassium")
        if k is not None and (k > 5.5 or k < 3.0):
            actions.append(SuggestedNextAction(
                target_modal="ECG",
                reason=f"칼륨 {k} mEq/L — 전해질 이상으로 심전도 변화 확인 필요",
                urgency="urgent" if k > 6.0 or k < 2.5 else "routine",
                priority=10 if k > 6.0 or k < 2.5 else 5,
            ))

        if indicators.get("has_troponin_t", 0) == 1 and profile == "CARDIAC":
            actions.append(SuggestedNextAction(
                target_modal="ECG",
                reason="트로포닌 T 측정됨 + CARDIAC — ACS 의심, ST 변화 교차 확인",
                urgency="urgent",
                priority=10,
            ))

        if indicators.get("has_bnp", 0) == 1 and profile == "RESPIRATORY":
            actions.append(SuggestedNextAction(
                target_modal="CXR",
                reason="BNP 측정됨 + RESPIRATORY — 심부전 의심, 폐부종/심비대 확인",
                urgency="urgent",
                priority=8,
            ))

        wbc = values.get("wbc")
        if wbc is not None and wbc > 12 and profile == "SEPSIS":
            actions.append(SuggestedNextAction(
                target_modal="CXR",
                reason=f"백혈구 {wbc} K/uL + SEPSIS — 감염 초점, 폐렴 확인",
                urgency="urgent",
                priority=8,
            ))

        lac = values.get("lactate")
        if lac is not None and lac > 2.0:
            actions.append(SuggestedNextAction(
                target_modal="ECG",
                reason=f"젖산 {lac} mmol/L — 심근 기능 영향 확인",
                urgency="urgent" if lac > 4.0 else "routine",
                priority=9 if lac > 4.0 else 4,
            ))

        # priority 내림차순 정렬
        actions.sort(key=lambda a: a.priority, reverse=True)
        return actions

    # ── #5: lab_summary (15개 항목 전체 테이블) ────────────────────
    @staticmethod
    def _generate_lab_summary(values: dict) -> List[LabSummaryItem]:
        items: List[LabSummaryItem] = []
        for feat, nr in NORMAL_RANGES.items():
            val = values.get(feat)
            measured = val is not None
            status = "not_measured"
            if measured:
                if val > nr["high"]:
                    status = "high"
                elif val < nr["low"]:
                    status = "low"
                else:
                    status = "normal"
            items.append(LabSummaryItem(
                feature=feat,
                value=val,
                unit=nr.get("unit", ""),
                reference_low=nr["low"],
                reference_high=nr["high"],
                status=status,
                measured=measured,
            ))
        return items

    # ── #6: measurements (CXR 패턴 동일 요약 지표) ────────────────
    @staticmethod
    def _generate_measurements(findings: List[Finding]) -> dict:
        critical_count = sum(1 for f in findings if f.category == "critical")
        primary_count = sum(
            1 for f in findings
            if f.category == "primary" and not f.name.startswith("unmeasured_")
        )
        secondary_count = sum(1 for f in findings if f.category == "secondary")
        unmeasured_count = sum(1 for f in findings if f.name.startswith("unmeasured_"))
        return {
            "critical_count": critical_count,
            "primary_count": primary_count,
            "secondary_count": secondary_count,
            "unmeasured_count": unmeasured_count,
            "total_findings": len(findings),
        }

    # ── summary 생성 ──────────────────────────────────────────────
    @staticmethod
    def _generate_summary(
        findings: List[Finding], risk_level: str, profile: str,
    ) -> str:
        if not findings:
            return f"[{risk_level}] 혈액검사 수치가 모두 정상 범위 내에 있습니다."

        risk_label = {
            "critical": "긴급", "urgent": "주의 필요",
            "watch": "관찰 필요", "routine": "정상",
        }.get(risk_level, risk_level)

        critical_findings = [f for f in findings if f.category == "critical"]
        primary_findings = [
            f for f in findings
            if f.category == "primary" and not f.name.startswith("unmeasured_")
        ]

        parts: list[str] = [f"[{risk_level}] 위험도: {risk_label}."]
        if critical_findings:
            names = ", ".join(f.detail.split("—")[0].strip() for f in critical_findings[:3])
            parts.append(f"Critical: {names}.")
        if primary_findings:
            names = ", ".join(f.detail.split("—")[0].strip() for f in primary_findings[:3])
            parts.append(f"주요 소견: {names}.")
        parts.append(f"프로파일: {profile}.")
        return " ".join(parts)
