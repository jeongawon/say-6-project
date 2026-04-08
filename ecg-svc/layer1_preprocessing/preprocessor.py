"""
Layer 1: ECG 신호 전처리

입력: S3 URI 또는 로컬 .npy 경로 (1000, 12) 또는 (5000, 12)
출력:
  - ecg_signal:   np.ndarray (1, 12, 1000) float32  — 모델 입력
  - demographics: np.ndarray (1, 2)        float32  — [age_norm, gender_enc]

전처리 순서:
  1. 파일 로딩 (S3 또는 로컬)
  2. NaN 보간 + ±3mV 클리핑
  3. 리샘플링 (500Hz → 100Hz, 이미 1000샘플이면 스킵)
  4. PTB-XL Z-score 정규화
  5. 클리핑 ±5σ
  6. (12, 1000) 변환 + 배치 차원 추가
"""

import io
import logging
import numpy as np
import boto3
from botocore.exceptions import ClientError
from pathlib import Path

from config import S3_BUCKET

logger = logging.getLogger(__name__)

# PTB-XL 채널별 정규화 통계 (학습 시 사용한 값과 동일)
PTB_XL_MEAN = np.array([
    -0.00184586, -0.00130277,  0.00017031, -0.00091313,
    -0.00148835, -0.00174687, -0.00077071, -0.00207407,
     0.00054329,  0.00155546, -0.00114379, -0.00035649
], dtype=np.float32)

PTB_XL_STD = np.array([
    0.16401004, 0.1647168,  0.23374124, 0.33767231,
    0.33362807, 0.30583013, 0.2731171,  0.27554379,
    0.17128962, 0.14030828, 0.14606956, 0.14656108
], dtype=np.float32)


class ECGPreprocessor:
    def __init__(self):
        self._s3 = None

    @property
    def s3(self):
        if self._s3 is None:
            self._s3 = boto3.client("s3")
        return self._s3

    # ------------------------------------------------------------------
    # 공개 인터페이스
    # ------------------------------------------------------------------
    def run(
        self,
        signal_path: str,
        age: float,
        sex: str,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Returns:
            ecg_signal:   (1, 12, 1000) float32
            demographics: (1, 2)        float32
        """
        raw = self._load(signal_path)                  # (T, 12)
        sig = self._clean(raw)                         # (T, 12) NaN 보간 + 클리핑
        sig = self._resample_if_needed(sig)            # (1000, 12)
        sig = self._normalize(sig)                     # Z-score + ±5σ 클리핑
        ecg = sig.T[np.newaxis].astype(np.float32)    # (1, 12, 1000)

        demo = self._encode_demographics(age, sex)     # (1, 2)
        return ecg, demo

    # ------------------------------------------------------------------
    # 내부 메서드
    # ------------------------------------------------------------------
    def _load(self, path: str) -> np.ndarray:
        """S3 URI (s3://bucket/key) 또는 로컬 경로 .npy 로드"""
        if path.startswith("s3://"):
            return self._load_s3(path)
        return np.load(path).astype(np.float32)

    def _load_s3(self, uri: str) -> np.ndarray:
        # s3://bucket/key/to/file.npy
        parts = uri.removeprefix("s3://").split("/", 1)
        bucket, key = parts[0], parts[1]
        buf = io.BytesIO()
        try:
            self.s3.download_fileobj(bucket, key, buf)
        except ClientError as e:
            raise RuntimeError(f"S3 다운로드 실패: {uri} — {e}") from e
        buf.seek(0)
        return np.load(buf).astype(np.float32)

    def _clean(self, sig: np.ndarray) -> np.ndarray:
        """NaN 선형 보간 + ±3mV 클리핑 (채널별)"""
        import pandas as pd
        out = sig.copy()
        for i in range(out.shape[1]):
            s = pd.Series(out[:, i])
            if s.isna().any():
                s = s.interpolate(method="linear", limit_direction="both")
            out[:, i] = np.clip(s.values, -3.0, 3.0)
        return out

    def _resample_if_needed(self, sig: np.ndarray) -> np.ndarray:
        """(5000, 12) → (1000, 12), 이미 1000이면 그대로"""
        T = sig.shape[0]
        if T == 1000:
            return sig
        if T == 5000:
            try:
                import resampy
                return resampy.resample(sig, 500, 100, axis=0).astype(np.float32)
            except ImportError:
                # resampy 없으면 단순 슬라이싱 (5→1 다운샘플)
                logger.warning("resampy 미설치 — 단순 다운샘플 사용")
                return sig[::5].astype(np.float32)
        # 그 외: 그대로 반환 (길이 불일치는 모델에서 처리)
        logger.warning("예상치 못한 ECG 길이: %d (1000 또는 5000 필요)", T)
        return sig

    def _normalize(self, sig: np.ndarray) -> np.ndarray:
        """PTB-XL 채널별 Z-score 정규화 + ±5σ 클리핑"""
        sig = (sig - PTB_XL_MEAN) / PTB_XL_STD
        return np.clip(sig, -5.0, 5.0).astype(np.float32)

    @staticmethod
    def _encode_demographics(age: float, sex: str) -> np.ndarray:
        """
        나이: (age - 18) / (101 - 18) → 0~1
        성별: M=1.0, F=0.0, 기타=0.5
        """
        age_norm   = float(np.clip((age - 18.0) / (101.0 - 18.0), 0.0, 1.0))
        gender_enc = {"m": 1.0, "male": 1.0, "f": 0.0, "female": 0.0}.get(
            sex.lower().strip(), 0.5
        )
        return np.array([[age_norm, gender_enc]], dtype=np.float32)  # (1, 2)
