"""경화 (Consolidation) — Silhouette sign + 폐엽 매핑"""

from ..models import ClinicalLogicInput
from ..thresholds import get_threshold


def analyze(input: ClinicalLogicInput) -> dict:
    a = input.anatomy
    d = input.densenet
    threshold = get_threshold("Consolidation")

    detected = False
    evidence = []
    severity = None
    location = None
    lobe = None
    alert = False

    # DenseNet 확률
    if d.Consolidation > threshold:
        detected = True
        evidence.append(f"DenseNet Consolidation: {d.Consolidation:.2f}")

    # YOLO bbox
    yolo_consol = [det for det in input.yolo_detections if det.class_name == "Consolidation"]
    if yolo_consol:
        detected = True
        for det in yolo_consol:
            evidence.append(f"YOLO Consolidation bbox conf {det.confidence:.2f}")
            if det.lobe:
                lobe = det.lobe
                evidence.append(f"폐엽 매핑: {det.lobe}")

    if not detected:
        evidence.append("경화 소견 없음")
        return {
            "finding": "Consolidation",
            "detected": False,
            "confidence": "high",
            "evidence": evidence,
            "quantitative": {},
            "location": None,
            "severity": None,
            "recommendation": None,
            "alert": False,
        }

    # YOLO bbox가 있으면 폐엽 매핑으로 위치 결정
    if lobe:
        lobe_names = {
            "RUL": "우상엽", "RML": "우중엽", "RLL": "우하엽",
            "LUL": "좌상엽", "LLL": "좌하엽",
        }
        location = lobe_names.get(lobe, lobe)

    # Silhouette sign 추정 (YOLO bbox 기반)
    if yolo_consol:
        det = yolo_consol[0]
        bbox = det.bbox
        bbox_cx = (bbox[0] + bbox[2]) / 2
        bbox_cy = (bbox[1] + bbox[3]) / 2
        img_cx = a.thorax_width_px / 2 if a.thorax_width_px > 0 else 256
        if bbox_cx < img_cx:
            side = "right"
        else:
            side = "left"

        if not lobe:
            if bbox_cy < a.thorax_width_px * 0.35:
                lobe = f"{side[0].upper()}UL"
            else:
                lobe = f"{side[0].upper()}LL"
            location = lobe

    # bbox 면적 비율
    area_percent = None
    if yolo_consol:
        det = yolo_consol[0]
        bbox = det.bbox
        bbox_area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
        if a.total_lung_area_px2 > 0:
            area_percent = round(bbox_area / a.total_lung_area_px2 * 100, 1)

    # severity
    if area_percent is not None:
        if area_percent > 20:
            severity = "severe"
        elif area_percent > 10:
            severity = "moderate"
        else:
            severity = "mild"
    else:
        severity = "moderate" if d.Consolidation > 0.7 else "mild"

    confidence = "high" if d.Consolidation > threshold and yolo_consol else "medium"

    return {
        "finding": "Consolidation",
        "detected": detected,
        "confidence": confidence,
        "evidence": evidence,
        "quantitative": {
            "lobe": lobe,
            "area_percent": area_percent,
            "densenet_prob": round(d.Consolidation, 4),
        },
        "location": location,
        "severity": severity,
        "recommendation": None,
        "alert": alert,
    }
