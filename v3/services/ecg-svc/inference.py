"""ONNX 13-class ECG 추론 엔진 — Lambda inference.py와 동일 로직."""
import time
import logging
import numpy as np
import boto3
from io import BytesIO

from model_loader import get_session
from signal_processing import compute_hr, compute_qtc
from thresholds import (
    LABEL_NAMES, LABEL_THRESHOLDS, EMERGENCY_LABELS,
    DETECTION_MARGIN, CRITICAL_LABELS, URGENT_LABELS,
    LABEL_KO, LABEL_SEVERITY, LABEL_RECOMMENDATION,
    NEXT_MODAL_MAP, ECG_CONFIRMED_LABELS,
)

# shared schemas
import sys
if "/app/shared" not in sys.path:
    sys.path.insert(0, "/app/shared")
from schemas import Finding

logger = logging.getLogger("ecg-svc")


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-x))


def _normalize(signal_array: np.ndarray) -> np.ndarray:
    """리드별 z-score 정규화 (Lambda 동일)"""
    mean = signal_array.mean(axis=1, keepdims=True)
    std = signal_array.std(axis=1, keepdims=True)
    std[std == 0] = 1.0
    return ((signal_array - mean) / std).astype(np.float32)


def load_signal(signal_path: str) -> np.ndarray:
    """S3 또는 로컬에서 .npy 신호 로드 → (12, 5000) 반환."""
    if signal_path.startswith("s3://"):
        parts = signal_path.replace("s3://", "").split("/", 1)
        bucket, key = parts[0], parts[1]
        s3 = boto3.client("s3")
        buf = BytesIO()
        s3.download_fileobj(bucket, key, buf)
        buf.seek(0)
        signal = np.load(buf)
    else:
        signal = np.load(signal_path)

    # shape 정규화
    if signal.shape == (5000, 12):
        signal = signal.T
    signal = np.nan_to_num(signal, nan=0.0)
    return signal.astype(np.float32)


def run_inference(
    signal: np.ndarray,
    patient_info=None,
    context: dict | None = None,
) -> dict:
    """
    ONNX 추론 실행 → Lambda와 동일 구조의 결과 dict 반환.

    Returns:
        dict with keys: findings, risk_level, summary, report,
                        pertinent_negatives, suggested_next_actions, metadata
    """
    _start = time.time()
    session = get_session()

    # 정규화 + 추론 (Lambda 동일)
    normalized = _normalize(signal)
    input_data = normalized[np.newaxis, ...]  # (1, 12, 5000)
    logits = session.run(None, {"ecg_signal": input_data})[0][0]
    probs = _sigmoid(logits)

    # findings 생성 (Lambda 동일 로직)
    findings: list[Finding] = []
    detected_names: list[str] = []
    for name, prob in zip(LABEL_NAMES, probs):
        threshold = LABEL_THRESHOLDS[name]
        over_threshold = bool(prob > threshold)
        # 응급 레이블은 margin 필터 미적용, 나머지는 margin 미달 시 음성 처리
        if over_threshold and name not in EMERGENCY_LABELS:
            detected = (prob - threshold) >= DETECTION_MARGIN
        else:
            detected = over_threshold

        findings.append(Finding(
            name=LABEL_KO[name],                                    # 한글만 (Lambda 동일)
            detected=detected,
            confidence=round(float(prob), 4),                       # 4자리 (Lambda 동일)
            detail=f"임계값 {threshold} 기준 {'감지됨' if detected else '음성'}",
            severity=LABEL_SEVERITY[name] if detected else None,    # Lambda LABEL_SEVERITY
            recommendation=LABEL_RECOMMENDATION[name] if detected else None,
        ))
        if detected:
            detected_names.append(LABEL_KO[name])

    # risk_level (Lambda 동일 — label set intersection)
    detected_keys = {name for name, prob in zip(LABEL_NAMES, probs)
                     if findings[LABEL_NAMES.index(name)].detected}
    if detected_keys & CRITICAL_LABELS:
        risk_level = "critical"
    elif detected_keys & URGENT_LABELS:
        risk_level = "urgent"
    else:
        risk_level = "routine"

    # summary & report (Lambda 동일 — ECG 확인 소견 vs 추가 검사 분류)
    prev = (context or {}).get("previous_findings", "")
    context_note = f" {prev} 맥락과 함께 해석 필요." if prev else ""

    ecg_confirmed = []
    needs_confirm = []
    for name, prob in zip(LABEL_NAMES, probs):
        if not findings[LABEL_NAMES.index(name)].detected:
            continue
        ko = LABEL_KO[name]
        rec = LABEL_RECOMMENDATION[name]
        prob_pct = round(float(prob) * 100, 1)
        if name in ECG_CONFIRMED_LABELS:
            ecg_confirmed.append((ko, prob_pct, rec))
        else:
            needs_confirm.append((ko, prob_pct, rec))

    if not detected_names:
        summary = f"ECG상 이상 소견 없음.{context_note}"
    else:
        parts = []
        if ecg_confirmed:
            confirmed_str = "; ".join(
                f"{ko}({p}%) → {rec}" for ko, p, rec in ecg_confirmed
            )
            parts.append(f"[ECG 확인 소견] {confirmed_str}")
        if needs_confirm:
            confirm_str = ", ".join(
                f"{ko}({p}%)" for ko, p, _ in needs_confirm
            )
            parts.append(f"[추가 검사 권고] {confirm_str} — ECG 비특이적 소견, 혈액검사/영상검사 확인 필요")
        summary = " | ".join(parts)
        if context_note:
            summary += context_note

    report = summary
    if risk_level == "critical":
        report += " 즉각적인 처치가 필요합니다."
    elif risk_level == "urgent":
        report += " 신속한 추가 검사가 필요합니다."

    # suggested_next_actions (Lambda 동일 — NEXT_MODAL_MAP + modal 중복 제거)
    suggested_next_actions = []
    seen_modals: set[str] = set()
    for name in LABEL_NAMES:
        if not findings[LABEL_NAMES.index(name)].detected:
            continue
        action_info = NEXT_MODAL_MAP.get(name)
        if action_info and action_info["modal"] not in seen_modals:
            suggested_next_actions.append(action_info)
            seen_modals.add(action_info["modal"])

    # pertinent_negatives (Lambda 동일)
    complaint = ""
    if patient_info and hasattr(patient_info, "chief_complaint"):
        complaint = (patient_info.chief_complaint or "").lower()
    pertinent_negatives = []
    if "흉통" in complaint or "chest" in complaint:
        if "stemi" not in detected_keys:
            pertinent_negatives.append("STEMI 소견 없음")
        if "nstemi" not in detected_keys:
            pertinent_negatives.append("NSTEMI 소견 없음")
    if "호흡" in complaint or "dyspnea" in complaint:
        if "pe" not in detected_keys:
            pertinent_negatives.append("폐색전증 소견 없음")
        if "heart_failure" not in detected_keys:
            pertinent_negatives.append("심부전 소견 없음")

    # metadata (Lambda 동일)
    hr = compute_hr(signal)
    qtc = compute_qtc(hr)
    inference_time_ms = int((time.time() - _start) * 1000)
    metadata = {
        "hr": hr,
        "qtc": qtc,
        "leads": 12,
        "sampling_rate": 500,
        "duration_sec": 10,
        "inference_time_ms": inference_time_ms,
    }

    return {
        "findings": findings,
        "risk_level": risk_level,
        "summary": summary,
        "report": report,
        "pertinent_negatives": pertinent_negatives,
        "suggested_next_actions": suggested_next_actions,
        "metadata": metadata,
    }
