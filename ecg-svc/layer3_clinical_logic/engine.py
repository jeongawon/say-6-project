"""
Layer 3: 임상 의사결정 엔진

역할:
  - 모델 확률 → Threshold 적용 → detected 여부 판정
  - 중증도(severity) / 권고사항(recommendation) 매핑
  - 전체 위험도(risk_level) 산출: critical / urgent / routine
  - 요약 문자열 생성

다음 모달 결정은 중앙 오케스트레이터(Bedrock Agent)가 담당.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from shared.labels import LABEL_NAMES, LABEL_KO, LABEL_SEVERITY, LABEL_RECOMMENDATION
from shared.schemas import Finding
from thresholds import get_threshold, TIER_MAP

logger = logging.getLogger(__name__)

_CRITICAL_SEVERITIES = {"critical"}
_URGENT_SEVERITIES   = {"severe", "critical"}


@dataclass
class ClinicalResult:
    findings:   list[Finding] = field(default_factory=list)
    risk_level: str           = "routine"
    summary:    str           = ""


class ClinicalEngine:
    def run(self, probs: dict[str, float]) -> ClinicalResult:
        findings   = self._build_findings(probs)   # threshold 통과한 것만
        risk_level = self._calc_risk_level(findings)
        summary    = self._summary(findings, risk_level)
        return ClinicalResult(findings=findings, risk_level=risk_level, summary=summary)

    # ------------------------------------------------------------------
    def _build_findings(self, probs: dict[str, float]) -> list[Finding]:
        findings = []
        for label in LABEL_NAMES:
            prob     = probs.get(label, 0.0)
            detected = prob >= get_threshold(label)
            if not detected:
                continue
            findings.append(Finding(
                name=label,
                confidence=round(prob, 4),
                detail=f"{LABEL_KO.get(label, label)} (신뢰도 {prob:.1%})",
                severity=LABEL_SEVERITY.get(label),
                recommendation=LABEL_RECOMMENDATION.get(label),
            ))
        return findings

    @staticmethod
    def _calc_risk_level(detected: list[Finding]) -> str:
        severities = {f.severity for f in detected}
        if severities & _CRITICAL_SEVERITIES:
            return "critical"
        if severities & _URGENT_SEVERITIES:
            return "urgent"
        if detected:
            return "urgent"
        return "routine"

    @staticmethod
    def _summary(detected: list[Finding], risk_level: str) -> str:
        if not detected:
            return "ECG 분석 결과 유의한 이상 소견 없음"
        ko_names = [LABEL_KO.get(f.name, f.name) for f in detected[:5]]
        extra    = f" 외 {len(detected) - 5}건" if len(detected) > 5 else ""
        risk_ko  = {"critical": "위험", "urgent": "주의", "routine": "정상"}[risk_level]
        return f"[{risk_ko}] {', '.join(ko_names)}{extra} 이상 소견 감지"
