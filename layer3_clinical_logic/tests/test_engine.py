"""
Layer 3 Clinical Logic Engine 유닛 테스트
4개 시나리오에 대해 핵심 판정 결과 검증
"""

import sys
import os

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from layer3_clinical_logic.engine import run_clinical_logic
from layer3_clinical_logic.mock_data import (
    mock_chf_patient,
    mock_pneumonia_patient,
    mock_tension_pneumo,
    mock_normal,
)


class TestCHFPatient:
    """시나리오 1: 심부전 환자"""

    def setup_method(self):
        self.result = run_clinical_logic(mock_chf_patient)

    def test_cardiomegaly_detected(self):
        r = self.result["findings"]["Cardiomegaly"]
        assert r["detected"] is True
        assert r["severity"] == "severe"
        assert r["quantitative"]["ctr"] == 0.62

    def test_pleural_effusion_bilateral(self):
        r = self.result["findings"]["Pleural_Effusion"]
        assert r["detected"] is True
        assert r["location"] == "bilateral"

    def test_edema_detected(self):
        r = self.result["findings"]["Edema"]
        assert r["detected"] is True

    def test_no_finding_false(self):
        """질환이 있으므로 No Finding은 False"""
        r = self.result["findings"]["No_Finding"]
        assert r["detected"] is False

    def test_detected_count_ge_3(self):
        """최소 3개 질환 (심비대 + 흉수 + 부종) 탐지"""
        assert self.result["detected_count"] >= 3

    def test_differential_chf(self):
        """감별 진단에 CHF 포함"""
        diagnoses = [d["diagnosis"] for d in self.result["differential_diagnosis"]]
        assert any("CHF" in diag or "심부전" in diag for diag in diagnoses)

    def test_risk_urgent(self):
        """CHF: Cardiomegaly severe + Edema severe → urgent"""
        assert self.result["risk_level"] == "urgent"


class TestPneumoniaPatient:
    """시나리오 2: 폐렴 환자"""

    def setup_method(self):
        self.result = run_clinical_logic(mock_pneumonia_patient)

    def test_consolidation_detected(self):
        r = self.result["findings"]["Consolidation"]
        assert r["detected"] is True

    def test_pneumonia_detected(self):
        r = self.result["findings"]["Pneumonia"]
        assert r["detected"] is True
        assert r["confidence"] in ("high", "medium")

    def test_pneumonia_has_fever_evidence(self):
        r = self.result["findings"]["Pneumonia"]
        evidence_text = " ".join(r["evidence"])
        assert "발열" in evidence_text or "체온" in evidence_text

    def test_lung_opacity_cause_consolidation(self):
        r = self.result["findings"]["Lung_Opacity"]
        if r["detected"]:
            assert r["quantitative"]["primary_cause"] == "Consolidation"

    def test_cardiomegaly_not_detected(self):
        r = self.result["findings"]["Cardiomegaly"]
        assert r["detected"] is False

    def test_cross_validation_consolidation(self):
        cv = self.result["cross_validation"]["Consolidation"]
        assert cv["sources"]["densenet"] is True
        assert cv["sources"]["yolo"] is True


class TestTensionPneumothorax:
    """시나리오 3: 긴장성 기흉 (응급!)"""

    def setup_method(self):
        self.result = run_clinical_logic(mock_tension_pneumo)

    def test_pneumothorax_detected(self):
        r = self.result["findings"]["Pneumothorax"]
        assert r["detected"] is True

    def test_tension_detected(self):
        r = self.result["findings"]["Pneumothorax"]
        assert r["quantitative"]["tension"] is True

    def test_alert_flag(self):
        r = self.result["findings"]["Pneumothorax"]
        assert r["alert"] is True

    def test_severity_critical(self):
        r = self.result["findings"]["Pneumothorax"]
        assert r["severity"] == "critical"

    def test_risk_level_critical(self):
        assert self.result["risk_level"] == "critical"

    def test_alert_flags_list(self):
        assert "Pneumothorax" in self.result["alert_flags"]

    def test_atelectasis_area_decrease(self):
        """좌측 폐 면적 대폭 감소 (ratio 0.421)"""
        r = self.result["findings"]["Atelectasis"]
        # 면적 감소가 있지만, 종격동이 반대쪽(right)으로 밀림 → 기흉이지 무기폐가 아님
        # DenseNet도 낮으므로 detected=False가 적절
        # (종격동 반대쪽 이동 = 흉수/기흉에 의한 것)


class TestNormalPatient:
    """시나리오 4: 정상"""

    def setup_method(self):
        self.result = run_clinical_logic(mock_normal)

    def test_no_finding_detected(self):
        r = self.result["findings"]["No_Finding"]
        assert r["detected"] is True

    def test_all_checklist_passed(self):
        r = self.result["findings"]["No_Finding"]
        assert r["quantitative"]["failed"] == 0

    def test_detected_count_zero(self):
        assert self.result["detected_count"] == 0

    def test_risk_routine(self):
        assert self.result["risk_level"] == "routine"

    def test_no_alert_flags(self):
        assert len(self.result["alert_flags"]) == 0

    def test_cardiomegaly_not_detected(self):
        assert self.result["findings"]["Cardiomegaly"]["detected"] is False

    def test_pneumothorax_not_detected(self):
        assert self.result["findings"]["Pneumothorax"]["detected"] is False


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
