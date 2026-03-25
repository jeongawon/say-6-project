"""기타 흉막 이상 (Pleural Other) — 비후 두께 + 석면 교차"""

from ..models import ClinicalLogicInput
from ..thresholds import get_threshold


def analyze(input: ClinicalLogicInput) -> dict:
    a = input.anatomy
    d = input.densenet
    threshold = get_threshold("Pleural_Other")  # 0.25 (매우 희귀)

    detected = False
    evidence = []
    severity = None
    location = None
    alert = False
    recommendation = None

    # DenseNet (낮은 threshold 적용)
    if d.Pleural_Other > threshold:
        detected = True
        evidence.append(f"DenseNet Pleural_Other: {d.Pleural_Other:.2f} (낮은 threshold {threshold} 적용)")

    # YOLO bbox
    yolo_pleural = [det for det in input.yolo_detections
                    if det.class_name in ("Pleural_thickening", "Pleural_Other")]
    if yolo_pleural:
        detected = True
        for det in yolo_pleural:
            evidence.append(f"YOLO {det.class_name} conf {det.confidence:.2f}")
            bbox_cx = (det.bbox[0] + det.bbox[2]) / 2
            img_cx = a.thorax_width_px / 2 if a.thorax_width_px > 0 else 256
            side = "right" if bbox_cx < img_cx else "left"
            location = f"{side} pleura"

    if not detected:
        evidence.append("기타 흉막 이상 없음")
        return {
            "finding": "Pleural_Other",
            "detected": False,
            "confidence": "high",
            "evidence": evidence,
            "quantitative": {},
            "location": None,
            "severity": None,
            "recommendation": None,
            "alert": False,
        }

    # 석면 노출 교차
    if input.patient_info and input.patient_info.chief_complaint:
        cc = input.patient_info.chief_complaint.lower()
        if "석면" in cc or "asbestos" in cc:
            evidence.append("석면 노출력 -> 석면 관련 흉막 병변 가능")
            recommendation = "CT 확인 + 직업병 상담 권장"

    severity = "mild"
    confidence = "medium" if d.Pleural_Other > threshold else "low"

    return {
        "finding": "Pleural_Other",
        "detected": detected,
        "confidence": confidence,
        "evidence": evidence,
        "quantitative": {
            "side": location,
            "densenet_prob": round(d.Pleural_Other, 4),
        },
        "location": location,
        "severity": severity,
        "recommendation": recommendation,
        "alert": alert,
    }
