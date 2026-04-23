"""
Lab 서비스 파이프라인

Layer 1 → Layer 2 → Layer 3 를 순서대로 실행하여
PredictRequest → PredictResponse 변환

ML 모델이 없으므로 즉시 ready 상태.
"""

import logging
import time
from datetime import datetime, timezone

from shared.schemas import PredictRequest, PredictResponse
from layer1_input_processor.processor import InputProcessor
from layer2_rule_engine.engine import RuleEngine
from layer3_report_generator.generator import ReportGenerator

logger = logging.getLogger(__name__)


class LabPipeline:
    def __init__(self):
        self.input_processor = InputProcessor()
        self.rule_engine = RuleEngine()
        self.report_generator = ReportGenerator()
        self._ready = True  # ML 모델 없으므로 즉시 ready

    @property
    def ready(self) -> bool:
        return self._ready

    def predict(self, req: PredictRequest) -> PredictResponse:
        """PredictRequest → PredictResponse 변환."""
        t0 = time.perf_counter()

        try:
            # Layer 1: 입력 처리
            processed = self.input_processor.process(req)

            # Layer 2: Rule Engine
            findings = self.rule_engine.execute(processed)

            # Layer 3: 리포트 생성
            response = self.report_generator.generate(findings, processed, req)

            # latency 측정
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
            response.metadata["latency_ms"] = elapsed_ms
            response.metadata["timestamp"] = datetime.now(timezone.utc).isoformat()

            logger.info(
                "patient_id=%s risk=%s findings=%d latency=%.1fms",
                req.patient_id, response.risk_level, len(response.findings), elapsed_ms,
            )

            return response

        except Exception as e:
            logger.exception("파이프라인 오류: %s", e)
            return PredictResponse(
                status="error",
                error=f"내부 오류: {type(e).__name__}",
            )
