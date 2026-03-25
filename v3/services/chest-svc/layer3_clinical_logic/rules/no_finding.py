"""소견 없음 (No Finding) — 전체 체크리스트 통과 판정.
모든 Rule이 실행된 후 마지막에 호출.
"""

from ..models import ClinicalLogicInput
from ..thresholds import get_threshold


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
        "lung_ratio": 0.80 <= a.lung_area_ratio <= 1.05 if a.lung_area_ratio else True,
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

    if all_passed:
        detected = True  # = 정상
        evidence.append(f"전체 정상 — {passed}개 체크 항목 모두 통과")
    else:
        detected = False
        failed_items = [k for k, v in checklist.items() if not v]
        evidence.append(f"{failed}개 항목 실패: {', '.join(failed_items)}")

    return {
        "finding": "No_Finding",
        "detected": detected,
        "confidence": "high",
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
