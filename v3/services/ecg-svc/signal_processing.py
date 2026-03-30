"""ECG 신호 처리 — HR, QTc 계산. Lambda signal_processing.py와 동일."""
import numpy as np
from scipy.signal import find_peaks


def compute_hr(signal_array: np.ndarray, fs: int = 500) -> int | None:
    """Lead II R-peak 기반 심박수 계산. 피크 부족 시 None 반환."""
    lead_ii = signal_array[1]  # index 1 = Lead II
    peaks, _ = find_peaks(lead_ii, distance=int(0.3 * fs), height=0.3)
    if len(peaks) < 2:
        return None
    rr_intervals = np.diff(peaks) / fs
    hr = round(float(60.0 / np.mean(rr_intervals)))
    return hr


def compute_qtc(hr: int | None) -> int | None:
    """Bazett 공식 QTc 보정. HR이 None이면 None 반환."""
    if hr is None or hr <= 0:
        return None
    qt_ms = 400  # 근사 baseline
    rr_sec = 60.0 / hr
    qtc = round(qt_ms / (rr_sec ** 0.5))
    return qtc
