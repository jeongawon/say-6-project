"""폐 음영 (Lung Opacity) — 감별 진단 엔진.
다른 질환 Rule 결과를 종합하여 Opacity의 원인을 감별.
다른 Rule이 먼저 실행된 후에 호출되어야 함.
"""

from ..models import ClinicalLogicInput
from thresholds import get_threshold


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

    # ── 다른 질환 결과를 확인하여 원인 감별 ──
    # 2차 소견 분류: 원인 소견의 DenseNet 확률이 Lung_Opacity보다 높을 때만 적용.
    # 이렇게 하면 원인이 불확실한(과검출 의심) 소견이 Opacity를 억제하지 않는다.
    independent = True
    if other_results:
        consol = other_results.get("Consolidation", {})
        edema_r = other_results.get("Edema", {})
        atel = other_results.get("Atelectasis", {})
        lesion = other_results.get("Lung_Lesion", {})

        if consol.get("detected") and d.Consolidation > d.Lung_Opacity:
            # Consolidation DenseNet 확률이 Lung_Opacity보다 높을 때만 귀속
            primary_cause = "Consolidation"
            independent = False
            evidence.append(
                f"감별: Consolidation({d.Consolidation:.2f}) > "
                f"Lung_Opacity({d.Lung_Opacity:.2f}) — 경화에 의한 음영 (2차)"
            )
            location = consol.get("location", location)
        elif consol.get("detected"):
            primary_cause = "Nonspecific"
            evidence.append(
                f"Consolidation 검출되나 DenseNet 확률({d.Consolidation:.2f})"
                f" ≤ Opacity({d.Lung_Opacity:.2f}) — 독립 음영 유지"
            )
        elif edema_r.get("detected"):
            bilateral = edema_r.get("quantitative", {}).get("bilateral_symmetric")
            edema_conf = edema_r.get("confidence", "low")
            if bilateral and edema_conf in ("high", "medium"):
                primary_cause = "Pulmonary Edema"
                independent = False
                evidence.append("감별: 고신뢰 Pulmonary Edema에 의한 음영 (2차)")
            else:
                primary_cause = "Nonspecific"
                if edema_r.get("detected") and not bilateral:
                    evidence.append("부종 있으나 비대칭 — 독립 음영 가능")
                else:
                    evidence.append("비특이적 음영, 추가 평가 필요")
        elif atel.get("detected") and d.Atelectasis > d.Lung_Opacity:
            primary_cause = "Atelectasis"
            independent = False
            evidence.append(
                f"감별: Atelectasis({d.Atelectasis:.2f}) > "
                f"Lung_Opacity({d.Lung_Opacity:.2f}) — 무기폐에 의한 음영 (2차)"
            )
            location = atel.get("location", location)
        elif atel.get("detected"):
            primary_cause = "Nonspecific"
            evidence.append("비특이적 음영, 추가 평가 필요")
        elif lesion.get("detected"):
            primary_cause = "Lung Lesion/Mass"
            independent = False
            evidence.append("감별: 고신뢰 Lung Lesion/Mass에 의한 음영 (2차)")
            location = lesion.get("location", location)
        else:
            primary_cause = "Nonspecific"
            evidence.append("비특이적 음영, 추가 평가 필요")
    else:
        primary_cause = "Nonspecific"
        evidence.append("다른 Rule 결과 없음 — 비특이적 음영")

    severity = "moderate" if d.Lung_Opacity > 0.7 else "mild"

    # ── confidence 할당 ──
    if independent:
        confidence = "medium" if d.Lung_Opacity > 0.60 else "low"
    else:
        confidence = "low"

    return {
        "finding": "Lung_Opacity",
        "detected": detected,
        "confidence": confidence,
        "evidence": evidence,
        "quantitative": {
            "primary_cause": primary_cause,
            "lobe": location,
            "densenet_prob": round(d.Lung_Opacity, 4),
            "independent": independent,
        },
        "location": location,
        "severity": severity,
        "recommendation": "CT 확인 권장" if primary_cause == "Nonspecific" else None,
        "alert": alert,
    }
