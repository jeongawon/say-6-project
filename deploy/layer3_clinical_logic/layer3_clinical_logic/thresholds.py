"""
질환별 DenseNet threshold — pos_weight 기반 조정
희귀 질환(pos_weight 높음)은 낮은 threshold, 흔한 질환은 높은 threshold
"""

# 질환별 DenseNet 확률 threshold (양성 판정 기준)
DENSENET_THRESHOLDS = {
    "Atelectasis": 0.40,
    "Cardiomegaly": 0.50,
    "Consolidation": 0.45,
    "Edema": 0.45,
    "Enlarged_Cardiomediastinum": 0.35,
    "Fracture": 0.30,              # 희귀 (pos_weight 높음)
    "Lung_Lesion": 0.30,           # 희귀
    "Lung_Opacity": 0.45,
    "No_Finding": 0.50,
    "Pleural_Effusion": 0.45,
    "Pleural_Other": 0.25,         # 매우 희귀 (pos_weight 63.76)
    "Pneumonia": 0.40,
    "Pneumothorax": 0.35,
    "Support_Devices": 0.40,
}


def get_threshold(finding: str) -> float:
    """질환별 threshold 반환, 없으면 기본 0.5"""
    return DENSENET_THRESHOLDS.get(finding, 0.5)
