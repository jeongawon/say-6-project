"""종격동 확대 (Enlarged Cardiomediastinum) — 종격동 너비 판정"""

from ..models import ClinicalLogicInput
from ..thresholds import get_threshold


# 종격동 너비 threshold (px 비율 기반)
MEDIASTINUM_RATIO_THRESHOLD = 0.33


def analyze(input: ClinicalLogicInput) -> dict:
    a = input.anatomy
    d = input.densenet
    threshold = get_threshold("Enlarged_Cardiomediastinum")

    detected = False
    evidence = []
    severity = None
    alert = False
    recommendation = None

    # 종격동 너비 기반 판정
    if a.mediastinum_width_px is not None and a.mediastinum_status is not None:
        if a.mediastinum_status == "enlarged":
            detected = True
            evidence.append(f"종격동 확대 (status: {a.mediastinum_status})")
    elif a.mediastinum_width_px is not None and a.thorax_width_px > 0:
        ratio = a.mediastinum_width_px / a.thorax_width_px
        if ratio > MEDIASTINUM_RATIO_THRESHOLD:
            detected = True
            evidence.append(
                f"종격동/흉곽 비율 {ratio:.3f} (threshold {MEDIASTINUM_RATIO_THRESHOLD})"
            )

    # DenseNet 보조
    if not detected and d.Enlarged_Cardiomediastinum > threshold:
        detected = True
        evidence.append(f"DenseNet Enlarged_CM: {d.Enlarged_Cardiomediastinum:.2f}")

    if not detected:
        evidence.append("종격동 정상")
        return {
            "finding": "Enlarged_Cardiomediastinum",
            "detected": False,
            "confidence": "high",
            "evidence": evidence,
            "quantitative": {},
            "location": "mediastinum",
            "severity": None,
            "recommendation": None,
            "alert": False,
        }

    # 동반 소견
    if a.trachea_midline is not None and not a.trachea_midline:
        evidence.append(f"기관 편위 동반 -> 종괴에 의한 종격동 확대 가능")
    if a.ctr > 0.50:
        evidence.append(f"CTR {a.ctr:.4f} -> 심비대에 의한 것일 수 있음")

    severity = "moderate" if d.Enlarged_Cardiomediastinum > 0.6 else "mild"
    confidence = "medium"
    if d.Enlarged_Cardiomediastinum > threshold:
        confidence = "high" if a.mediastinum_status == "enlarged" else "medium"

    return {
        "finding": "Enlarged_Cardiomediastinum",
        "detected": detected,
        "confidence": confidence,
        "evidence": evidence,
        "quantitative": {
            "mediastinum_width_px": a.mediastinum_width_px,
        },
        "location": "mediastinum",
        "severity": severity,
        "recommendation": recommendation,
        "alert": alert,
    }
