"""기흉 (Pneumothorax) — 폐 경계~흉벽 거리 + Tension 판정"""

from ..models import ClinicalLogicInput
from ..thresholds import get_threshold, PTX_LARGE, PTX_MODERATE


def analyze(input: ClinicalLogicInput, other_results: dict = None) -> dict:
    # ── confidence 판정 기준 (14개 Rule 공통) ──────────────────
    # "high"   — 2개 이상 독립 소스 일치 (CTR+DenseNet+YOLO 등)
    # "medium" — 1개 소스 양성 + 합리적 근거
    # "low"    — 1개 소스만 양성 + 근거 약함 (의사 확인 필요)
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

    # 세그멘테이션 정량 지표 기반 보조 검출
    # 폐면적 급감(ratio < 0.60 or > 1.67) + 종격동 편위 = PTX 의심
    # 단, 심비대나 무기폐가 이미 양성이면 비대칭의 다른 원인이 있으므로 스킵
    if not detected:
        # 교차 배제: 심비대/무기폐에 의한 폐면적 비대칭은 기흉 근거에서 제외
        has_other_cause = False
        if other_results:
            cardio_detected = other_results.get("Cardiomegaly", {}).get("detected", False)
            atel_detected = other_results.get("Atelectasis", {}).get("detected", False)
            if cardio_detected or atel_detected:
                has_other_cause = True
                cause = []
                if cardio_detected: cause.append("심비대")
                if atel_detected: cause.append("무기폐")
                evidence.append(f"폐면적 비대칭 있으나 {'+'.join(cause)} 동반 → 기흉 근거에서 제외")

        if not has_other_cause:
            ratio = a.lung_area_ratio
            severe_asymmetry = (ratio < 0.60 or ratio > 1.67)
            trachea_shifted = (a.trachea_midline is not None and not a.trachea_midline)

            if severe_asymmetry and trachea_shifted:
                detected = True
                evidence.append(f"폐면적 비대칭 (좌/우 {ratio:.3f}) + 기관 편위 → 기흉 의심 (세그 기반)")
            elif severe_asymmetry and d.Pneumothorax > 0.20:
                detected = True
                evidence.append(f"폐면적 비대칭 (좌/우 {ratio:.3f}) + DenseNet {d.Pneumothorax:.2f} → 기흉 의심")

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
        evidence.append(f"우측 폐 면적 감소 (좌/우 비 {ratio:.3f})")
    else:
        location = "indeterminate"

    # 크기 판정
    if d.Pneumothorax > PTX_LARGE:
        size = "large"
        severity = "severe"
    elif d.Pneumothorax > PTX_MODERATE:
        size = "moderate"
        severity = "moderate"
    else:
        size = "small"
        severity = "mild"

    # Tension pneumothorax 판정
    if a.trachea_midline is not None and not a.trachea_midline:
        dev_dir = a.trachea_deviation_direction
        if (location == "left" and dev_dir == "right") or \
           (location == "right" and dev_dir == "left"):
            tension = True
            alert = True
            severity = "critical"
            evidence.append(
                f"기관 {dev_dir}측 편위 -> TENSION PNEUMOTHORAX 의심"
            )

    # 횡격막 하강 (동측) → tension 추가 근거
    if a.diaphragm_status is not None:
        if (location == "left" and a.diaphragm_status == "elevated_left") or \
           (location == "right" and a.diaphragm_status == "elevated_right"):
            evidence.append(f"동측 횡격막 하강 -> tension 추가 근거")
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
