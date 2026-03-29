import time
import numpy as np
import onnxruntime as ort

from app.signal_processing import compute_hr, compute_qtc
from app.schemas import Finding, PredictRequest, PredictResponse

LABEL_NAMES = [
    "stemi", "vfib_vtach", "avblock_3rd", "pe", "nstemi",
    "afib", "svt", "heart_failure", "sepsis",
    "hyperkalemia", "hypokalemia", "lbbb", "arrhythmia",
]

LABEL_KO = {
    "stemi":         "ST분절 상승 심근경색",
    "vfib_vtach":    "심실세동/심실빈맥",
    "avblock_3rd":   "3도 방실차단",
    "pe":            "폐색전증",
    "nstemi":        "비ST분절 상승 심근경색",
    "afib":          "심방세동",
    "svt":           "발작성 상심실 빈맥",
    "heart_failure": "심부전",
    "sepsis":        "패혈증",
    "hyperkalemia":  "고칼륨혈증",
    "hypokalemia":   "저칼륨혈증",
    "lbbb":          "좌각차단",
    "arrhythmia":    "부정맥",
}

LABEL_THRESHOLDS = {
    "stemi":         0.250,  # 응급 — Sensitivity >= 80% 유지
    "vfib_vtach":    0.170,  # 응급 — Sensitivity >= 80% 유지
    "avblock_3rd":   0.470,  # 응급 — Sensitivity >= 80% 유지
    "pe":            0.505,  # FP 완화(30%) — 모델 한계로 20% 달성 불가
    "nstemi":        0.470,
    "afib":          0.425,
    "svt":           0.345,  # FP 완화(30%) — 모델 한계로 20% 달성 불가
    "heart_failure": 0.440,
    "sepsis":        0.385,
    "hyperkalemia":  0.471,  # FP 완화(30%) 적용에도 55% — 재학습 필요
    "hypokalemia":   0.350,  # FP 완화(30%)
    "lbbb":          0.835,
    "arrhythmia":    0.445,
}

# margin 필터 미적용 레이블 (놓치면 안 됨 — 응급 + 멀티모달 트리거용)
EMERGENCY_LABELS = {"stemi", "vfib_vtach", "avblock_3rd", "hyperkalemia"}
DETECTION_MARGIN = 0.10  # prob - threshold < MARGIN 이면 감지 무시

CRITICAL_LABELS = {"stemi", "vfib_vtach", "avblock_3rd"}
URGENT_LABELS   = {"nstemi", "pe", "svt", "hyperkalemia"}

# ECG 파형으로 직접 확인 가능한 레이블
ECG_CONFIRMED_LABELS = {"stemi", "vfib_vtach", "avblock_3rd", "afib", "lbbb", "arrhythmia", "svt"}
# ECG 비특이적 — 다른 모달(혈액/흉부CT/영상) 추가 확인 필요
NEEDS_CONFIRMATION_LABELS = {"pe", "nstemi", "heart_failure", "sepsis", "hyperkalemia", "hypokalemia"}

# 감지 레이블 → 추천 다음 모달 매핑
NEXT_MODAL_MAP: dict[str, dict] = {
    "nstemi":        {"modal": "blood", "action": "트로포닌 I/T 검사", "description": "NSTEMI 의심 — 심근 바이오마커 확인 필요"},
    "heart_failure": {"modal": "blood", "action": "BNP/NT-proBNP 검사", "description": "심부전 의심 — 심장 바이오마커 확인 필요"},
    "sepsis":        {"modal": "blood", "action": "혈액배양 + 젖산 검사", "description": "패혈증 의심 — 감염 바이오마커 확인 필요"},
    "hyperkalemia":  {"modal": "blood", "action": "혈중 K+ 즉시 확인", "description": "고칼륨혈증 의심 — 전해질 검사 긴급 시행"},
    "hypokalemia":   {"modal": "blood", "action": "혈중 K+ 확인", "description": "저칼륨혈증 의심 — 전해질 검사 시행"},
    "pe":            {"modal": "chest", "action": "CT 폐혈관조영술(CTPA)", "description": "폐색전증 의심 — 흉부 영상 확인 필요"},
}

LABEL_SEVERITY = {
    "stemi":         "critical",
    "vfib_vtach":    "critical",
    "avblock_3rd":   "critical",
    "pe":            "severe",
    "nstemi":        "severe",
    "hyperkalemia":  "severe",
    "afib":          "moderate",
    "svt":           "moderate",
    "heart_failure": "moderate",
    "sepsis":        "moderate",
    "hypokalemia":   "mild",
    "lbbb":          "mild",
    "arrhythmia":    "mild",
}

LABEL_RECOMMENDATION = {
    "stemi":         "즉시 PCI(관상동맥 중재술) 팀 호출",
    "vfib_vtach":    "즉시 제세동 및 CPR 준비",
    "avblock_3rd":   "즉시 임시 심박동기 삽입 고려",
    "pe":            "CT 폐혈관조영술(CTPA) 시행",
    "nstemi":        "심장내과 협진 및 트로포닌 재검",
    "hyperkalemia":  "혈액 K+ 즉시 확인, 심전도 모니터링",
    "afib":          "심박수 조절 및 항응고 요법 검토",
    "svt":           "미주신경자극 또는 아데노신 투여 고려",
    "heart_failure": "BNP/NT-proBNP 검사 및 이뇨제 투여",
    "sepsis":        "혈액배양 후 광범위 항생제 투여",
    "hypokalemia":   "혈액 K+ 확인 및 전해질 보충",
    "lbbb":          "심장내과 협진, STEMI equivalent 배제",
    "arrhythmia":    "지속 심전도 모니터링",
}


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-x))


def _normalize(signal_array: np.ndarray) -> np.ndarray:
    """리드별 z-score 정규화"""
    mean = signal_array.mean(axis=1, keepdims=True)
    std  = signal_array.std(axis=1, keepdims=True)
    std[std == 0] = 1.0
    return ((signal_array - mean) / std).astype(np.float32)


def run_inference(signal_array: np.ndarray, request: PredictRequest,
                  session: ort.InferenceSession) -> PredictResponse:
    """
    ECG 추론 메인 함수

    Args:
        signal_array: (12, 5000) numpy array — 정규화 전 원본
        request: 표준 API 요청 객체
        session: ONNX InferenceSession

    Returns:
        PredictResponse (표준 API 규격)
    """
    try:
        _start      = time.time()
        normalized  = _normalize(signal_array)
        input_data  = normalized[np.newaxis, ...]          # (1, 12, 5000)
        logits      = session.run(None, {"ecg_signal": input_data})[0][0]
        probs       = _sigmoid(logits)

        # findings
        findings       = []
        detected_names = []
        for name, prob in zip(LABEL_NAMES, probs):
            threshold = LABEL_THRESHOLDS[name]
            over_threshold = bool(prob > threshold)
            # 응급 레이블은 margin 필터 미적용, 나머지는 margin 미달 시 음성 처리
            if over_threshold and name not in EMERGENCY_LABELS:
                detected = (prob - threshold) >= DETECTION_MARGIN
            else:
                detected = over_threshold
            findings.append(Finding(
                name           = LABEL_KO[name],
                detected       = detected,
                confidence     = round(float(prob), 4),
                detail         = f"임계값 {threshold} 기준 {'감지됨' if detected else '음성'}",
                severity       = LABEL_SEVERITY[name] if detected else None,
                recommendation = LABEL_RECOMMENDATION[name] if detected else None,
            ))
            if detected:
                detected_names.append(LABEL_KO[name])

        # risk_level
        detected_keys = {name for name, prob in zip(LABEL_NAMES, probs)
                         if findings[LABEL_NAMES.index(name)].detected}
        if detected_keys & CRITICAL_LABELS:
            risk_level = "critical"
        elif detected_keys & URGENT_LABELS:
            risk_level = "urgent"
        else:
            risk_level = "routine"

        # summary & report (context 반영)
        prev         = request.context.get("previous_findings", "")
        context_note = f" {prev} 맥락과 함께 해석 필요." if prev else ""

        # ECG 확인 소견 vs 추가 검사 필요 소견 분류
        ecg_confirmed   = []   # (ko_name, prob, recommendation)
        needs_confirm   = []   # (ko_name, prob, recommendation)
        for name, prob in zip(LABEL_NAMES, probs):
            if not findings[LABEL_NAMES.index(name)].detected:
                continue
            ko   = LABEL_KO[name]
            rec  = LABEL_RECOMMENDATION[name]
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

        # suggested_next_actions
        suggested_next_actions = []
        seen_modals: set[str] = set()
        for name in LABEL_NAMES:
            if not findings[LABEL_NAMES.index(name)].detected:
                continue
            action_info = NEXT_MODAL_MAP.get(name)
            if action_info and action_info["modal"] not in seen_modals:
                suggested_next_actions.append(action_info)
                seen_modals.add(action_info["modal"])

        # pertinent_negatives (주소증 관련 음성 소견)
        complaint = ""
        if request.patient_info:
            complaint = (request.patient_info.chief_complaint or "").lower()
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

        # metadata
        hr  = compute_hr(signal_array)
        qtc = compute_qtc(hr)
        inference_time_ms = int((time.time() - _start) * 1000)
        metadata = {
            "hr":                hr,
            "qtc":               qtc,
            "leads":             12,
            "sampling_rate":     500,
            "duration_sec":      10,
            "inference_time_ms": inference_time_ms,
        }

        return PredictResponse(
            status                  = "success",
            modal                   = "ecg",
            findings                = findings,
            summary                 = summary,
            report                  = report,
            risk_level              = risk_level,
            pertinent_negatives     = pertinent_negatives,
            suggested_next_actions  = suggested_next_actions,
            metadata                = metadata,
        )

    except Exception as e:
        return PredictResponse(status="error", findings=[], error=str(e))
