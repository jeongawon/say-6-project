"""소견 없음 (No Finding) — 전체 체크리스트 통과 판정.
모든 Rule이 실행된 후 마지막에 호출.
"""

from ..models import ClinicalLogicInput
from ..thresholds import get_threshold, LUNG_RATIO_NORMAL_MIN, LUNG_RATIO_NORMAL_MAX


def analyze(input: ClinicalLogicInput, other_results: dict = None) -> dict:
    a = input.anatomy
    d = input.densenet

    evidence = []

    # 8영역 + YOLO 체크리스트
    checklist = {
        "heart": a.ctr < 0.50,
        "mediastinum": a.mediastinum_status in (None, "normal"),
        "trachea": a.trachea_midline in (None, True),
        "pleura_right": a.right_cp_status in (None, "sharp"),
        "pleura_left": a.left_cp_status in (None, "sharp"),
        "diaphragm": a.diaphragm_status in (None, "normal"),
        # 좌/우 폐 면적비: 해부학적으로 좌폐가 약간 작으므로 1.15까지 정상 허용
        "lung_ratio": LUNG_RATIO_NORMAL_MIN <= a.lung_area_ratio <= LUNG_RATIO_NORMAL_MAX if a.lung_area_ratio else True,
        "yolo_clear": len(input.yolo_detections) == 0,
    }

    # DenseNet 13개 질환 전부 threshold 이하인지 확인
    densenet_clear = True
    finding_names = [
        "Atelectasis", "Cardiomegaly", "Consolidation", "Edema",
        "Enlarged_Cardiomediastinum", "Fracture", "Lung_Lesion", "Lung_Opacity",
        "Pleural_Effusion", "Pleural_Other", "Pneumonia",
        "Pneumothorax", "Support_Devices",
    ]
    for name in finding_names:
        prob = getattr(d, name, 0.0)
        thresh = get_threshold(name)
        if prob > thresh:
            densenet_clear = False
            break
    checklist["lungs_densenet"] = densenet_clear

    # other_results에서 detected된 항목이 있으면 No Finding 아님
    if other_results:
        any_detected = any(
            r.get("detected", False)
            for key, r in other_results.items()
            if key != "No_Finding"
        )
        checklist["no_other_findings"] = not any_detected
    else:
        checklist["no_other_findings"] = True

    passed = sum(1 for v in checklist.values() if v)
    failed = sum(1 for v in checklist.values() if not v)
    all_passed = all(checklist.values())

    # confidence 세분화
    confidence = "high"

    if all_passed:
        detected = True  # = 정상

        # CTR < 0.50 AND YOLO 없음 AND DenseNet 정상 → 강한 정상 판정
        if a.ctr < 0.50 and len(input.yolo_detections) == 0 and densenet_clear:
            evidence.append(f"전체 정상 — {passed}개 체크 항목 모두 통과 (CTR {a.ctr:.4f}, YOLO 0건, DenseNet 정상)")
            confidence = "high"
        else:
            evidence.append(f"전체 정상 — {passed}개 체크 항목 모두 통과")

        # 경계선 소견 체크 — threshold 이하이지만 근접한 값
        borderline_notes = []
        if 0.45 <= a.ctr < 0.50:
            borderline_notes.append(f"CTR {a.ctr:.4f} (경계선)")
        for name in finding_names:
            prob = getattr(d, name, 0.0)
            thresh = get_threshold(name)
            if prob > thresh * 0.7 and prob <= thresh:
                borderline_notes.append(f"{name} {prob:.2f}/{thresh:.2f}")
        if borderline_notes:
            evidence.append(f"경계선 소견 있으나 정상 범위 내: {', '.join(borderline_notes)}")
            confidence = "medium"
    else:
        detected = False
        failed_items = [k for k, v in checklist.items() if not v]
        evidence.append(f"{failed}개 항목 실패: {', '.join(failed_items)}")

    return {
        "finding": "No_Finding",
        "detected": detected,
        "confidence": confidence,
        "evidence": evidence,
        "quantitative": {
            "checklist": checklist,
            "passed": passed,
            "failed": failed,
        },
        "location": None,
        "severity": None,
        "recommendation": None,
        "alert": False,
    }
