"""심비대 (Cardiomegaly) — CTR 기반 판정"""

from ..models import ClinicalLogicInput
from ..thresholds import get_threshold


def analyze(input: ClinicalLogicInput) -> dict:
    # ── confidence 판정 기준 (14개 Rule 공통) ──────────────────
    # "high"   — 2개 이상 독립 소스 일치 (CTR+DenseNet+YOLO 등)
    # "medium" — 1개 소스 양성 + 합리적 근거
    # "low"    — 1개 소스만 양성 + 근거 약함 (의사 확인 필요)
    a = input.anatomy
    d = input.densenet
    threshold = get_threshold("Cardiomegaly")

    ctr = a.ctr
    detected = ctr > 0.50
    evidence = []
    severity = None
    confidence = "medium"
    alert = False

    if detected:
        evidence.append(f"CTR {ctr:.4f} (정상 <0.50)")

        # 중증도 분류
        if ctr > 0.60:
            severity = "severe"
        elif ctr > 0.55:
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
        "recommendation": "심초음파 추적 권장" if severity == "severe" else None,
        "alert": alert,
    }
