"""
질환별 DenseNet threshold — 문헌 기반 최적 threshold.
기존 pos_weight 기반 threshold에서 임상 문헌 기반으로 재조정.

근거:
- 심혈관 질환: CTR 해부학 교차검증이 가능하므로 높은 threshold 적용
- 흉막 질환 (특히 기흉): 놓치면 치명적이므로 낮은 threshold 유지
- 폐실질 질환: 중간 수준 threshold (0.55)
- 골절: CXR 민감도가 30-50%로 낮아 높은 threshold 적용
- Support Devices: 대부분 명확한 소견이므로 낮은 threshold

# TODO: Youden's J (= sensitivity + specificity - 1) 기반 threshold 검증 필요.
#       CheXpert/MIMIC-CXR validation set에서 ROC 분석 후
#       각 질환별 Youden's J 최적점과 비교하여 최종 threshold 확정할 것.
"""

# 질환별 DenseNet 확률 threshold (양성 판정 기준) — 문헌 기반 최적값
OPTIMAL_THRESHOLDS = {
    # === 심혈관 (CTR 교차검증 가능 → 높은 threshold OK) ===
    "Cardiomegaly": 0.60,                  # CTR로 독립 확인 가능
    "Enlarged_Cardiomediastinum": 0.55,     # 종격동 비율로 교차검증

    # === 흉막 (놓치면 위험 → 낮은 threshold) ===
    "Pleural_Effusion": 0.50,              # CP angle blunting으로 교차검증
    "Pneumothorax": 0.35,                  # 놓치면 치명적 → 민감도 우선
    "Pleural_Other": 0.60,                 # 기존 0.25는 과탐지 (false positive 과다)

    # === 폐실질 ===
    "Atelectasis": 0.55,                   # 폐 면적비로 교차검증 가능
    "Consolidation": 0.55,                 # YOLO bbox와 교차검증
    "Edema": 0.55,                         # 임상정보(SpO2, BNP)와 교차검증
    "Lung_Opacity": 0.55,                  # 다른 폐실질 소견과 중복 가능
    "Pneumonia": 0.55,                     # 임상정보(발열, WBC)와 교차검증

    # === 기타 ===
    "Fracture": 0.65,                      # CXR 민감도 30-50% → 높은 threshold
    "Lung_Lesion": 0.60,                   # YOLO bbox와 교차검증
    "Support_Devices": 0.45,               # 대부분 명확한 소견
    "No_Finding": 0.50,                    # 기본값 유지
}

# 하위 호환: 기존 코드에서 DENSENET_THRESHOLDS 참조하는 경우 대비
DENSENET_THRESHOLDS = OPTIMAL_THRESHOLDS


def get_threshold(finding: str) -> float:
    """질환별 threshold 반환, 없으면 기본 0.5"""
    return OPTIMAL_THRESHOLDS.get(finding, 0.5)
