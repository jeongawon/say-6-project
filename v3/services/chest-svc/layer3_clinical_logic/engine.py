"""
Layer 3 Clinical Logic Engine — 메인 오케스트레이터.
14개 질환 Rule 순차 실행 + 교차 검증 + 감별 진단 + 위험도 분류.

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
from .differential import deduplicate_differentials
from .pertinent_negatives import get_pertinent_negatives

import inspect


def _call_analyze(module, input, other_results=None):
    """Rule의 analyze()가 other_results 파라미터를 지원하면 전달, 아니면 생략."""
    sig = inspect.signature(module.analyze)
    if "other_results" in sig.parameters and other_results is not None:
        return module.analyze(input, other_results=other_results)
    return module.analyze(input)


def run_clinical_logic(input: ClinicalLogicInput) -> dict:
    """
    14개 질환 전부 실행 + 교차 검증 + 감별 진단.

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
    results = {}

    # ================================================================
    # Phase 1: 독립 Rule (다른 질환 결과에 의존하지 않는 단독 분석)
    # ================================================================
    phase1_rules = [
        ("Cardiomegaly", cardiomegaly),
        ("Pleural_Effusion", pleural_effusion),
        ("Pneumothorax", pneumothorax),
        ("Atelectasis", atelectasis),
        ("Fracture", fracture),
        ("Support_Devices", support_devices),
        ("Lung_Lesion", lung_lesion),
    ]
    for name, module in phase1_rules:
        results[name] = module.analyze(input)

    # ================================================================
    # Phase 2: 교차 의존 Rule (Phase 1 결과를 참조할 수 있음)
    #   - Enlarged_Cardiomediastinum: Cardiomegaly 결과 참조
    #   - Consolidation: 독립이지만 Phase 3에서 참조되므로 여기 배치
    #   - Edema: Atelectasis 결과 참조
    #   - Pleural_Other: 다른 흉막 소견 참조 가능
    # ================================================================
    phase2_rules = [
        ("Enlarged_Cardiomediastinum", enlarged_cm),
        ("Consolidation", consolidation),
        ("Edema", edema),
        ("Pleural_Other", pleural_other),
    ]
    for name, module in phase2_rules:
        results[name] = _call_analyze(module, input, other_results=results)

    # ================================================================
    # Phase 3: 집계 Rule (Phase 1+2 결과를 종합하여 최종 판정)
    #   - Lung_Opacity: Consolidation, Edema 결과 필요
    #   - Pneumonia: Consolidation + 임상정보 필요
    #   - No_Finding: 전체 결과 확인 후 정상 판정
    # ================================================================
    results["Lung_Opacity"] = _call_analyze(lung_opacity, input, other_results=results)
    results["Pneumonia"] = _call_analyze(pneumonia, input, other_results=results)
    results["No_Finding"] = _call_analyze(no_finding, input, other_results=results)

    # ================================================================
    # Step 4: 교차 검증 (DenseNet + YOLO + Rule 결과 일치 확인)
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
    # Step 5: 감별 진단
    # ================================================================
    diff = differential.analyze(results, input)
    # 중복 감별진단 제거 (같은 질환 그룹에서 첫 번째만 유지)
    diff = deduplicate_differentials(diff)

    # ================================================================
    # Step 6: 위험도 분류 (3단계)
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

    # ================================================================
    # Step 7: Pertinent Negatives (주소 기반 감별 필수 음성 소견)
    # ================================================================
    chief_complaint = None
    if input.patient_info:
        chief_complaint = input.patient_info.chief_complaint
    pertinent_neg = get_pertinent_negatives(chief_complaint, results)

    return {
        "findings": results,
        "cross_validation": cross_val,
        "differential_diagnosis": diff,
        "risk_level": risk_level,
        "alert_flags": [r["finding"] for r in alert_findings],
        "detected_count": detected_count,
        "pertinent_negatives": pertinent_neg,
    }
