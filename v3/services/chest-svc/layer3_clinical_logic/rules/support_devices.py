"""의료 기구 (Support Devices) — 팁~carina 거리 판정"""

from ..models import ClinicalLogicInput
from ..thresholds import get_threshold, px_to_cm


def analyze(input: ClinicalLogicInput) -> dict:
    # ── confidence 판정 기준 (14개 Rule 공통) ──────────────────
    # "high"   — 2개 이상 독립 소스 일치 (CTR+DenseNet+YOLO 등)
    # "medium" — 1개 소스 양성 + 합리적 근거
    # "low"    — 1개 소스만 양성 + 근거 약함 (의사 확인 필요)
    a = input.anatomy
    d = input.densenet
    threshold = get_threshold("Support_Devices")

    detected = False
    evidence = []
    severity = None
    location = None
    alert = False
    recommendation = None
    device_type = None

    # DenseNet
    if d.Support_Devices > threshold:
        detected = True
        evidence.append(f"DenseNet Support_Devices: {d.Support_Devices:.2f}")

    # YOLO bbox
    device_classes = {"ETT", "NG_tube", "CVC", "Swan_Ganz", "Chest_tube",
                      "Support_Devices", "Tracheostomy"}
    yolo_devices = [det for det in input.yolo_detections
                    if det.class_name in device_classes]
    if yolo_devices:
        detected = True
        device_type = yolo_devices[0].class_name

    if not detected:
        evidence.append("의료 기구 미감지")
        return {
            "finding": "Support_Devices",
            "detected": False,
            "confidence": "high",
            "evidence": evidence,
            "quantitative": {},
            "location": None,
            "severity": None,
            "recommendation": None,
            "alert": False,
        }

    # px→cm 환산 (thresholds.py 중앙 관리)

    # 기구별 위치 판정
    for det in yolo_devices:
        bbox = det.bbox
        device = det.class_name
        evidence.append(f"{device} 감지 (conf {det.confidence:.2f})")

        if device == "ETT":
            tip_y = bbox[3]
            img_h = a.thorax_width_px if a.thorax_width_px > 0 else 512
            carina_y = img_h * 0.30

            dist_px = abs(tip_y - carina_y)
            dist_cm = px_to_cm(dist_px)

            if dist_cm < 3.0:
                alert = True
                evidence.append(f"ETT 팁~carina {dist_cm}cm -> 너무 깊음, 우측 주기관지 삽입 위험")
                recommendation = "ETT 위치 재조정 필요"
            elif dist_cm > 5.0:
                evidence.append(f"ETT 팁~carina {dist_cm}cm -> 너무 얕음, 발관 위험")
                recommendation = "ETT 위치 확인 필요"
            else:
                evidence.append(f"ETT 팁~carina {dist_cm}cm -> 정상 위치")

        elif device == "NG_tube":
            bbox_cx = (bbox[0] + bbox[2]) / 2
            img_cx = a.thorax_width_px / 2 if a.thorax_width_px > 0 else 256
            if bbox_cx < img_cx * 0.8:
                evidence.append("NG tube — 위치 확인 필요 (좌측 편향)")
            else:
                evidence.append("NG tube 감지")

    severity = "mild"
    if alert:
        severity = "moderate"

    confidence = "high" if yolo_devices else "medium"

    return {
        "finding": "Support_Devices",
        "detected": detected,
        "confidence": confidence,
        "evidence": evidence,
        "quantitative": {
            "device_type": device_type,
            "device_count": len(yolo_devices),
        },
        "location": location,
        "severity": severity,
        "recommendation": recommendation,
        "alert": alert,
    }
