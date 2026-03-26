"""흉수 (Pleural Effusion) — CP angle 기반 판정"""

from ..models import ClinicalLogicInput
from ..thresholds import get_threshold, CP_ANGLE_SMALL, CP_ANGLE_MODERATE


def analyze(input: ClinicalLogicInput) -> dict:
    # ── confidence 판정 기준 (14개 Rule 공통) ──────────────────
    # "high"   — 2개 이상 독립 소스 일치 (CTR+DenseNet+YOLO 등)
    # "medium" — 1개 소스 양성 + 합리적 근거
    # "low"    — 1개 소스만 양성 + 근거 약함 (의사 확인 필요)
    a = input.anatomy
    d = input.densenet
    threshold = get_threshold("Pleural_Effusion")

    detected = False
    evidence = []
    severity = None
    location = None
    alert = False

    right_effusion = a.right_cp_status == "blunted"
    left_effusion = a.left_cp_status == "blunted"

    # CP angle 기반 판정
    if right_effusion or left_effusion:
        detected = True

        if right_effusion and left_effusion:
            location = "bilateral"
        elif right_effusion:
            location = "right"
        else:
            location = "left"

    # DenseNet 보조 판정
    if not detected and d.Pleural_Effusion > threshold:
        detected = True
        evidence.append(f"DenseNet Pleural_Effusion: {d.Pleural_Effusion:.2f}")

    # YOLO bbox 보조 판정
    yolo_eff = [det for det in input.yolo_detections if det.class_name == "Pleural_effusion"]
    if yolo_eff and not detected:
        detected = True
        for det in yolo_eff:
            evidence.append(f"YOLO Pleural_effusion bbox conf {det.confidence:.2f}")
    elif yolo_eff and detected:
        for det in yolo_eff:
            evidence.append(f"YOLO 교차 확인: Pleural_effusion bbox conf {det.confidence:.2f}")

    if not detected:
        evidence.append("CP angle 정상, 흉수 소견 없음")
        return {
            "finding": "Pleural_Effusion",
            "detected": False,
            "confidence": "high",
            "evidence": evidence,
            "quantitative": {},
            "location": None,
            "severity": None,
            "recommendation": None,
            "alert": False,
        }

    # 추정량 (각 side별)
    estimated_volume = {}
    for side, cp_angle, cp_status in [
        ("right", a.right_cp_angle_degrees, a.right_cp_status),
        ("left", a.left_cp_angle_degrees, a.left_cp_status),
    ]:
        if cp_status != "blunted" or cp_angle is None:
            continue
        if cp_angle <= CP_ANGLE_SMALL:
            vol = "small"
            evidence.append(f"{side} CP angle {cp_angle:.1f}deg -> small (~200-300mL)")
        elif cp_angle <= CP_ANGLE_MODERATE:
            vol = "moderate"
            evidence.append(f"{side} CP angle {cp_angle:.1f}deg -> moderate (~500mL)")
        else:
            vol = "large"
            evidence.append(f"{side} CP angle {cp_angle:.1f}deg -> large (>1000mL)")
        estimated_volume[side] = vol

    # 최대 볼륨으로 severity 결정
    vol_order = {"small": 1, "moderate": 2, "large": 3}
    max_vol = max(estimated_volume.values(), key=lambda v: vol_order.get(v, 0)) if estimated_volume else "small"
    severity = "mild" if max_vol == "small" else ("moderate" if max_vol == "moderate" else "severe")

    # 양측 흉수는 한 단계 severity 상향
    if location == "bilateral" and severity == "mild":
        severity = "moderate"
        evidence.append("양측 흉수 → severity 상향")

    # 동반 소견 교차: 양측 흉수 + CTR 상승 → CHF 관련
    recommendation = None
    if location == "bilateral" and a.ctr > 0.50:
        evidence.append(f"양측 흉수 + CTR {a.ctr:.4f} -> CHF 관련 흉수 가능")
        recommendation = "심초음파 및 BNP 확인 권장"

    # confidence
    confidence = "medium"
    if d.Pleural_Effusion > threshold and (right_effusion or left_effusion):
        confidence = "high"

    return {
        "finding": "Pleural_Effusion",
        "detected": detected,
        "confidence": confidence,
        "evidence": evidence,
        "quantitative": {
            "right_cp_angle": a.right_cp_angle_degrees,
            "left_cp_angle": a.left_cp_angle_degrees,
            "estimated_volume": estimated_volume if estimated_volume else max_vol,
            "location": location,
        },
        "location": location,
        "severity": severity,
        "recommendation": recommendation,
        "alert": alert,
    }
