"""
Layer 2: ONNX Runtime 기반 ECG 추론 엔진

모델: ecg_s6.onnx (S6 Mamba 백본 + 인구통계 결합)
입력:
  - ecg_signal:   (1, 12, 1000) float32
  - demographics: (1, 2)        float32
출력:
  - logits:       (1, 24)       float32  — sigmoid 전 raw 값
  → sigmoid 적용 후 질환별 확률 반환

S3에서 모델 파일 자동 다운로드 (캐시 후 재사용)
"""

import logging
import numpy as np
import boto3
from botocore.exceptions import ClientError
from pathlib import Path

import onnxruntime as ort

from config import S3_BUCKET, S3_MODEL_KEY, S3_DATA_KEY, MODEL_DIR, MODEL_PATH
from shared.labels import LABEL_NAMES

logger = logging.getLogger(__name__)


class ECGInferenceEngine:
    def __init__(self):
        self._session: ort.InferenceSession | None = None

    # ------------------------------------------------------------------
    # 초기화 — 앱 시작 시 1회 호출
    # ------------------------------------------------------------------
    def load(self) -> None:
        """모델 로드 (S3 다운로드 → ONNX 세션 생성)"""
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        self._ensure_model_cached()
        self._session = self._create_session()
        logger.info("ONNX 세션 준비 완료: %s", MODEL_PATH)

    # ------------------------------------------------------------------
    # 추론
    # ------------------------------------------------------------------
    def predict(
        self,
        ecg_signal: np.ndarray,    # (1, 12, 1000) float32
        demographics: np.ndarray,  # (1, 2)        float32
    ) -> dict[str, float]:
        """
        Returns:
            { label_name: probability, ... }  — 24개 질환 확률 0~1
        """
        if self._session is None:
            raise RuntimeError("모델이 로드되지 않았습니다. load()를 먼저 호출하세요.")

        logits: np.ndarray = self._session.run(
            ["logits"],
            {
                "ecg_signal":   ecg_signal,
                "demographics": demographics,
            },
        )[0]  # (1, 24)

        probs = self._sigmoid(logits[0])  # (24,)
        return {label: float(prob) for label, prob in zip(LABEL_NAMES, probs)}

    # ------------------------------------------------------------------
    # 내부 메서드
    # ------------------------------------------------------------------
    def _ensure_model_cached(self) -> None:
        """MODEL_PATH 없으면 S3에서 다운로드"""
        if MODEL_PATH.exists():
            logger.info("캐시된 모델 사용: %s", MODEL_PATH)
            return

        logger.info("S3에서 모델 다운로드: s3://%s/%s", S3_BUCKET, S3_MODEL_KEY)
        s3 = boto3.client("s3")
        try:
            s3.download_file(S3_BUCKET, S3_MODEL_KEY, str(MODEL_PATH))
        except ClientError as e:
            raise RuntimeError(
                f"모델 다운로드 실패: s3://{S3_BUCKET}/{S3_MODEL_KEY} — {e}"
            ) from e

        # ONNX external data 파일 (.onnx.data) — 있는 경우 함께 다운로드
        data_path = MODEL_PATH.parent / (MODEL_PATH.name + ".data")
        if not data_path.exists():
            try:
                s3.download_file(S3_BUCKET, S3_DATA_KEY, str(data_path))
                logger.info("ONNX external data 다운로드 완료: %s", data_path)
            except ClientError:
                logger.debug("external data 파일 없음 (단일 파일 모델)")

    def _create_session(self) -> ort.InferenceSession:
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.intra_op_num_threads = 4
        try:
            sess = ort.InferenceSession(str(MODEL_PATH), opts, providers=providers)
        except Exception:
            # CUDA 없으면 CPU만으로 재시도
            sess = ort.InferenceSession(
                str(MODEL_PATH), opts, providers=["CPUExecutionProvider"]
            )
        return sess

    @staticmethod
    def _sigmoid(x: np.ndarray) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-x.astype(np.float64)))
