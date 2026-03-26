"""
chest-svc 임계값 및 임상 상수 중앙 관리 (Single Source of Truth).
다른 파일에서 하드코딩하지 마세요. 여기서 import하세요.

변경 이력:
- 2026-03-25: 문헌 기반 초기값
- 2026-03-26: 601건 PA Youden's J 기반 최적화
- 2026-03-26: Rule 로직 수정 (Consolidation, Lung Opacity)
- 2026-03-26: 전체 magic number 통합 (Single Source of Truth)
"""

# ====================================================================
# 1. DenseNet thresholds (질환별 확률 양성 판정 기준)
#    근거: say1-pre-project-5 MIMIC-CXR p10 PA 601건 × CheXpert GT
#    - Youden's J 최적점 기반, GT 불충분 질환은 보수적 기본값
#    - AUC < 0.70: Youden 불안정 → 기본값 유지
#    - 응급 질환(PTX): 세그 보조 검출이 저확률 커버하므로 높은 임계값 허용
# ====================================================================
OPTIMAL_THRESHOLDS = {
    # === 심혈관 ===
    "Cardiomegaly": 0.55,                  # Youden 0.546, AUC 0.819 — CTR 보완이 FN 커버
    "Enlarged_Cardiomediastinum": 0.64,     # Youden 0.642, AUC 0.800

    # === 흉막 ===
    "Pleural_Effusion": 0.51,              # Youden 0.514, AUC 0.928 (최고 AUC)
    "Pneumothorax": 0.75,                  # Youden 0.746, AUC 0.895 — 세그 보조가 FN 커버
    "Pleural_Other": 0.70,                 # GT 불충분 (neg=1) → 보수적 상향 (FP 방지)

    # === 폐실질 ===
    "Atelectasis": 0.50,                   # GT 불충분 (neg=4) → 기본값
    "Consolidation": 0.55,                 # Youden 0.276 but U-Ones 왜곡 — 보수적 상향 (Rule 감별 의존)
    "Edema": 0.67,                         # Youden 0.671, AUC 0.847 — ↑ 과검출 해소
    "Lung_Opacity": 0.45,                  # AUC 0.634 (낮음) — Youden 불안정, 보수적 조정
    "Pneumonia": 0.52,                     # Youden 0.517, AUC 0.786

    # === 기타 ===
    "Fracture": 0.70,                      # Youden 0.395, AUC 0.857 — FP 방지 위해 보수적 상향
    "Lung_Lesion": 0.70,                   # GT 불충분 (neg=2) → 보수적 상향 (FP 방지)
    "Support_Devices": 0.68,               # Youden 0.681 — 높게 유지 (FP 방지)
    "No_Finding": 0.70,                    # GT 없음 (neg=0) → 기본값
}

# 하위 호환: 기존 코드에서 DENSENET_THRESHOLDS 참조하는 경우 대비
DENSENET_THRESHOLDS = OPTIMAL_THRESHOLDS

# DenseNet fallback threshold (알 수 없는 질환명)
DENSENET_DEFAULT_THRESHOLD = 0.5


def get_threshold(finding: str) -> float:
    """질환별 DenseNet threshold 반환, 없으면 기본 0.5."""
    return OPTIMAL_THRESHOLDS.get(finding, DENSENET_DEFAULT_THRESHOLD)


# 하위 호환 alias
get_densenet_threshold = get_threshold


# ====================================================================
# 2. YOLO confidence thresholds (클래스별 최소 confidence)
#    임상적 중요도에 따라 차등 적용
# ====================================================================
YOLO_CONF_THRESHOLDS = {
    "Pneumothorax": 0.15,       # 긴장성 기흉 → 놓치면 치명적
    "Pleural_effusion": 0.20,   # 흉막삼출 → 비교적 흔하고 중요
}
YOLO_DEFAULT_CONF = 0.25            # 나머지 클래스 기본값
YOLO_IOU_THRESHOLD = 0.45           # NMS IoU threshold
YOLO_INPUT_SIZE = 1024              # YOLOv8 정사각 입력 크기


def get_yolo_threshold(class_name: str) -> float:
    """YOLO 클래스별 confidence threshold 반환."""
    return YOLO_CONF_THRESHOLDS.get(class_name, YOLO_DEFAULT_CONF)


# ====================================================================
# 3. CTR (Cardiothoracic Ratio) 상수
#    Source: cardiomegaly.py, pleural_effusion.py, edema.py,
#            no_finding.py, pneumonia.py, differential.py
# ====================================================================
CTR_NORMAL_UPPER = 0.50          # 정상 상한 (>0.50 = 심비대)
CTR_MODERATE = 0.55              # moderate cardiomegaly
CTR_SEVERE = 0.60                # severe cardiomegaly
CTR_BORDERLINE_LOWER = 0.45      # no_finding 경계선 하한 (0.45~0.50 = 경계선)

# YOLO 후처리: Cardiomegaly 보충 탐지 CTR 기준 (yolo_postprocess.py)
CTR_SUPPLEMENT_PA = 0.53         # PA 뷰 보충 기준
CTR_SUPPLEMENT_AP = 0.55         # AP 뷰 보충 기준 (+0.02 보정)


# ====================================================================
# 4. CP angle (costophrenic angle) 흉수량 추정 상수
#    Source: pleural_effusion.py
# ====================================================================
CP_ANGLE_SMALL = 90              # ≤90° → small (~200-300mL)
CP_ANGLE_MODERATE = 120          # ≤120° → moderate (~500mL)
                                 # >120° → large (>1000mL)

# CP angle blunted/normal 판정 (model.py _cp_struct)
CP_ANGLE_BLUNTED_THRESHOLD = 30  # <30° = blunted (흉수 의심), ≥30° = normal


# ====================================================================
# 5. Lung area ratio 범위 (좌/우 폐 면적비)
#    Source: atelectasis.py, pneumothorax.py, consolidation.py,
#            no_finding.py, differential.py, edema.py
# ====================================================================

# 무기폐 (Atelectasis) — 폐 면적 감소 판정
LUNG_RATIO_ATELECTASIS_LOW = 0.80    # <0.80 → 좌폐 면적 감소
LUNG_RATIO_ATELECTASIS_HIGH = 1.25   # >1.25 → 우폐 면적 감소
ATEL_SEVERITY_MODERATE_PCT = 25      # >25% 면적 감소 = moderate
ATEL_SEVERITY_SEVERE_PCT = 40        # >40% 면적 감소 = severe

# 기흉 (Pneumothorax) — 세그 기반 비대칭 탐지
PTX_RATIO_SEVERE_LOW = 0.60          # <0.60 → 심한 좌측 비대칭
PTX_RATIO_SEVERE_HIGH = 1.67         # >1.67 → 심한 우측 비대칭 (1/0.60)
PTX_RATIO_LOCATION_LEFT = 0.70       # <0.70 → 좌측 기흉 추정
PTX_RATIO_LOCATION_RIGHT = 1.30      # >1.30 → 우측 기흉 추정
PTX_DENSENET_SEG_SUPPORT = 0.20      # 비대칭 + DenseNet > 0.20 → 기흉 의심

# 경화 (Consolidation) — DenseNet 단독 양성 게이트 보조 근거
LUNG_RATIO_CONSOLIDATION_LOW = 0.70  # <0.70 → 좌측 경화 추정 (gate 보조)
LUNG_RATIO_CONSOLIDATION_HIGH = 1.40 # >1.40 → 우측 경화 추정 (AUC 0.682 보상)
CONSOL_LOCATION_LEFT = 0.85          # <0.85 → 좌측 경화 추정 (위치)
CONSOL_LOCATION_RIGHT = 1.20         # >1.20 → 우측 경화 추정 (위치)

# No Finding — 정상 폐 면적비 범위
LUNG_RATIO_NORMAL_MIN = 0.85         # 해부학적으로 좌폐가 약간 작음
LUNG_RATIO_NORMAL_MAX = 1.15         # 1.15까지 정상 허용

# 부종 (Edema) — 대칭성 판정
EDEMA_SYMMETRY = 0.85                # symmetry_score > 0.85 → 양측 대칭


# ====================================================================
# 6. Mediastinum ratio (종격동/흉곽 비율)
#    Source: enlarged_cm.py
# ====================================================================
MEDIASTINUM_RATIO = 0.33             # >0.33 → 종격동 확대


# ====================================================================
# 7. Pneumothorax severity (DenseNet 확률 기반 크기 판정)
#    Source: pneumothorax.py
# ====================================================================
PTX_LARGE = 0.80                     # >0.80 → large (severe)
PTX_MODERATE = 0.60                  # >0.60 → moderate
                                     # ≤0.60 → small (mild)


# ====================================================================
# 8. Edema 상수
#    Source: edema.py
# ====================================================================
EDEMA_BILATERAL_DENSENET = 0.70      # DenseNet >0.70 + 무기폐 동반 → bilateral 추정
EDEMA_BUTTERFLY = 0.75               # DenseNet >0.75 → butterfly 패턴 의심
EDEMA_SEVERITY_SEVERE = 0.80         # >0.80 → severe
EDEMA_SEVERITY_MODERATE = 0.60       # >0.60 → moderate, ≤0.60 → mild

# SpO2 기준 (edema.py)
SPO2_SEVERE_HYPOXIA = 92            # <92% → 저산소증 동반
SPO2_MILD_HYPOXIA = 95              # <95% → 경미한 저산소증


# ====================================================================
# 9. Fleischner Society 가이드라인 (폐 결절 크기 기준, mm)
#    Source: lung_lesion.py
# ====================================================================
FLEISCHNER_NO_FOLLOWUP = 6.0         # <6mm → 추적 불필요 (저위험)
FLEISCHNER_CT_FOLLOWUP = 8.0         # 6~8mm → 6~12개월 CT 추적
FLEISCHNER_MASS = 30.0               # ≥30mm → 종괴, 즉시 조직검사


# ====================================================================
# 10. px ↔ mm/cm 환산 상수 및 함수
#     Source: lung_lesion.py, support_devices.py
# ====================================================================
_PX_TO_MM_FALLBACK = 0.14           # PA CXR 표준: ~0.14mm/px @ 3000x3000
_PX_TO_CM_FALLBACK = 0.014          # 0.14mm/px → 0.014cm/px (원본 크기 미상 시)

# CXR 표준 카세트 크기 (cm) — support_devices.py estimate_px_to_cm()
CXR_CASSETTE_WIDTH_CM = 35.0
CXR_CASSETTE_HEIGHT_CM = 43.0

# ETT 팁 위치 판정 (cm) — support_devices.py
ETT_TIP_TOO_DEEP_CM = 3.0           # <3cm → 너무 깊음 (우측 주기관지 삽입 위험)
ETT_TIP_TOO_SHALLOW_CM = 5.0        # >5cm → 너무 얕음 (발관 위험)
ETT_CARINA_Y_RATIO = 0.30           # carina 위치 추정: img_h * 0.30


def px_to_mm(px: float) -> float:
    """픽셀 → mm 근사 환산 (CXR 표준 0.14mm/px)."""
    return round(px * _PX_TO_MM_FALLBACK, 1)


def px_to_cm(px: float) -> float:
    """픽셀 → cm 근사 환산 (CXR 표준 0.014cm/px)."""
    return round(px * _PX_TO_CM_FALLBACK, 1)


# ====================================================================
# 11. YOLO edge margin (가장자리 FP 필터링)
#     Source: yolo_postprocess.py filter_edge_detections()
# ====================================================================
YOLO_EDGE_MARGIN = 0.10             # 가장자리 10% 이내 Other_lesion 제거

# YOLO bbox ↔ 세그멘테이션 마스크 IoU 보정 임계값
YOLO_SEG_IOU_THRESHOLD = 0.15       # IoU < 0.15 → 해부학적 보정 적용


# ====================================================================
# 12. Consolidation 고확률 임계값 (DenseNet 단독 양성 게이트)
#     Source: consolidation.py
# ====================================================================
CONSOLIDATION_HIGH_CONF = 0.70       # DenseNet >0.70 → 추가 근거 충분 (AUC 0.682 보상)

# Consolidation/Pneumonia 발열 기준
FEVER_THRESHOLD = 38.0               # >38.0°C → 발열


# ====================================================================
# 13. Enlarged Cardiomediastinum 보조 상수
#     Source: enlarged_cm.py
# ====================================================================
ECM_SEVERITY_THRESHOLD = 0.6        # DenseNet >0.6 → moderate, ≤0.6 → mild
ECM_INDEPENDENT_THRESHOLD = 0.75    # DenseNet >0.75 + 해부학적 확대 → 독립 소견


# ====================================================================
# 14. Lung Opacity 감별 상수
#     Source: lung_opacity.py
# ====================================================================
OPACITY_SEVERITY_THRESHOLD = 0.7     # DenseNet >0.7 → moderate, ≤0.7 → mild
OPACITY_INDEPENDENT_CONF = 0.60      # 독립 음영: >0.60 → medium, ≤0.60 → low


# ====================================================================
# 15. Cardiomegaly DenseNet 불일치 기준
#     Source: cardiomegaly.py
# ====================================================================
CARDIO_DENSENET_LOW = 0.3           # DenseNet <0.3 + CTR 양성 → confidence low (불일치)


# ====================================================================
# 16. Fracture 늑골 추정 y_ratio 범위
#     Source: fracture.py
# ====================================================================
FRACTURE_RIB_UPPER_RATIO = 0.25     # <0.25 → 제1~3늑골
FRACTURE_RIB_MIDDLE_RATIO = 0.50    # <0.50 → 제4~6늑골
                                    # ≥0.50 → 제7~10늑골


# ====================================================================
# 17. Consolidation/Lung Lesion 폐엽 매핑 y 비율
#     Source: consolidation.py, lung_lesion.py
# ====================================================================
LOBE_UPPER_Y_RATIO = 0.35           # consolidation: bbox_cy < thorax*0.35 → upper lobe
LOBE_UPPER_Y_RATIO_LESION = 0.4     # lung_lesion: bbox_cy < img_h*0.4 → upper lobe


# ====================================================================
# 18. Consolidation severity (area percent 기반)
#     Source: consolidation.py
# ====================================================================
CONSOL_AREA_SEVERE_PCT = 20         # >20% → severe
CONSOL_AREA_MODERATE_PCT = 10       # >10% → moderate, ≤10% → mild


# ====================================================================
# 19. 세그멘테이션 마스크 상수
#     Source: model.py
# ====================================================================
SEG_MASK_SIZE = 320                  # UNet 마스크 크기 (320x320)
SEG_TRACHEA_DEVIATION_PX = 10       # 320px 기준 10px 이상 편위 → 유의미
SEG_TRACHEA_ALERT_PX = 15           # 320px 기준 15px 이상 → 강한 편위 alert
SEG_DIAPHRAGM_DIFF_PX = 10          # 320px 기준 좌우 횡격막 높이차 10px → 비정상
SEG_HEART_CLIP_MARGIN = 5           # 320px 기준 Heart 횡격막 클리핑 여유 (~1.5%)
SEG_MEDIASTINUM_WIDE_PX = 80        # 320px 기준 종격동 폭 80px → widened (~25%)


# ====================================================================
# 20. Pneumonia 임상 기준
#     Source: pneumonia.py
# ====================================================================
TACHYPNEA_THRESHOLD = 20            # 호흡수 >20/min → 빈호흡
WBC_ELEVATED_THRESHOLD = 11000      # WBC >11000 → 상승
CRP_ELEVATED_THRESHOLD = 5.0        # CRP >5.0 → 상승


# ====================================================================
# 21. DenseNet (Layer 2) 상수
#     Source: densenet.py
# ====================================================================
DENSENET_INPUT_SIZE = (224, 224)     # H, W
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


# ====================================================================
# 22. 세그멘테이션 전처리 상수
#     Source: preprocessing.py
# ====================================================================
SEG_INPUT_SIZE = (320, 320)          # H, W


# ====================================================================
# 23. Risk level 분류 기준
#     Source: engine.py
# ====================================================================
RISK_SEVERE_COUNT_FOR_URGENT = 2     # severe 소견 2개 이상 → urgent
