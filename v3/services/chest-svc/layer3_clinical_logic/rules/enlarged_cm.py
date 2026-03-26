"""종격동 확대 (Enlarged Cardiomediastinum) — 종격동 너비 판정"""

from ..models import ClinicalLogicInput
from ..thresholds import get_threshold, MEDIASTINUM_RATIO


def analyze(input: ClinicalLogicInput, other_results: dict = None) -> dict:
    a = input.anatomy
    d = input.densenet
    threshold = get_threshold("Enlarged_Cardiomediastinum")

    detected = False
    evidence = []
    severity = None
    alert = False
    recommendation = None
    # 심비대(Cardiomegaly) 중복 소견 여부 플래그
    secondary_to_cardiomegaly = False

    # 종격동 너비 기반 판정
    if a.mediastinum_width_px is not None and a.mediastinum_status is not None:
        if a.mediastinum_status == "enlarged":
            detected = True
            evidence.append(f"종격동 확대 (status: {a.mediastinum_status})")
    elif a.mediastinum_width_px is not None and a.thorax_width_px > 0:
        ratio = a.mediastinum_width_px / a.thorax_width_px
        if ratio > MEDIASTINUM_RATIO:
            detected = True
            evidence.append(
                f"종격동/흉곽 비율 {ratio:.3f} (threshold {MEDIASTINUM_RATIO})"
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
            "quantitative": {
                "secondary_to_cardiomegaly": False,
            },
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

    # ── Cardiomegaly 중복 소견 보정 ──
    # 심비대가 이미 감지된 경우, 종격동 확대는 동반 소견일 가능성이 높으므로
    # confidence/severity를 하향 조정하여 중복 보고를 억제한다.
    if other_results and detected:
        cardio = other_results.get("Cardiomegaly", {})
        if cardio.get("detected", False):
            secondary_to_cardiomegaly = True
            # 기본: 심비대 동반 소견으로 격하
            confidence = "low"
            severity = "mild"
            evidence.append(
                "심비대에 의한 종격동 확대 — Cardiomegaly의 동반 소견"
            )
            # 예외: DenseNet 고확률 + 해부학적 종격동 확대 → 독립 소견 유지 가능
            if (
                d.Enlarged_Cardiomediastinum > 0.75
                and a.mediastinum_status == "enlarged"
            ):
                confidence = "medium"
                recommendation = "CT 확인 권장 — 종격동 독립 병변 가능"
                evidence.append(
                    f"DenseNet {d.Enlarged_Cardiomediastinum:.2f} + 종격동 확대 "
                    "→ 독립 병변 가능성, CT 권장"
                )

    return {
        "finding": "Enlarged_Cardiomediastinum",
        "detected": detected,
        "confidence": confidence,
        "evidence": evidence,
        "quantitative": {
            "mediastinum_width_px": a.mediastinum_width_px,
            "secondary_to_cardiomegaly": secondary_to_cardiomegaly,
        },
        "location": "mediastinum",
        "severity": severity,
        "recommendation": recommendation,
        "alert": alert,
    }
