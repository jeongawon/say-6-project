"""Stage A: Critical Flags — 생명 위협 수치 즉시 감지.

Complaint Profile과 무관하게 모든 입력에 대해 최우선 실행.
CRITICAL_FLAGS 딕셔너리(thresholds.py)의 8개 규칙을 참조한다.
"""

from __future__ import annotations

from typing import List

from shared.schemas import Finding, ProcessedInput
from thresholds import CRITICAL_FLAGS

# Critical Flag별 한국어 detail 및 recommendation
_CRITICAL_DETAILS: dict[str, dict[str, str]] = {
    "potassium_high": {
        "detail": "칼륨 {value} {unit} — 고칼륨혈증으로 심정지 위험이 있습니다.",
        "recommendation": "즉시 심전도 확인 및 칼륨 저하 치료(칼슘 글루코네이트, 인슐린+포도당, 카이엑살레이트) 시작",
    },
    "potassium_low": {
        "detail": "칼륨 {value} {unit} — 저칼륨혈증으로 치명적 부정맥 위험이 있습니다.",
        "recommendation": "즉시 심전도 모니터링 및 칼륨 보충(IV KCl) 시작",
    },
    "sodium_low": {
        "detail": "나트륨 {value} {unit} — 중증 저나트륨혈증으로 경련/뇌부종 위험이 있습니다.",
        "recommendation": "3% NaCl 고장성 식염수 투여 고려, 신경학적 상태 모니터링",
    },
    "glucose_high": {
        "detail": "혈당 {value} {unit} — DKA 또는 HHS 의심 수준의 고혈당입니다.",
        "recommendation": "즉시 혈액가스 분석, 케톤 검사, 인슐린 치료 시작",
    },
    "glucose_low": {
        "detail": "혈당 {value} {unit} — 중증 저혈당으로 즉시 포도당 투여가 필요합니다.",
        "recommendation": "50% 포도당 50mL IV 즉시 투여, 의식 상태 모니터링",
    },
    "lactate_high": {
        "detail": "젖산 {value} {unit} — 조직 저관류 또는 쇼크 상태가 의심됩니다.",
        "recommendation": "즉시 수액 소생술 시작, 감염원 탐색, 혈역학적 모니터링",
    },
    "hemoglobin_low": {
        "detail": "혈색소 {value} {unit} — 중증 빈혈로 수혈을 고려해야 합니다.",
        "recommendation": "농축 적혈구 수혈 준비, 출혈원 탐색, 활력징후 모니터링",
    },
    "platelet_low": {
        "detail": "혈소판 {value} {unit} — 중증 혈소판감소증으로 자발 출혈 위험이 있습니다.",
        "recommendation": "혈소판 수혈 준비, 출혈 징후 관찰, DIC 감별 검사",
    },
}


class CriticalFlagStage:
    """Stage A: 8개 Critical Flag 규칙 실행."""

    def run(self, processed_input: ProcessedInput) -> List[Finding]:
        """Critical Flag 검사를 실행하고 Finding 리스트를 반환한다."""
        findings: List[Finding] = []
        values = processed_input.normalized_values

        for rule_name, rule in CRITICAL_FLAGS.items():
            feature = rule["feature"]
            op = rule["op"]
            threshold = rule["value"]
            flag_label = rule["flag"]

            value = values.get(feature)
            if value is None:
                continue

            triggered = False
            if op == ">" and value > threshold:
                triggered = True
            elif op == "<" and value < threshold:
                triggered = True

            if triggered:
                # NORMAL_RANGES에서 단위 가져오기
                from thresholds import NORMAL_RANGES
                unit = NORMAL_RANGES.get(feature, {}).get("unit", "")

                detail_template = _CRITICAL_DETAILS.get(rule_name, {})
                detail = detail_template.get("detail", flag_label).format(
                    value=value, unit=unit,
                )
                recommendation = detail_template.get("recommendation", "")

                findings.append(Finding(
                    name=f"critical_{rule_name}",
                    confidence=1.0,
                    detail=detail,
                    severity="critical",
                    recommendation=recommendation,
                    category="critical",
                ))

        return findings
