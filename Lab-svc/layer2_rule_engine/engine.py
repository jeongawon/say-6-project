"""Layer 2: Rule Engine — 3-Stage 순차 실행 오케스트레이션.

Stage A (Critical Flags) → Stage B (Complaint-Focused) → Stage C (Full Scan)
순서로 실행하고, 각 Stage의 Finding 리스트를 합산하여 반환한다.
"""

from __future__ import annotations

from typing import List

from layer2_rule_engine.stage_a_critical import CriticalFlagStage
from layer2_rule_engine.stage_b_complaint import ComplaintFocusedStage
from layer2_rule_engine.stage_c_fullscan import FullScanStage
from shared.schemas import Finding, ProcessedInput


class RuleEngine:
    """3-Stage Rule Engine 오케스트레이터."""

    def __init__(self) -> None:
        self.stage_a = CriticalFlagStage()
        self.stage_b = ComplaintFocusedStage()
        self.stage_c = FullScanStage()

    def execute(self, processed_input: ProcessedInput) -> List[Finding]:
        """Stage A → B → C 순차 실행 후 전체 Finding 리스트를 반환한다."""
        findings: List[Finding] = []

        # Stage A: Critical Flags (주호소 무관, 최우선)
        findings.extend(self.stage_a.run(processed_input))

        # Stage B: Complaint-Focused (Profile별 우선 검사)
        findings.extend(self.stage_b.run(processed_input))

        # Stage B에서 검사한 Feature 집합 → Stage C에서 제외
        checked_features = self.stage_b.get_checked_features(
            processed_input.complaint_profile,
        )

        # Stage C: Full Scan (나머지 항목)
        findings.extend(self.stage_c.run(processed_input, checked_features))

        return findings
