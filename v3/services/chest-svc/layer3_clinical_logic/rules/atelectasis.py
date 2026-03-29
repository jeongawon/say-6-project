"""무기폐 (Atelectasis) — 폐 면적비 + 종격동 이동 방향"""

from ..models import ClinicalLogicInput
from thresholds import get_threshold, LUNG_RATIO_ATELECTASIS_LOW, LUNG_RATIO_ATELECTASIS_HIGH


def analyze(input: ClinicalLogicInput) -> dict:
    # ── confidence 판정 기준 (14개 Rule 공통) ──────────────────
    # "high"   — 2개 이상 독립 소스 일치 (CTR+DenseNet+YOLO 등)
    # "medium" — 1개 소스 양성 + 합리적 근거
    # "low"    — 1개 소스만 양성 + 근거 약함 (의사 확인 필요)
    a = input.anatomy
    d = input.densenet
    threshold = get_threshold("Atelectasis")

    detected = False
    evidence = []
    severity = None
    location = None
    alert = False
    recommendation = None

    ratio = a.lung_area_ratio  # left / right

    # 폐 면적 감소 판정 (0.80 미만이면 의심)
    area_decreased = False
    affected_side = None
    area_reduction_pct = 0.0

    if ratio < LUNG_RATIO_ATELECTASIS_LOW:
        area_decreased = True
        affected_side = "left"
        area_reduction_pct = round((1.0 - ratio) * 100, 1)
    elif ratio > LUNG_RATIO_ATELECTASIS_HIGH:
        area_decreased = True
        affected_side = "right"
        area_reduction_pct = round((1.0 - 1.0 / ratio) * 100, 1)

    if area_decreased:
        evidence.append(f"{affected_side}측 폐 면적 감소 {area_reduction_pct:.1f}%")

        # 종격동 이동 방향으로 무기폐 vs 흉수 감별
        trachea_dir = a.trachea_deviation_direction
        if trachea_dir is not None and trachea_dir != "none":
            if trachea_dir == affected_side:
                detected = True
                evidence.append(f"종격동 {trachea_dir}측 이동 (동측) -> 무기폐")
            else:
                evidence.append(f"종격동 {trachea_dir}측 이동 (반대측) -> 흉수 가능성")
        else:
            if d.Atelectasis > threshold:
                detected = True
                evidence.append(f"DenseNet Atelectasis: {d.Atelectasis:.2f}")

        # 동측 횡격막 거상 → 추가 근거
        if a.diaphragm_status is not None:
            if (affected_side == "right" and a.diaphragm_status == "elevated_right") or \
               (affected_side == "left" and a.diaphragm_status == "elevated_left"):
                detected = True
                evidence.append(f"{affected_side}측 횡격막 거상 -> 무기폐 추가 근거")

    # 면적 감소 없지만 DenseNet 양성
    if not detected and d.Atelectasis > threshold:
        detected = True
        evidence.append(f"DenseNet Atelectasis: {d.Atelectasis:.2f} (면적비는 정상 범위)")

    if not detected:
        evidence.append("무기폐 소견 없음")
        return {
            "finding": "Atelectasis",
            "detected": False,
            "confidence": "high",
            "evidence": evidence,
            "quantitative": {"lung_area_ratio": round(ratio, 4)},
            "location": None,
            "severity": None,
            "recommendation": None,
            "alert": False,
        }

    # severity
    if area_reduction_pct > 40:
        severity = "severe"
    elif area_reduction_pct > 25:
        severity = "moderate"
    else:
        severity = "mild"

    location = affected_side

    mediastinal_shift = "ipsilateral" if (
        a.trachea_deviation_direction == affected_side
    ) else "none"

    confidence = "high" if area_decreased and mediastinal_shift == "ipsilateral" else "medium"

    return {
        "finding": "Atelectasis",
        "detected": detected,
        "confidence": confidence,
        "evidence": evidence,
        "quantitative": {
            "affected_side": affected_side,
            "area_reduction_percent": area_reduction_pct,
            "lung_area_ratio": round(ratio, 4),
            "mediastinal_shift": mediastinal_shift,
        },
        "location": location,
        "severity": severity,
        "recommendation": recommendation,
        "alert": alert,
    }
