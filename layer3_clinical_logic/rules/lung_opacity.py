"""폐 음영 (Lung Opacity) — 감별 진단 엔진
다른 질환 Rule 결과를 종합하여 Opacity의 원인을 감별.
다른 Rule이 먼저 실행된 후에 호출되어야 함.
"""

from ..models import ClinicalLogicInput
from ..thresholds import get_threshold


def analyze(input: ClinicalLogicInput, other_results: dict = None) -> dict:
    d = input.densenet
    threshold = get_threshold("Lung_Opacity")

    detected = False
    evidence = []
    severity = None
    location = None
    alert = False
    primary_cause = None

    if d.Lung_Opacity > threshold:
        detected = True
        evidence.append(f"DenseNet Lung_Opacity: {d.Lung_Opacity:.2f}")

    # YOLO bbox 보조
    yolo_opacity = [det for det in input.yolo_detections if det.class_name == "Lung_Opacity"]
    if yolo_opacity:
        detected = True
        for det in yolo_opacity:
            evidence.append(f"YOLO Lung_Opacity conf {det.confidence:.2f}")
            if det.lobe:
                location = det.lobe

    if not detected:
        evidence.append("폐 음영 소견 없음")
        return {
            "finding": "Lung_Opacity",
            "detected": False,
            "confidence": "high",
            "evidence": evidence,
            "quantitative": {},
            "location": None,
            "severity": None,
            "recommendation": None,
            "alert": False,
        }

    # 다른 질환 결과를 확인하여 원인 감별
    if other_results:
        consol = other_results.get("Consolidation", {})
        edema_r = other_results.get("Edema", {})
        atel = other_results.get("Atelectasis", {})
        lesion = other_results.get("Lung_Lesion", {})

        if consol.get("detected"):
            primary_cause = "Consolidation"
            evidence.append("감별: Consolidation → 경화에 의한 음영")
            location = consol.get("location", location)
        elif edema_r.get("detected") and edema_r.get("quantitative", {}).get("bilateral_symmetric"):
            primary_cause = "Pulmonary Edema"
            evidence.append("감별: 양측 대칭 폐부종에 의한 음영")
        elif atel.get("detected"):
            primary_cause = "Atelectasis"
            evidence.append("감별: 무기폐에 의한 음영")
            location = atel.get("location", location)
        elif lesion.get("detected"):
            primary_cause = "Lung Lesion/Mass"
            evidence.append("감별: 폐 병변/종괴에 의한 음영")
            location = lesion.get("location", location)
        else:
            primary_cause = "Nonspecific"
            evidence.append("비특이적 음영, 추가 평가 필요")
    else:
        primary_cause = "Nonspecific"
        evidence.append("다른 Rule 결과 없음 — 비특이적 음영")

    severity = "moderate" if d.Lung_Opacity > 0.7 else "mild"
    confidence = "high" if primary_cause != "Nonspecific" else "low"

    return {
        "finding": "Lung_Opacity",
        "detected": detected,
        "confidence": confidence,
        "evidence": evidence,
        "quantitative": {
            "primary_cause": primary_cause,
            "lobe": location,
            "densenet_prob": round(d.Lung_Opacity, 4),
        },
        "location": location,
        "severity": severity,
        "recommendation": "CT 확인 권장" if primary_cause == "Nonspecific" else None,
        "alert": alert,
    }
