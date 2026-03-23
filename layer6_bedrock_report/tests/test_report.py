"""
Layer 6 Bedrock Report - 테스트
Bedrock 호출 없이 프롬프트 조립/파싱 로직만 단위 테스트.
Bedrock 실제 호출 테스트는 Lambda 배포 후 수행.
"""
import json
import pytest
from layer6_bedrock_report.report_generator import BedrockReportGenerator
from layer6_bedrock_report.config import Config
from layer6_bedrock_report.mock_data import (
    SCENARIO_CHF, SCENARIO_PNEUMONIA, SCENARIO_TENSION_PNEUMO, SCENARIO_NORMAL,
    SCENARIOS,
)


@pytest.fixture
def generator():
    return BedrockReportGenerator(Config())


# ============================================================
# 프롬프트 조립 테스트
# ============================================================
class TestPromptBuilding:
    def test_system_prompt_ko(self, generator):
        prompt = generator._build_system_prompt(SCENARIO_CHF, "ko")
        assert "응급의학과 전문의" in prompt
        assert "RAG" in prompt

    def test_system_prompt_en(self, generator):
        prompt = generator._build_system_prompt(SCENARIO_CHF, "en")
        assert "emergency medicine specialist" in prompt

    def test_system_prompt_with_rag(self, generator):
        event = dict(SCENARIO_CHF)
        event["rag_evidence"] = [
            {"similarity": 0.91, "impression": "Cardiomegaly with bilateral effusion"}
        ]
        prompt = generator._build_system_prompt(event, "ko")
        assert "유사 케이스" in prompt
        assert "0.91" in prompt

    def test_user_prompt_chf(self, generator):
        prompt = generator._build_user_prompt(SCENARIO_CHF, "ko")
        assert "72세" in prompt or "72" in prompt
        assert "심방세동" in prompt
        assert "CTR" in prompt
        assert "0.62" in prompt
        assert "URGENT" in prompt

    def test_user_prompt_normal(self, generator):
        prompt = generator._build_user_prompt(SCENARIO_NORMAL, "ko")
        assert "건강검진" in prompt
        assert "ROUTINE" in prompt

    def test_user_prompt_tension(self, generator):
        prompt = generator._build_user_prompt(SCENARIO_TENSION_PNEUMO, "ko")
        assert "CRITICAL" in prompt
        assert "기관" in prompt
        assert "0.421" in prompt


# ============================================================
# 섹션 포맷팅 테스트
# ============================================================
class TestFormatting:
    def test_format_patient_info(self, generator):
        info = {"age": 72, "sex": "M", "chief_complaint": "호흡곤란", "spo2": 91}
        result = generator._format_patient_info(info)
        assert "72세" in result
        assert "남성" in result
        assert "호흡곤란" in result
        assert "91%" in result

    def test_format_patient_info_empty(self, generator):
        result = generator._format_patient_info({})
        assert "정보 없음" in result

    def test_format_prior_results(self, generator):
        results = [{"modal": "ecg", "summary": "심방세동"}]
        formatted = generator._format_prior_results(results)
        assert "ECG" in formatted
        assert "심방세동" in formatted

    def test_format_prior_results_empty(self, generator):
        result = generator._format_prior_results([])
        assert "이전 검사 없음" in result

    def test_format_anatomy(self, generator):
        result = generator._format_anatomy(SCENARIO_CHF["anatomy_measurements"])
        assert "0.6200" in result
        assert "severe" in result
        assert "blunted" in result

    def test_format_detection(self, generator):
        result = generator._format_detection(
            SCENARIO_CHF["densenet_predictions"],
            SCENARIO_CHF["yolo_detections"]
        )
        assert "Cardiomegaly" in result
        assert "0.92" in result

    def test_format_detection_with_yolo(self, generator):
        result = generator._format_detection(
            SCENARIO_PNEUMONIA["densenet_predictions"],
            SCENARIO_PNEUMONIA["yolo_detections"]
        )
        assert "YOLO" in result
        assert "LLL" in result

    def test_format_clinical_logic(self, generator):
        result = generator._format_clinical_logic(SCENARIO_CHF["clinical_logic"])
        assert "Cardiomegaly" in result
        assert "양성" in result
        assert "3" in result  # detected_count

    def test_format_differential(self, generator):
        diff = SCENARIO_CHF["clinical_logic"]["differential_diagnosis"]
        result = generator._format_differential(diff)
        assert "심부전" in result or "CHF" in result

    def test_format_cross_validation(self, generator):
        result = generator._format_cross_validation(SCENARIO_CHF["cross_validation_summary"])
        assert "Cardiomegaly" in result


# ============================================================
# 응답 파싱 테스트
# ============================================================
class TestResponseParsing:
    def test_parse_json_block(self, generator):
        response = {
            "content": [{"text": '```json\n{"structured": {"heart": "test"}, "narrative": "n", "summary": "s", "suggested_next_actions": []}\n```'}],
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }
        result = generator._parse_response(response)
        assert result["structured"]["heart"] == "test"

    def test_parse_raw_json(self, generator):
        response = {
            "content": [{"text": '{"structured": {"heart": "raw"}, "narrative": "n", "summary": "s", "suggested_next_actions": []}'}],
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }
        result = generator._parse_response(response)
        assert result["structured"]["heart"] == "raw"

    def test_parse_json_with_text(self, generator):
        response = {
            "content": [{"text": 'Here is the report:\n{"structured": {"heart": "mixed"}, "narrative": "n", "summary": "s", "suggested_next_actions": []}\nDone.'}],
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }
        result = generator._parse_response(response)
        assert result["structured"]["heart"] == "mixed"

    def test_parse_no_json_raises(self, generator):
        response = {
            "content": [{"text": "No JSON here at all"}],
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }
        with pytest.raises((ValueError, json.JSONDecodeError)):
            generator._parse_response(response)


# ============================================================
# Mock 데이터 검증
# ============================================================
class TestMockData:
    def test_all_scenarios_exist(self):
        assert "chf" in SCENARIOS
        assert "pneumonia" in SCENARIOS
        assert "tension_pneumo" in SCENARIOS
        assert "normal" in SCENARIOS

    def test_scenario_structure(self):
        for key, scenario in SCENARIOS.items():
            assert "name" in scenario
            assert "description" in scenario
            assert "input" in scenario
            data = scenario["input"]
            assert "clinical_logic" in data
            assert "anatomy_measurements" in data
            assert "densenet_predictions" in data

    def test_chf_has_urgent_risk(self):
        assert SCENARIO_CHF["clinical_logic"]["risk_level"] == "URGENT"

    def test_tension_has_critical_risk(self):
        assert SCENARIO_TENSION_PNEUMO["clinical_logic"]["risk_level"] == "CRITICAL"

    def test_normal_has_routine_risk(self):
        assert SCENARIO_NORMAL["clinical_logic"]["risk_level"] == "ROUTINE"

    def test_chf_detected_count(self):
        assert SCENARIO_CHF["clinical_logic"]["detected_count"] == 3

    def test_normal_detected_count(self):
        assert SCENARIO_NORMAL["clinical_logic"]["detected_count"] == 0
