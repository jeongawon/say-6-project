"""
Layer 1: ECG 신호 전처리

입력: WFDB 레코드 경로 (확장자 없이)
  - 로컬: /path/to/files/p1000/p10000032/s40689238/40689238
  - S3:   s3://bucket/mimic/ecg/waveforms/p1000/p10000032/s40689238/40689238

전처리 순서:
  1. .hea + .dat 읽기 (wfdb) → (5000, 12)
  2. NaN 보간 + ±3mV 클리핑
  3. 리샘플링 500Hz → 100Hz → (1000, 12)
  4. 12채널 고정 순서 정렬
  5. PTB-XL Z-score 정규화 + ±5σ 클리핑
  6. (1, 12, 1000) 변환

출력:
  ecg_signal:   np.ndarray (1, 12, 1000) float32
  demographics: np.ndarray (1, 2)        float32
"""

import io
import logging
import tempfile
import os
import numpy as np
import boto3
from botocore.exceptions import ClientError
from pathlib import Path

import wfdb
import resampy
import pandas as pd

logger = logging.getLogger(__name__)

# 고정 채널 순서 (학습 시와 동일)
CHANNEL_ORDER = ['I', 'II', 'V1', 'V2', 'V3', 'V4', 'V5', 'V6', 'III', 'aVR', 'aVL', 'aVF']

# PTB-XL 채널별 정규화 통계
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
        record_path: str,   # WFDB 레코드 경로 (확장자 없이)
        age: float,
        sex: str,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Returns:
            ecg_signal:   (1, 12, 1000) float32
            demographics: (1, 2)        float32
        """
        sig, fs, sig_names = self._load_wfdb(record_path)   # (T, 12), Hz, [채널명...]
        sig = self._clean(sig)                               # NaN 보간 + ±3mV 클리핑
        sig = self._resample(sig, fs)                        # → (1000, 12)
        sig = self._align_channels(sig, sig_names)           # 채널 고정 순서
        sig = self._normalize(sig)                           # Z-score + ±5σ
        ecg = sig.T[np.newaxis].astype(np.float32)          # (1, 12, 1000)

        demo = self._encode_demographics(age, sex)           # (1, 2)
        return ecg, demo

    # ------------------------------------------------------------------
    # WFDB 로딩
    # ------------------------------------------------------------------
    def _load_wfdb(self, record_path: str) -> tuple[np.ndarray, int, list[str]]:
        """
        .hea + .dat 읽기
        Returns: (signal (T, n_leads), fs, sig_names)
        """
        if record_path.startswith("s3://"):
            return self._load_wfdb_s3(record_path)
        # 로컬
        sig, fields = wfdb.rdsamp(record_path)
        return sig.astype(np.float32), fields['fs'], fields['sig_name']

    def _load_wfdb_s3(self, s3_record: str) -> tuple[np.ndarray, int, list[str]]:
        """
        S3에서 .hea, .dat 임시 디렉토리에 다운로드 후 wfdb.rdsamp
        s3_record 예: s3://bucket/mimic/ecg/waveforms/p1000/.../40689238
        """
        parts  = s3_record.removeprefix("s3://").split("/", 1)
        bucket = parts[0]
        prefix = parts[1]   # mimic/ecg/waveforms/p1000/.../40689238

        with tempfile.TemporaryDirectory() as tmpdir:
            for ext in [".hea", ".dat"]:
                key       = prefix + ext
                local_path = os.path.join(tmpdir, os.path.basename(prefix) + ext)
                try:
                    self.s3.download_file(bucket, key, local_path)
                except ClientError as e:
                    raise RuntimeError(f"S3 다운로드 실패: s3://{bucket}/{key} — {e}") from e

            record_name = os.path.join(tmpdir, os.path.basename(prefix))
            sig, fields = wfdb.rdsamp(record_name)

        return sig.astype(np.float32), fields['fs'], fields['sig_name']

    # ------------------------------------------------------------------
    # 전처리 단계
    # ------------------------------------------------------------------
    def _clean(self, sig: np.ndarray) -> np.ndarray:
        """NaN 선형 보간 + ±3mV 클리핑 (채널별)"""
        out = sig.copy()
        for i in range(out.shape[1]):
            s = pd.Series(out[:, i])
            if s.isna().any():
                s = s.interpolate(method="linear", limit_direction="both")
            out[:, i] = np.clip(s.values, -3.0, 3.0)
        return out

    def _resample(self, sig: np.ndarray, fs: int) -> np.ndarray:
        """500Hz → 100Hz (1000샘플), 이미 100Hz면 그대로"""
        if fs == 100:
            return sig[:1000] if sig.shape[0] >= 1000 else sig
        return resampy.resample(sig, fs, 100, axis=0).astype(np.float32)

    def _align_channels(self, sig: np.ndarray, sig_names: list[str]) -> np.ndarray:
        """채널명 기반 CHANNEL_ORDER 순서로 재정렬"""
        # sig_names 정규화 (공백/대소문자)
        name_map = {n.strip().upper(): i for i, n in enumerate(sig_names)}
        aligned  = np.zeros((sig.shape[0], len(CHANNEL_ORDER)), dtype=np.float32)
        for out_idx, ch in enumerate(CHANNEL_ORDER):
            src_idx = name_map.get(ch.upper())
            if src_idx is not None:
                aligned[:, out_idx] = sig[:, src_idx]
            else:
                logger.warning("채널 '%s' 없음 — 0으로 채움", ch)
        return aligned

    def _normalize(self, sig: np.ndarray) -> np.ndarray:
        """PTB-XL 채널별 Z-score 정규화 + ±5σ 클리핑"""
        sig = (sig - PTB_XL_MEAN) / PTB_XL_STD
        return np.clip(sig, -5.0, 5.0).astype(np.float32)

    # ------------------------------------------------------------------
    # 인구통계 인코딩
    # ------------------------------------------------------------------
    @staticmethod
    def _encode_demographics(age: float, sex: str) -> np.ndarray:
        age_norm   = float(np.clip((age - 18.0) / (101.0 - 18.0), 0.0, 1.0))
        gender_enc = {"m": 1.0, "male": 1.0, "f": 0.0, "female": 0.0}.get(
            sex.lower().strip(), 0.5
        )
        return np.array([[age_norm, gender_enc]], dtype=np.float32)
