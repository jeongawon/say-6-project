"""
Layer 5 RAG 테스트 — 4개 시나리오로 검색 품질 검증.
Mock 모드에서 키워드 매칭 기반 결과 확인.
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from layer5_rag.query_builder import build_query
from layer5_rag.mock_data import MOCK_L3_SCENARIOS, MOCK_REPORTS


class TestQueryBuilder:
    """쿼리 생성 테스트"""

    def test_chf_query_english(self):
        query = build_query(MOCK_L3_SCENARIOS["chf"])
        assert "cardiomegaly" in query.lower()
        assert "edema" in query.lower()
        assert "CHF" in query

    def test_pneumonia_query(self):
        query = build_query(MOCK_L3_SCENARIOS["pneumonia"])
        assert "consolidation" in query.lower()
        assert "pneumonia" in query.lower()
        assert "Pneumonia" in query

    def test_tension_pneumo_query(self):
        query = build_query(MOCK_L3_SCENARIOS["tension_pneumo"])
        assert "pneumothorax" in query.lower()
        assert "fracture" in query.lower()

    def test_normal_query(self):
        query = build_query(MOCK_L3_SCENARIOS["normal"])
        assert "normal" in query.lower()
        assert "no acute" in query.lower()

    def test_no_finding_excluded(self):
        """No_Finding은 쿼리에 포함되지 않아야 함"""
        query = build_query(MOCK_L3_SCENARIOS["normal"])
        assert "no_finding" not in query.lower()
        assert "no finding" not in query.lower()


class TestMockSearch:
    """Mock 검색 테스트 (Lambda 핸들러의 mock_search 로직 재현)"""

    def _mock_search(self, clinical_logic, top_k=3):
        """mock_search 로직 재현"""
        query = build_query(clinical_logic)
        findings = clinical_logic.get("findings", {})
        scored = []

        for report in MOCK_REPORTS:
            score = 0.0
            imp_lower = report["impression"].lower()
            for disease, result in findings.items():
                if not result.get("detected") or disease == "No_Finding":
                    continue
                name = disease.replace("_", " ").lower()
                if name in imp_lower:
                    score += 0.3
                if result.get("severity") and result["severity"] in imp_lower:
                    score += 0.1
                if result.get("location") and result["location"].split()[0].lower() in imp_lower:
                    score += 0.1
            if findings.get("No_Finding", {}).get("detected"):
                if "normal" in imp_lower or "no acute" in imp_lower:
                    score += 0.5
            scored.append((score, report))

        scored.sort(key=lambda x: -x[0])
        return [r for _, r in scored[:top_k]]

    def test_chf_returns_chf_reports(self):
        results = self._mock_search(MOCK_L3_SCENARIOS["chf"])
        # Top 결과에 CHF 관련 판독문이 포함되어야 함
        impressions = " ".join(r["impression"].lower() for r in results)
        assert "cardiomegaly" in impressions
        assert "chf" in impressions or "heart failure" in impressions

    def test_pneumonia_returns_pneumonia_reports(self):
        results = self._mock_search(MOCK_L3_SCENARIOS["pneumonia"])
        impressions = " ".join(r["impression"].lower() for r in results)
        assert "pneumonia" in impressions or "consolidation" in impressions

    def test_tension_returns_pneumothorax_reports(self):
        results = self._mock_search(MOCK_L3_SCENARIOS["tension_pneumo"])
        impressions = " ".join(r["impression"].lower() for r in results)
        assert "pneumothorax" in impressions

    def test_normal_returns_normal_reports(self):
        results = self._mock_search(MOCK_L3_SCENARIOS["normal"])
        impressions = " ".join(r["impression"].lower() for r in results)
        assert "normal" in impressions or "no acute" in impressions

    def test_top_k_respected(self):
        for k in [1, 3, 5]:
            results = self._mock_search(MOCK_L3_SCENARIOS["chf"], top_k=k)
            assert len(results) == min(k, len(MOCK_REPORTS))

    def test_results_have_all_fields(self):
        results = self._mock_search(MOCK_L3_SCENARIOS["chf"])
        for r in results:
            assert "note_id" in r
            assert "impression" in r
            assert "findings" in r
            assert "indication" in r


class TestMockReports:
    """Mock 데이터 품질 검증"""

    def test_all_reports_have_impression(self):
        for r in MOCK_REPORTS:
            assert r["impression"], f"note_id {r['note_id']} missing impression"

    def test_all_reports_have_findings(self):
        for r in MOCK_REPORTS:
            assert r["findings"], f"note_id {r['note_id']} missing findings"

    def test_report_count(self):
        assert len(MOCK_REPORTS) == 10

    def test_scenarios_count(self):
        assert len(MOCK_L3_SCENARIOS) == 4

    def test_scenario_keys(self):
        expected = {"chf", "pneumonia", "tension_pneumo", "normal"}
        assert set(MOCK_L3_SCENARIOS.keys()) == expected


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
