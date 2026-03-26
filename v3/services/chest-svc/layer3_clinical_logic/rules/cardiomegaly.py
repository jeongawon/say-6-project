"""심비대 (Cardiomegaly) — CTR 기반 판정"""

from ..models import ClinicalLogicInput
from ..thresholds import get_threshold, CTR_NORMAL_UPPER, CTR_MODERATE, CTR_SEVERE


def analyze(input: ClinicalLogicInput) -> dict:
    # ── confidence 판정 기준 (14개 Rule 공통) ──────────────────
    # "high"   — 2개 이상 독립 소스 일치 (CTR+DenseNet+YOLO 등)
    # "medium" — 1개 소스 양성 + 합리적 근거
    # "low"    — 1개 소스만 양성 + 근거 약함 (의사 확인 필요)
    a = input.anatomy
    d = input.densenet
    threshold = get_threshold("Cardiomegaly")

    ctr = a.ctr
    detected = ctr > CTR_NORMAL_UPPER
    evidence = []
    severity = None
    confidence = "medium"
    alert = False

    if detected:
        evidence.append(f"CTR {ctr:.4f} (정상 <{CTR_NORMAL_UPPER})")

        # 중증도 분류
        if ctr > CTR_SEVERE:
            severity = "severe"
        elif ctr > CTR_MODERATE:
            severity = "moderate"
        else:
            severity = "mild"

        # DenseNet 교차 검증으로 confidence 결정
        if d.Cardiomegaly > threshold:
            confidence = "high"
            evidence.append(f"DenseNet Cardiomegaly: {d.Cardiomegaly:.2f}")
        elif d.Cardiomegaly < 0.3:
            confidence = "low"
            evidence.append(f"DenseNet Cardiomegaly: {d.Cardiomegaly:.2f} (불일치)")

        # YOLO Cardiomegaly bbox 교차 검증
        yolo_cardio = [det for det in input.yolo_detections if det.class_name == "Cardiomegaly"]
        if yolo_cardio:
            confidence = "high"
            evidence.append(f"YOLO Cardiomegaly bbox conf {yolo_cardio[0].confidence:.2f}")

        # AP뷰에서는 심장이 확대되어 보이므로 confidence 하향
        if a.view == "AP":
            if confidence == "high":
                confidence = "medium"
            elif confidence == "medium":
                confidence = "low"
            evidence.append("AP 뷰 — 심장 확대 가능성 고려 필요")
    else:
        evidence.append(f"CTR {ctr:.4f} (정상 범위)")

    return {
        "finding": "Cardiomegaly",
        "detected": detected,
        "confidence": confidence,
        "evidence": evidence,
        "quantitative": {
            "ctr": round(ctr, 4),
            "heart_width_px": a.heart_width_px,
            "thorax_width_px": a.thorax_width_px,
        },
        "location": None,
        "severity": severity,
        "recommendation": (
            "심초음파 + BNP 검사 즉시 권장, 심부전 감별 필요" if severity == "severe"
            else "심초음파 검사 권장" if severity == "moderate"
            else "추적 관찰 권장 (6개월 후 재검)" if severity == "mild"
            else None
        ),
        "alert": alert,
    }
