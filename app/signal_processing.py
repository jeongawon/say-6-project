import numpy as np
import scipy.signal as sp_signal


def compute_hr(signal_array: np.ndarray, fs: int = 500) -> int | None:
    """
    Lead II(index 1)에서 R-peak 검출 → 심박수 계산

    Args:
        signal_array: (12, 5000) numpy array
        fs: 샘플링 레이트 (Hz)

    Returns:
        HR (bpm) 또는 None (검출 실패 시)
    """
    try:
        lead_ii = signal_array[1]
        peaks, _ = sp_signal.find_peaks(
            lead_ii,
            distance=int(0.3 * fs),  # 최소 간격 300ms
            height=0.3
        )
        if len(peaks) < 2:
            return None
        rr_intervals = np.diff(peaks) / fs  # 초 단위 RR 간격
        hr = round(float(60.0 / np.mean(rr_intervals)))
        return hr
    except Exception:
        return None


def compute_qtc(hr: int | None) -> int | None:
    """
    Bazett 공식으로 QTc 계산 (근사값)
    QTc = QT / sqrt(RR)
    정상 QT 평균 400ms 기준으로 HR 보정

    Args:
        hr: 심박수 (bpm)

    Returns:
        QTc (ms) 또는 None
    """
    try:
        if hr is None or hr <= 0:
            return None
        qt_ms = 400
        rr_sec = 60.0 / hr
        qtc = round(qt_ms / (rr_sec ** 0.5))
        return qtc
    except Exception:
        return None
