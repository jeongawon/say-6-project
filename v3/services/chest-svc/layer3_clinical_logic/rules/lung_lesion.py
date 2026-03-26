"""폐 병변/결절 (Lung Lesion) — 크기 분류 + Fleischner Society 추천"""

from ..models import ClinicalLogicInput
from ..thresholds import (
    get_threshold,
    px_to_mm,
    FLEISCHNER_NO_FOLLOWUP,
    FLEISCHNER_CT_FOLLOWUP,
    FLEISCHNER_MASS,
)

# 하위 호환 별칭 — 기존 코드에서 FLEISCHNER_MASS_THRESHOLD 참조 대비
FLEISCHNER_MASS_THRESHOLD = FLEISCHNER_MASS


def analyze(input: ClinicalLogicInput) -> dict:
    # ── confidence 판정 기준 (14개 Rule 공통) ──────────────────
    # "high"   — 2개 이상 독립 소스 일치 (CTR+DenseNet+YOLO 등)
    # "medium" — 1개 소스 양성 + 합리적 근거
    # "low"    — 1개 소스만 양성 + 근거 약함 (의사 확인 필요)
    a = input.anatomy
    d = input.densenet
    threshold = get_threshold("Lung_Lesion")

    detected = False
    evidence = []
    severity = None
    location = None
    alert = False
    recommendation = None

    # DenseNet
    if d.Lung_Lesion > threshold:
        detected = True
        evidence.append(f"DenseNet Lung_Lesion: {d.Lung_Lesion:.2f}")

    # YOLO bbox (Nodule_Mass 류)
    yolo_lesion = [det for det in input.yolo_detections
                   if det.class_name in ("Nodule_Mass", "Nodule", "Mass", "Lung_Lesion", "Nodule/Mass")]
    if yolo_lesion:
        detected = True

    if not detected:
        evidence.append("폐 병변/결절 소견 없음")
        return {
            "finding": "Lung_Lesion",
            "detected": False,
            "confidence": "high",
            "evidence": evidence,
            "quantitative": {},
            "location": None,
            "severity": None,
            "recommendation": None,
            "alert": False,
        }

    lesion_count = len(yolo_lesion)
    lesion_type = None
    size_mm = None
    lobe = None

    if yolo_lesion:
        det = yolo_lesion[0]
        bbox = det.bbox
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        long_axis_px = max(w, h)
        size_mm = px_to_mm(long_axis_px)

        # 크기 분류
        if size_mm >= FLEISCHNER_MASS_THRESHOLD:
            lesion_type = "mass"
            recommendation = "종괴, 즉시 조직검사 권장"
            severity = "severe"
            alert = True
        elif size_mm >= FLEISCHNER_CT_FOLLOWUP:
            lesion_type = "nodule"
            recommendation = "즉시 CT 또는 PET-CT"
            severity = "moderate"
        elif size_mm >= FLEISCHNER_NO_FOLLOWUP:
            lesion_type = "nodule"
            recommendation = "6~12개월 CT 추적"
            severity = "mild"
        else:
            lesion_type = "nodule"
            recommendation = "추적 불필요 (저위험)"
            severity = "mild"

        evidence.append(f"{lesion_type} {size_mm}mm (Fleischner: {recommendation})")

        # 폐엽 매핑
        if det.lobe:
            lobe = det.lobe
        else:
            bbox_cx = (bbox[0] + bbox[2]) / 2
            img_cx = a.thorax_width_px / 2 if a.thorax_width_px > 0 else 256
            side = "R" if bbox_cx < img_cx else "L"
            bbox_cy = (bbox[1] + bbox[3]) / 2
            img_h = a.thorax_width_px if a.thorax_width_px > 0 else 512
            if bbox_cy < img_h * 0.4:
                lobe = f"{side}UL"
            else:
                lobe = f"{side}LL"

        lobe_names = {
            "RUL": "우상엽", "RML": "우중엽", "RLL": "우하엽",
            "LUL": "좌상엽", "LLL": "좌하엽",
        }
        location = lobe_names.get(lobe, lobe)
        evidence.append(f"위치: {location}")

        if lesion_count > 1:
            evidence.append(f"다발성 결절 ({lesion_count}개)")
    else:
        severity = "mild"
        recommendation = "CT 확인 권장"

    confidence = "high" if yolo_lesion and d.Lung_Lesion > threshold else "medium"

    return {
        "finding": "Lung_Lesion",
        "detected": detected,
        "confidence": confidence,
        "evidence": evidence,
        "quantitative": {
            "lobe": lobe,
            "size_mm": size_mm,
            "type": lesion_type,
            "count": lesion_count if lesion_count else 0,
        },
        "location": location,
        "severity": severity,
        "recommendation": recommendation,
        "alert": alert,
    }
