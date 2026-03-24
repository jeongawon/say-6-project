"""골절 (Fracture) — 동반 손상 교차"""

from ..models import ClinicalLogicInput
from ..thresholds import get_threshold


def analyze(input: ClinicalLogicInput) -> dict:
    a = input.anatomy
    d = input.densenet
    threshold = get_threshold("Fracture")

    detected = False
    evidence = []
    severity = None
    location = None
    alert = False
    recommendation = "CT 확인 권장 (CXR 골절 민감도 30~50%)"

    # DenseNet
    if d.Fracture > threshold:
        detected = True
        evidence.append(f"DenseNet Fracture: {d.Fracture:.2f}")

    # YOLO bbox
    yolo_frac = [det for det in input.yolo_detections
                 if det.class_name in ("Rib_fracture", "Clavicle_fracture", "Fracture")]
    if yolo_frac:
        detected = True
        for det in yolo_frac:
            # bbox y좌표로 늑골 번호 대략 추정
            bbox = det.bbox
            bbox_cy = (bbox[1] + bbox[3]) / 2
            # thorax_width_px를 이미지 높이 proxy로 사용
            img_h = a.thorax_width_px if a.thorax_width_px > 0 else 512
            y_ratio = bbox_cy / img_h

            if y_ratio < 0.25:
                rib_est = "제1~3늑골"
            elif y_ratio < 0.50:
                rib_est = "제4~6늑골"
            else:
                rib_est = "제7~10늑골"

            # 좌/우 판별
            bbox_cx = (bbox[0] + bbox[2]) / 2
            img_cx = a.thorax_width_px / 2 if a.thorax_width_px > 0 else 256
            side = "right" if bbox_cx < img_cx else "left"

            evidence.append(
                f"{side}측 {rib_est} 골절 의심 (YOLO {det.class_name} conf {det.confidence:.2f})"
            )
            location = f"{side} {rib_est}"

    if not detected:
        evidence.append("골절 소견 없음")
        return {
            "finding": "Fracture",
            "detected": False,
            "confidence": "high",
            "evidence": evidence,
            "quantitative": {},
            "location": None,
            "severity": None,
            "recommendation": None,
            "alert": False,
        }

    # 동반 손상 자동 교차 (다른 Rule 결과는 engine에서 수행하지만, DenseNet으로 미리 체크)
    associated = []
    if d.Pneumothorax > get_threshold("Pneumothorax"):
        associated.append("외상성 기흉 동반 가능")
    if d.Pleural_Effusion > get_threshold("Pleural_Effusion"):
        associated.append("혈흉 가능")
    if associated:
        evidence.extend(associated)
        alert = True

    severity = "moderate" if len(yolo_frac) > 1 else "mild"
    confidence = "high" if d.Fracture > threshold and yolo_frac else "medium"

    return {
        "finding": "Fracture",
        "detected": detected,
        "confidence": confidence,
        "evidence": evidence,
        "quantitative": {
            "yolo_count": len(yolo_frac),
            "associated_pneumothorax": d.Pneumothorax > get_threshold("Pneumothorax"),
            "associated_effusion": d.Pleural_Effusion > get_threshold("Pleural_Effusion"),
        },
        "location": location,
        "severity": severity,
        "recommendation": recommendation,
        "alert": alert,
    }
