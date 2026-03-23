"""
공통 설정 — S3 경로, 라벨, 모델 설정 등
전체 파이프라인에서 공유하는 상수값
"""

# ============================================================
# AWS / S3
# ============================================================
AWS_REGION = "ap-northeast-2"
S3_BUCKET = "pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an"

# S3 경로
S3_DATA_PREFIX = "data/p10_pa"
S3_CSV_KEY = "preprocessing/p10_train_ready_resplit.csv"
S3_CODE_PREFIX = "code"
S3_OUTPUT_PREFIX = "output"
S3_CHECKPOINT_PREFIX = "checkpoints"

# ============================================================
# 14개 CheXpert 질환 라벨
# ============================================================
LABEL_COLS = [
    'Atelectasis', 'Cardiomegaly', 'Consolidation', 'Edema',
    'Enlarged Cardiomediastinum', 'Fracture', 'Lung Lesion', 'Lung Opacity',
    'No Finding', 'Pleural Effusion', 'Pleural Other', 'Pneumonia',
    'Pneumothorax', 'Support Devices'
]
NUM_CLASSES = len(LABEL_COLS)

# ============================================================
# 모델 설정
# ============================================================
# DenseNet-121
DENSENET_IMAGE_SIZE = 224
DENSENET_IMAGENET_MEAN = [0.485, 0.456, 0.406]
DENSENET_IMAGENET_STD = [0.229, 0.224, 0.225]
DENSENET_TRAINING_JOB = "densenet121-mimic-cxr-v1"
DENSENET_MODEL_S3_KEY = f"{S3_OUTPUT_PREFIX}/{DENSENET_TRAINING_JOB}/output/model.tar.gz"

# YOLOv8 (예정)
YOLO_IMAGE_SIZE = 640
YOLO_CLASSES = 22  # VinDr-CXR 22개 local label

# Segmentation — HuggingFace 사전학습 모델
# ianpan/chest-x-ray-basic (EfficientNetV2-S + U-Net, CheXmask 33.5만장)
# Dice: Right Lung 0.957, Left Lung 0.948, Heart 0.943
SEGMENTATION_HF_MODEL = "ianpan/chest-x-ray-basic"
SEGMENTATION_MASK_CLASSES = {0: "background", 1: "right_lung", 2: "left_lung", 3: "heart"}

# ============================================================
# Clinical Logic 임계값
# ============================================================
CTR_THRESHOLD = 0.50          # Cardiomegaly
CTR_SEVERE_THRESHOLD = 0.60   # Severe Cardiomegaly
MEDIASTINUM_WIDTH_THRESHOLD = 8.0  # cm, Enlarged Cardiomediastinum
PNEUMOTHORAX_LARGE_THRESHOLD = 2.0  # cm, Large Pneumothorax
LUNG_AREA_RATIO_NORMAL = (0.85, 0.95)  # 좌/우 폐 면적 비율 정상 범위
PLEURAL_THICKENING_THRESHOLD = 3.0  # mm
NODULE_MASS_THRESHOLD = 30.0  # mm, 결절 vs 종괴 경계

# Fleischner Society 가이드라인 (mm)
FLEISCHNER_NO_FOLLOWUP = 6.0
FLEISCHNER_CT_FOLLOWUP = 8.0
FLEISCHNER_IMMEDIATE_CT = 30.0
