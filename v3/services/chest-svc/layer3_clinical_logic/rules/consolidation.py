"""경화 (Consolidation) — Silhouette sign + 폐엽 매핑"""

from ..models import ClinicalLogicInput
from ..thresholds import (
    get_threshold,
    CONSOLIDATION_HIGH_CONF,
    LUNG_RATIO_CONSOLIDATION_LOW,
    LUNG_RATIO_CONSOLIDATION_HIGH,
)


def analyze(input: ClinicalLogicInput) -> dict:
    # ── confidence 판정 기준 (14개 Rule 공통) ──────────────────
    # "high"   — 2개 이상 독립 소스 일치 (CTR+DenseNet+YOLO 등)
    # "medium" — 1개 소스 양성 + 합리적 근거
    # "low"    — 1개 소스만 양성 + 근거 약함 (의사 확인 필요)
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

    # ── DenseNet 단독 양성 게이트 (AUC 0.682 보완) ──────────────
    # YOLO bbox 없이 DenseNet만 양성인 경우 추가 근거 최소 1개 요구
    if not yolo_consol and detected:
        supporting = []

        # (a) 임상 정보: 발열 >38.0°C 또는 기침
        if input.patient_info:
            pi = input.patient_info
            cc = (pi.chief_complaint or "").lower()
            has_fever = pi.temperature is not None and pi.temperature > 38.0
            has_cough = "기침" in cc or "cough" in cc
            if has_fever:
                supporting.append("발열 >38.0°C")
            if has_cough:
                supporting.append("기침 호소")

        # (b) DenseNet 고확률 (>CONSOLIDATION_HIGH_CONF) — AUC 0.682이므로 엄격한 기준
        if d.Consolidation > CONSOLIDATION_HIGH_CONF:
            supporting.append(f"DenseNet 고확률 {d.Consolidation:.2f}")

        # (c) 폐면적 비대칭 — 심비대/무기폐 비대칭(~1.3) 제외, 경화급 비대칭만
        ratio = a.lung_area_ratio
        if ratio < LUNG_RATIO_CONSOLIDATION_LOW or ratio > LUNG_RATIO_CONSOLIDATION_HIGH:
            supporting.append(f"폐면적 비대칭 ratio={ratio:.3f}")

        if not supporting:
            # 근거 없음 → 양성 철회
            detected = False
            evidence.append(
                f"DenseNet Consolidation {d.Consolidation:.2f} 양성이나 "
                f"추가 근거 없음 (AUC 0.682)"
            )
            return {
                "finding": "Consolidation",
                "detected": False,
                "confidence": "low",
                "evidence": evidence,
                "quantitative": {
                    "densenet_prob": round(d.Consolidation, 4),
                },
                "location": None,
                "severity": None,
                "recommendation": None,
                "alert": False,
            }
        else:
            # 근거 있음 → 양성 유지하되 confidence 제한
            evidence.append(
                f"DenseNet 단독 양성 — 추가 근거: {', '.join(supporting)}"
            )

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

    # ── YOLO bbox 없이 DenseNet만 양성일 때 위치 추정 (폐 면적비 기반) ──
    if not yolo_consol and detected:
        ratio = a.lung_area_ratio  # left / right
        if ratio < 0.85:
            location = "좌측 (폐 면적비 기반 추정)"
            evidence.append(f"YOLO bbox 없음 — 좌/우 면적비 {ratio:.3f} → 좌측 경화 추정")
        elif ratio > 1.20:
            location = "우측 (폐 면적비 기반 추정)"
            evidence.append(f"YOLO bbox 없음 — 좌/우 면적비 {ratio:.3f} → 우측 경화 추정")
        else:
            location = "indeterminate"
            evidence.append(
                f"YOLO bbox 없음 — 좌/우 면적비 {ratio:.3f} → 위치 불확정, CT 확인 권장"
            )

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
        severity = "moderate" if d.Consolidation > CONSOLIDATION_HIGH_CONF else "mild"

    # 임상정보 교차 — 발열+기침 동반 시 감염성 가능성
    recommendation = None
    if input.patient_info:
        pi = input.patient_info
        cc = (pi.chief_complaint or "").lower()
        has_fever = pi.temperature and pi.temperature > 38.0
        has_cough = "기침" in cc or "cough" in cc or "가래" in cc
        if has_fever and has_cough:
            evidence.append("발열+기침 동반 → 감염성 경화(폐렴) 가능성 높음")
            recommendation = "객담 배양 + 항생제 치료 고려"
        elif has_fever:
            evidence.append("발열 동반 → 감염 가능성")

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
        "recommendation": recommendation,
        "alert": alert,
    }
