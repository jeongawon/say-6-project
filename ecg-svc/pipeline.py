"""
ECG 서비스 파이프라인

Layer 1 → Layer 2 → Layer 3 를 순서대로 실행하여
PredictRequest → PredictResponse 변환

싱글톤 패턴: app 시작 시 load()로 초기화 후 predict()로 반복 사용
"""

import logging
import time
from datetime import datetime, timezone

from shared.schemas import PredictRequest, PredictResponse
from layer1_preprocessing import ECGPreprocessor
from layer2_inference import ECGInferenceEngine
from layer3_clinical_logic import ClinicalEngine

logger = logging.getLogger(__name__)


class ECGPipeline:
    def __init__(self):
        self.preprocessor = ECGPreprocessor()
        self.inference    = ECGInferenceEngine()
        self.clinical     = ClinicalEngine()
        self._ready       = False

    # ------------------------------------------------------------------
    # 초기화 (앱 시작 시 1회)
    # ------------------------------------------------------------------
    def load(self) -> None:
        logger.info("ECG 파이프라인 초기화 시작")
        self.inference.load()
        self._ready = True
        logger.info("ECG 파이프라인 준비 완료")

    @property
    def ready(self) -> bool:
        return self._ready

    # ------------------------------------------------------------------
    # 메인 실행
    # ------------------------------------------------------------------
    def predict(self, req: PredictRequest) -> PredictResponse:
        if not self._ready:
            return PredictResponse(
                status="error",
                error="모델이 아직 로드되지 않았습니다. 잠시 후 다시 시도하세요.",
            )

        t0 = time.perf_counter()

        try:
            # ----------------------------------------------------------
            # Layer 1: 전처리
            # ----------------------------------------------------------
            age = req.patient_info.age  if req.patient_info else 60.0
            sex = req.patient_info.sex  if req.patient_info else "unknown"

            ecg_signal, demographics, vitals = self.preprocessor.run(
                record_path=req.data.record_path,
                age=age,
                sex=sex,
            )

            # ----------------------------------------------------------
            # Layer 2: 추론
            # ----------------------------------------------------------
            probs: dict[str, float] = self.inference.predict(ecg_signal, demographics)

            # ----------------------------------------------------------
            # Layer 3: 임상 해석
            # ----------------------------------------------------------
            result = self.clinical.run(probs, vitals)

            elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
            logger.info(
                "patient_id=%s risk=%s latency=%.1fms",
                req.patient_id, result.risk_level, elapsed_ms,
            )

            return PredictResponse(
                status="ok",
                findings=result.findings,
                summary=result.summary,
                risk_level=result.risk_level,
                ecg_vitals=result.ecg_vitals,
                metadata={
                    "patient_id":   req.patient_id,
                    "latency_ms":   elapsed_ms,
                    "model":        "ecg_s6.onnx",
                    "timestamp":    datetime.now(timezone.utc).isoformat(),
                    "num_detected": len(result.findings),
                },
            )

        except FileNotFoundError as e:
            logger.error("신호 파일 없음: %s", e)
            return PredictResponse(status="error", error=f"신호 파일을 찾을 수 없습니다: {e}")
        except RuntimeError as e:
            logger.error("런타임 오류: %s", e)
            return PredictResponse(status="error", error=str(e))
        except Exception as e:
            logger.exception("예상치 못한 오류: %s", e)
            return PredictResponse(status="error", error=f"내부 오류: {type(e).__name__}")
