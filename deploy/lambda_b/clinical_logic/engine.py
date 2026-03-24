"""
Layer 3 Clinical Logic Engine — 메인 오케스트레이터
14개 질환 Rule 순차 실행 + 교차 검증 + 감별 진단 + 위험도 분류

사용법:
    from layer3_clinical_logic.engine import run_clinical_logic
    from layer3_clinical_logic.models import ClinicalLogicInput

    result = run_clinical_logic(input)
"""

from .models import ClinicalLogicInput
from .rules import (
    cardiomegaly,
    pleural_effusion,
    pneumothorax,
    atelectasis,
    consolidation,
    edema,
    enlarged_cm,
    fracture,
    lung_lesion,
    pleural_other,
    support_devices,
    lung_opacity,
    pneumonia,
    no_finding,
)
from .cross_validation import cross_validate
from . import differential


def run_clinical_logic(input: ClinicalLogicInput) -> dict:
    """
    14개 질환 전부 실행 + 교차 검증 + 감별 진단

    Args:
        input: ClinicalLogicInput (Layer 1/2 결과 + 환자정보)

    Returns:
        dict: {
            findings: {질환명: result_dict, ...},
            cross_validation: {질환명: cv_dict, ...},
            differential_diagnosis: [matched patterns],
            risk_level: "critical" | "urgent" | "routine",
            alert_flags: [알림 질환명 목록],
            detected_count: int,
        }
    """
    # ================================================================
    # Phase 1: 14개 질환별 Rule 실행 (순서 중요!)
    # ================================================================
    results = {}

    # 독립 실행 가능한 Rule들 (다른 결과에 의존하지 않음)
    results["Cardiomegaly"] = cardiomegaly.analyze(input)
    results["Pleural_Effusion"] = pleural_effusion.analyze(input)
    results["Pneumothorax"] = pneumothorax.analyze(input)
    results["Atelectasis"] = atelectasis.analyze(input)
    results["Consolidation"] = consolidation.analyze(input)
    results["Edema"] = edema.analyze(input)
    results["Enlarged_Cardiomediastinum"] = enlarged_cm.analyze(input)
    results["Fracture"] = fracture.analyze(input)
    results["Lung_Lesion"] = lung_lesion.analyze(input)
    results["Pleural_Other"] = pleural_other.analyze(input)
    results["Support_Devices"] = support_devices.analyze(input)

    # Lung Opacity: 다른 결과에 의존 → 나중에 실행
    results["Lung_Opacity"] = lung_opacity.analyze(input, other_results=results)

    # Pneumonia: 임상정보 + 다른 결과에 의존 → 가장 나중에
    results["Pneumonia"] = pneumonia.analyze(input, other_results=results)

    # No Finding: 전체 결과 확인 후 판정
    results["No_Finding"] = no_finding.analyze(input, other_results=results)

    # ================================================================
    # Phase 2: 교차 검증
    # ================================================================
    cross_val = {}
    for finding_name, result in results.items():
        if finding_name == "No_Finding":
            continue
        densenet_prob = getattr(input.densenet, finding_name, 0.0)
        yolo_detected = any(
            d.class_name == finding_name for d in input.yolo_detections
        )
        logic_detected = result["detected"]
        cross_val[finding_name] = cross_validate(
            finding_name, densenet_prob, yolo_detected, logic_detected
        )

    # ================================================================
    # Phase 3: 감별 진단
    # ================================================================
    diff = differential.analyze(results, input)

    # ================================================================
    # Phase 4: 위험도 분류 (3단계)
    #   CRITICAL — alert=True (긴장성 기흉, ETT 이탈 등)
    #   URGENT   — severity "severe"인 소견 2개 이상
    #   ROUTINE  — 그 외
    # ================================================================
    alert_findings = [r for r in results.values() if r.get("alert")]
    severe_count = sum(
        1 for r in results.values()
        if r.get("severity") == "severe" and r.get("detected")
    )

    if alert_findings:
        risk_level = "critical"
    elif severe_count >= 2:
        risk_level = "urgent"
    else:
        risk_level = "routine"

    detected_count = sum(
        1 for name, r in results.items()
        if r["detected"] and name != "No_Finding"
    )

    return {
        "findings": results,
        "cross_validation": cross_val,
        "differential_diagnosis": diff,
        "risk_level": risk_level,
        "alert_flags": [r["finding"] for r in alert_findings],
        "detected_count": detected_count,
    }
