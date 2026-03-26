"""
교차 검증 (Cross-Validation).
DenseNet vs YOLO vs Clinical Logic 3중 소스 일치 확인.
"""

from .thresholds import get_threshold


def cross_validate(
    finding: str,
    densenet_prob: float,
    yolo_detected: bool,
    logic_detected: bool,
    densenet_threshold: float = None,
) -> dict:
    """
    3개 소스의 일치도를 확인하여 confidence 결정.

    Args:
        finding: 질환명
        densenet_prob: DenseNet 확률
        yolo_detected: YOLO에서 탐지 여부
        logic_detected: Clinical Logic Rule 판정 결과
        densenet_threshold: DenseNet threshold (None이면 질환별 기본값)

    Returns:
        dict: {finding, sources, agreement, confidence, flag}
    """
    if densenet_threshold is None:
        densenet_threshold = get_threshold(finding)

    sources = {
        "densenet": densenet_prob > densenet_threshold,
        "yolo": yolo_detected,
        "clinical_logic": logic_detected,
    }

    agreement_count = sum(sources.values())
    flag = None

    if agreement_count == 3:
        confidence = "high"
    elif agreement_count == 2:
        confidence = "medium"
    elif agreement_count == 1:
        confidence = "low"
        flag = "의사 확인 필요 — 1개 소스만 양성"
    else:
        confidence = "none"

    # 임상적으로 중요한 질환에서 2/3 양성이면 override 제안
    CRITICAL_FINDINGS = {"Pneumothorax", "Cardiomegaly", "Pleural_Effusion"}
    if finding in CRITICAL_FINDINGS and agreement_count == 2 and not logic_detected:
        flag = f"⚠️ 2/3 양성 (clinical_logic만 음성) — Rule 재검토 권장"
    elif finding in CRITICAL_FINDINGS and agreement_count == 2 and logic_detected:
        flag = None  # 2/3 including logic = OK

    return {
        "finding": finding,
        "sources": sources,
        "agreement": f"{agreement_count}/3",
        "confidence": confidence,
        "flag": flag,
    }
