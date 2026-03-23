"""기흉 (Pneumothorax) — 폐 경계~흉벽 거리 + Tension 판정"""

from ..models import ClinicalLogicInput
from ..thresholds import get_threshold


def analyze(input: ClinicalLogicInput) -> dict:
    a = input.anatomy
    d = input.densenet
    threshold = get_threshold("Pneumothorax")

    detected = False
    evidence = []
    severity = None
    location = None
    alert = False
    recommendation = None
    size = None
    tension = False

    # DenseNet 확률 기반 판정
    if d.Pneumothorax > threshold:
        detected = True
        evidence.append(f"DenseNet Pneumothorax: {d.Pneumothorax:.2f}")

    # YOLO bbox 기반 보조 판정
    yolo_ptx = [det for det in input.yolo_detections if det.class_name == "Pneumothorax"]
    if yolo_ptx:
        detected = True
        for det in yolo_ptx:
            evidence.append(f"YOLO Pneumothorax bbox conf {det.confidence:.2f}")

    if not detected:
        evidence.append("기흉 소견 없음")
        return {
            "finding": "Pneumothorax",
            "detected": False,
            "confidence": "high",
            "evidence": evidence,
            "quantitative": {},
            "location": None,
            "severity": None,
            "recommendation": None,
            "alert": False,
        }

    # 폐 면적비로 affected side 추정
    ratio = a.lung_area_ratio  # left / right
    if ratio < 0.70:
        location = "left"
        evidence.append(f"좌측 폐 면적 감소 (좌/우 비 {ratio:.3f})")
    elif ratio > 1.30:
        location = "right"
        r_inv = 1.0 / ratio if ratio > 0 else 0
        evidence.append(f"우측 폐 면적 감소 (좌/우 비 {ratio:.3f})")
    else:
        location = "indeterminate"

    # 크기 판정 (정밀한 거리 측정 불가 시 DenseNet 확률로 대체)
    if d.Pneumothorax > 0.80:
        size = "large"
        severity = "severe"
    elif d.Pneumothorax > 0.60:
        size = "moderate"
        severity = "moderate"
    else:
        size = "small"
        severity = "mild"

    # Tension pneumothorax 판정
    if a.trachea_midline is not None and not a.trachea_midline:
        dev_dir = a.trachea_deviation_direction
        # 기관이 병변 반대쪽으로 밀리면 tension
        if (location == "left" and dev_dir == "right") or \
           (location == "right" and dev_dir == "left"):
            tension = True
            alert = True
            severity = "critical"
            evidence.append(
                f"기관 {dev_dir}측 편위 → TENSION PNEUMOTHORAX 의심"
            )

    # 횡격막 하강 (동측) → tension 추가 근거
    if a.diaphragm_status is not None:
        if (location == "left" and a.diaphragm_status == "elevated_left") or \
           (location == "right" and a.diaphragm_status == "elevated_right"):
            evidence.append(f"동측 횡격막 하강 → tension 추가 근거")
            if not tension:
                tension = True
                alert = True
                severity = "critical"

    # 추천
    if tension:
        recommendation = "응급: 즉시 바늘 감압 또는 흉관 삽입"
    elif size == "large":
        recommendation = "흉관 삽입 고려"
    elif size == "moderate":
        recommendation = "흉관 삽입 또는 경과 관찰"
    else:
        recommendation = "경과 관찰, 추적 촬영 권장"

    confidence = "high" if d.Pneumothorax > threshold and yolo_ptx else "medium"

    return {
        "finding": "Pneumothorax",
        "detected": detected,
        "confidence": confidence,
        "evidence": evidence,
        "quantitative": {
            "side": location,
            "size": size,
            "tension": tension,
            "densenet_prob": round(d.Pneumothorax, 4),
        },
        "location": location,
        "severity": severity,
        "recommendation": recommendation,
        "alert": alert,
    }
