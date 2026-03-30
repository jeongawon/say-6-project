# Layer 2 YOLOv8 병변 탐지 계획서

> **Summary**: VinDr-CXR 데이터셋 기반 YOLOv8 흉부 X-Ray 바운딩 박스 병변 탐지 모델 구축
>
> **Project**: Dr. AI Radiologist (MIMIC-CXR)
> **Author**: hyunwoo
> **Date**: 2026-03-22
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | DenseNet-121은 "어떤 질환이 있는가"만 알려주고, "어디에 있는가"를 알 수 없음. 전문의 판독에는 병변 위치 특정이 필수 |
| **Solution** | VinDr-CXR 18K bbox 어노테이션으로 YOLOv8 **멀티GPU**(ml.g5.12xlarge, A10G×4) fine-tuning → 14개 클래스 바운딩 박스 탐지 |
| **Function/UX Effect** | X-Ray 위에 병변 위치 bbox + 클래스명 + confidence 오버레이. Layer 3 Clinical Logic에 위치 정보 제공 |
| **Core Value** | "무엇이 + 어디에" 결합으로 전문의 수준의 위치 특정 판독 실현. Layer 3~6 파이프라인의 핵심 입력 |

---

## 1. Overview

### 1.1 Purpose

Layer 2 Detection의 두 번째 축으로, DenseNet-121(14-label 확률 분류)과 상호 보완하는 **위치 탐지 모델**을 구축한다.

- DenseNet-121: "이 X-Ray에 Pleural Effusion이 **있다** (확률 0.87)" → **What**
- YOLOv8: "Pleural Effusion이 **좌측 하단 (x1,y1,x2,y2)에 있다** (conf 0.82)" → **Where**

### 1.2 Background

6-Layer 파이프라인에서 Layer 3 Clinical Logic이 정확한 병변 위치를 필요로 한다:
- Consolidation → Silhouette sign 판단 시 bbox 위치가 심장/횡격막 경계에 인접한지 확인
- Atelectasis → bbox 위치로 어떤 폐엽에 무기폐가 발생했는지 특정
- Lung Lesion → bbox 크기(px→cm)로 결절 vs 종괴 자동 분류
- Fracture → bbox 위치로 몇 번째 늑골 골절인지 추정

### 1.3 Related Documents

- Architecture: `CHEST_MODAL_V2_REDESIGN.md` (Layer 2 섹션)
- DenseNet Training: `layer2_detection/densenet/TRAINING_JOB_GUIDE.md`
- Layer 1 Deploy: `docs/01-plan/features/layer1-deploy.plan.md`

---

## 2. Scope

### 2.1 In Scope

- [x] VinDr-CXR 데이터셋 획득 및 S3 업로드
- [ ] DICOM → PNG 변환 + YOLO 포맷 어노테이션 생성
- [ ] YOLOv8 모델 선정 및 fine-tuning 코드 작성
- [ ] SageMaker 학습 잡 구성 및 실행
- [ ] 학습된 모델 평가 (mAP@0.5, mAP@0.5:0.95)
- [ ] Lambda 배포 (Layer 1과 동일 패턴)
- [ ] Layer 2 테스트 페이지 (bbox 시각화)

### 2.2 Out of Scope

- SIIM-ACR Pneumothorax 세그멘테이션 (별도 `pneumothorax_seg/` 에서 처리)
- DenseNet-121 재학습 (별도 진행 중)
- Layer 3 Clinical Logic 구현
- 모델 경량화 / 양자화 (추후 최적화)

---

## 3. 데이터 — VinDr-CXR

### 3.1 데이터셋 개요

| 항목 | 내용 |
|------|------|
| **데이터셋** | VinDr-CXR (Kaggle: vinbigdata-chest-xray-abnormalities-detection) |
| **이미지 수** | 18,000장 (train 15,000 / test 3,000) |
| **포맷** | DICOM (.dicom) |
| **해상도** | 다양 (대부분 2000×2500 이상) |
| **어노테이터** | 17명 방사선 전문의 (각 이미지 3명이 독립 어노테이션) |
| **라벨 형식** | CSV — image_id, class_name, class_id, x_min, y_min, x_max, y_max, rad_id |

### 3.2 VinDr-CXR 14 클래스

| class_id | class_name | 인스턴스 수 (approx) | 임상적 중요도 |
|----------|------------|---------------------|---------------|
| 0 | Aortic enlargement | 3,009 | 높음 |
| 1 | Atelectasis | 339 | 높음 |
| 2 | Calcification | 1,261 | 중간 |
| 3 | Cardiomegaly | 1,536 | 높음 |
| 4 | Consolidation | 478 | 높음 |
| 5 | ILD (Interstitial Lung Disease) | 603 | 높음 |
| 6 | Infiltration | 806 | 높음 |
| 7 | Lung Opacity | 5,765 | 높음 |
| 8 | Nodule/Mass | 3,796 | 매우 높음 |
| 9 | Other lesion | 1,993 | 중간 |
| 10 | Pleural effusion | 2,347 | 높음 |
| 11 | Pleural thickening | 2,542 | 중간 |
| 12 | Pneumothorax | 220 | 매우 높음 |
| 13 | Pulmonary fibrosis | 1,406 | 높음 |
| 14 | No finding | ~6,000 | - |

### 3.3 VinDr-CXR ↔ CheXpert 14-label 매핑

우리 파이프라인의 CheXpert 14개 라벨과 VinDr-CXR bbox 클래스 매핑:

| CheXpert Label | VinDr-CXR bbox 클래스 | 비고 |
|----------------|----------------------|------|
| Cardiomegaly | Cardiomegaly (3) | 직접 매핑 |
| Pleural Effusion | Pleural effusion (10) | 직접 매핑 |
| Consolidation | Consolidation (4) | 직접 매핑 |
| Atelectasis | Atelectasis (1) | 직접 매핑 |
| Pneumothorax | Pneumothorax (12) | 직접 매핑, 인스턴스 적음 주의 |
| Lung Lesion | Nodule/Mass (8) | 결절/종괴 bbox |
| Lung Opacity | Lung Opacity (7) | 가장 많은 인스턴스 |
| Enlarged Cardiomediastinum | Aortic enlargement (0) | 부분 매핑 |
| Edema | — | VinDr-CXR에 없음, DenseNet만 사용 |
| Fracture | — | VinDr-CXR에 있지만 class_name 다름 |
| Pleural Other | Pleural thickening (11) | 부분 매핑 |
| Support Devices | — | VinDr-CXR에 없음 |
| No Finding | No finding (14) | bbox 없음, 학습에서 제외 |

### 3.4 데이터 획득 전략

```
[방법 1] Kaggle CLI (권장)
──────────────────────────────────
1. SageMaker 노트북에서 kaggle CLI 설치
   pip install kaggle
2. Kaggle API 토큰 설정
   ~/.kaggle/kaggle.json
3. 데이터셋 다운로드 → S3 직접 업로드
   kaggle competitions download -c vinbigdata-chest-xray-abnormalities-detection
4. S3 경로: s3://work-bucket/vindr-cxr/raw/

[방법 2] 로컬 다운로드 후 S3 업로드
──────────────────────────────────
* 대용량(~50GB DICOM) → 로컬 다운로드 금지 규칙
* SageMaker에서 직접 처리 필수
```

**핵심 제약**: 로컬 다운로드 금지 → SageMaker 노트북 인스턴스에서 Kaggle API로 직접 다운로드 후 S3 업로드

---

## 4. 데이터 전처리 파이프라인

### 4.1 DICOM → PNG 변환

```python
# SageMaker 노트북에서 실행
import pydicom
from PIL import Image
import numpy as np

def dicom_to_png(dicom_path, output_path, target_size=640):
    """DICOM → PNG (YOLOv8 입력 크기)"""
    dcm = pydicom.dcmread(dicom_path)
    pixel_array = dcm.pixel_array.astype(np.float32)

    # Normalize to 0-255
    pixel_array = (pixel_array - pixel_array.min()) / (pixel_array.max() - pixel_array.min()) * 255

    # PhotometricInterpretation 처리
    if dcm.PhotometricInterpretation == "MONOCHROME1":
        pixel_array = 255 - pixel_array  # 반전

    img = Image.fromarray(pixel_array.astype(np.uint8))
    img = img.resize((target_size, target_size))  # 640x640 for YOLOv8
    img.save(output_path)

    return dcm.Rows, dcm.Columns  # 원본 크기 반환 (bbox 좌표 변환용)
```

### 4.2 다중 어노테이터 병합 (Weighted Box Fusion)

VinDr-CXR은 이미지당 3명의 방사선과 전문의가 독립 어노테이션. 병합 전략:

```
전략: Weighted Box Fusion (WBF)
──────────────────────────────
1. 각 이미지에 대해 3명의 어노테이션을 수집
2. IoU threshold = 0.5로 유사 bbox 그룹핑
3. 2명 이상 동의한 bbox만 채택 (majority voting)
4. 채택된 bbox의 좌표를 평균하여 최종 bbox 생성
5. 1명만 표시한 bbox는 제외 (노이즈 감소)

라이브러리: ensemble_boxes (pip install ensemble-boxes)
```

### 4.3 YOLO 포맷 변환

```
VinDr-CXR CSV 포맷:
  image_id, class_name, class_id, x_min, y_min, x_max, y_max, rad_id

        ↓ 변환 ↓

YOLO 포맷 (txt, 이미지당 1개):
  class_id  x_center  y_center  width  height  (모두 0~1 정규화)
```

### 4.4 디렉토리 구조 (YOLO 표준)

```
vindr-cxr-yolo/
├── images/
│   ├── train/     # 12,000장 (80%)
│   └── val/       # 3,000장 (20%)
├── labels/
│   ├── train/     # 대응하는 txt 파일
│   └── val/
└── data.yaml      # 클래스 정의
```

### 4.5 data.yaml

```yaml
path: /opt/ml/input/data/training  # SageMaker 경로
train: images/train
val: images/val

nc: 14
names:
  0: Aortic_enlargement
  1: Atelectasis
  2: Calcification
  3: Cardiomegaly
  4: Consolidation
  5: ILD
  6: Infiltration
  7: Lung_Opacity
  8: Nodule_Mass
  9: Other_lesion
  10: Pleural_effusion
  11: Pleural_thickening
  12: Pneumothorax
  13: Pulmonary_fibrosis
```

---

## 5. 모델 — YOLOv8

### 5.1 모델 선택

| 모델 | 파라미터 | mAP@0.5 (COCO) | 추론 속도 | 선택 |
|------|----------|----------------|-----------|:----:|
| YOLOv8n (nano) | 3.2M | 37.3 | 1.2ms | |
| **YOLOv8s (small)** | **11.2M** | **44.9** | **2.3ms** | **선택** |
| YOLOv8m (medium) | 25.9M | 50.2 | 5.5ms | |
| YOLOv8l (large) | 43.7M | 52.9 | 8.7ms | |

**YOLOv8s 선택 이유:**
1. Lambda 배포 시 컨테이너 크기 제약 (10GB) → 모델 경량 필요
2. 의료 영상은 클래스 수 14개로 COCO(80) 대비 적음 → small로 충분
3. 추론 속도 2.3ms → Lambda cold start 포함해도 10초 이내 가능
4. COCO pretrained weights → 의료 영상 fine-tuning으로 전이학습

### 5.2 멀티GPU 학습 설정 (DenseNet 멀티GPU 패턴 적용)

```python
"""
YOLOv8 Multi-GPU SageMaker 학습 스크립트

DenseNet train_multigpu.py에서 검증된 패턴 적용:
- EFA/NCCL/OMP 환경변수 사전 설정 (g5 인스턴스 필수)
- Ultralytics 내장 DDP (device=[0,1,2,3])
- Spot 체크포인트 복구
"""
import os
import sys

# ============================================================
# 환경변수 — 반드시 torch/ultralytics import 전에 설정
# (DenseNet train_multigpu.py에서 검증된 패턴)
# ============================================================
# EFA fork 안전 모드 (DataLoader fork() 크래시 방지)
os.environ['FI_EFA_FORK_SAFE'] = '1'
os.environ['RDMAV_FORK_SAFE'] = '1'

# NCCL 통신 안정화 (g5 인스턴스는 InfiniBand 없음)
os.environ['NCCL_IB_DISABLE'] = '1'
os.environ['NCCL_ASYNC_ERROR_HANDLING'] = '1'
os.environ['TORCH_NCCL_ASYNC_ERROR_HANDLING'] = '1'
os.environ['NCCL_SOCKET_IFNAME'] = 'eth0'
os.environ['NCCL_DEBUG'] = 'WARN'

# CPU 스레드 제어 (48 vCPU / 4 GPU = 12, 여유 두고 4)
os.environ['OMP_NUM_THREADS'] = '4'

from ultralytics import YOLO

model = YOLO('yolov8s.pt')  # COCO pretrained

results = model.train(
    data='data.yaml',
    epochs=100,
    imgsz=640,
    batch=64,              # 총 64 (GPU당 16 × 4대)
    device=[0, 1, 2, 3],  # ★ 4-GPU DDP (Ultralytics 내장)
    patience=15,           # early stopping
    optimizer='AdamW',
    lr0=0.001,
    lrf=0.01,              # final lr = lr0 * lrf
    warmup_epochs=3,
    workers=16,            # DataLoader num_workers (DenseNet과 동일)

    # 의료 영상 특화 증강
    hsv_h=0.0,             # 색조 변경 불필요 (그레이스케일)
    hsv_s=0.0,             # 채도 변경 불필요
    hsv_v=0.2,             # 밝기 변경만 허용
    degrees=10,            # 미세 회전 (촬영 각도 변이)
    translate=0.1,
    scale=0.3,
    fliplr=0.5,            # 좌우 반전 (유효)
    flipud=0.0,            # 상하 반전 금지 (비현실적)
    mosaic=0.0,            # 모자이크 증강 부적합 (해부학 구조 파괴)
    mixup=0.0,             # 혼합 증강 부적합 (병변 특성 왜곡)

    # 출력
    project='/opt/ml/model',
    name='yolov8s-vindr',
    save_period=10,        # 10 epoch마다 체크포인트
    exist_ok=True,         # Spot 재시작 시 덮어쓰기 허용
)
```

### 5.3 DenseNet 멀티GPU에서 가져온 핵심 패턴

| 패턴 | DenseNet 구현 | YOLOv8 적용 |
|------|--------------|-------------|
| **EFA fork safe** | `FI_EFA_FORK_SAFE=1` | 동일 적용 (DataLoader fork 크래시 방지) |
| **NCCL 안정화** | `NCCL_IB_DISABLE=1` 등 6개 | 동일 적용 (g5는 InfiniBand 없음) |
| **OMP 스레드** | `OMP_NUM_THREADS=4` | 동일 적용 (48vCPU/4GPU) |
| **병렬화 방식** | nn.DataParallel | Ultralytics 내장 DDP (더 효율적) |
| **배치 크기** | 128 (GPU당 32) | 64 (GPU당 16, 640px 이미지라 VRAM 더 필요) |
| **num_workers** | 16 | 16 (동일) |
| **Gradient clipping** | max_norm=1.0 수동 | Ultralytics 내장 (자동) |
| **체크포인트** | atomic save (tmp→replace) | Ultralytics 내장 save_period |
| **Spot 복구** | load_checkpoint() | Ultralytics resume=True |

### 5.4 의료 영상 특화 증강 주의사항

| 증강 | COCO 기본값 | 의료 영상 설정 | 이유 |
|------|------------|---------------|------|
| mosaic | 1.0 | **0.0** | 4장 합성은 해부학적 구조 파괴 |
| mixup | 0.0 | **0.0** | 이미지 블렌딩은 병변 특성 왜곡 |
| hsv_h/s | 0.015/0.7 | **0.0/0.0** | 그레이스케일 의료 영상에 불필요 |
| flipud | 0.0 | **0.0** | 상하 반전된 X-Ray는 비현실적 |
| fliplr | 0.5 | **0.5** | 좌우 반전은 유효 (미러 케이스 학습) |
| degrees | 0.0 | **10** | 약간의 회전은 촬영 각도 변이 시뮬레이션 |

---

## 6. 학습 인프라 — SageMaker (멀티GPU)

### 6.1 학습 잡 구성 — DenseNet 동일 인스턴스

| 항목 | 설정 | 비고 |
|------|------|------|
| **인스턴스** | **ml.g5.12xlarge** (4x NVIDIA A10G 24GB, 48 vCPU, 192GB RAM) | DenseNet과 동일 |
| **볼륨** | 150GB (이미지 + 모델 체크포인트) | |
| **Docker 이미지** | PyTorch 2.8.0 GPU (SageMaker 제공) | `763104351884.dkr.ecr.ap-northeast-2.amazonaws.com/pytorch-training:2.8.0-gpu-py312-cu129-ubuntu22.04-sagemaker` |
| **학습 시간** | 예상 **1~2시간** (4GPU 병렬, 100 epochs, 15K images) | 싱글GPU 대비 ~3x 빨라짐 |
| **Spot 인스턴스** | 사용 (비용 60~70% 절감) | |
| **비용 예상** | Spot: ~$2.14/h × 2h ≈ **$4.28** | On-Demand $7.09/h |

### 6.2 싱글GPU vs 멀티GPU 비교

| 항목 | 싱글 (ml.g5.xlarge) | **멀티 (ml.g5.12xlarge)** |
|------|---------------------|--------------------------|
| GPU | A10G × 1 | **A10G × 4** |
| VRAM 합계 | 24GB | **96GB** |
| vCPU | 4 | **48** |
| RAM | 16GB | **192GB** |
| 배치 크기 | 16 | **64** (GPU당 16) |
| 예상 학습 시간 | 4~6시간 | **1~2시간** |
| Spot 단가 | ~$0.42/h | ~$2.14/h |
| **총 비용** | ~$2.1~2.5 | **~$2.1~4.3** |
| 비용 대비 시간 | 느림 | **비슷한 비용, 3배 빠름** |

### 6.3 SageMaker 학습 잡 JSON (DenseNet 멀티GPU 패턴 기반)

```json
{
    "TrainingJobName": "yolov8s-vindr-v1-multigpu",
    "RoleArn": "arn:aws:iam::666803869796:role/SKKU_SageMaker_Role",
    "AlgorithmSpecification": {
        "TrainingImage": "763104351884.dkr.ecr.ap-northeast-2.amazonaws.com/pytorch-training:2.8.0-gpu-py312-cu129-ubuntu22.04-sagemaker",
        "TrainingInputMode": "File"
    },
    "HyperParameters": {
        "sagemaker_program": "train.py",
        "sagemaker_submit_directory": "s3://work-bucket/code/yolov8_sourcedir.tar.gz",
        "sagemaker_region": "ap-northeast-2",
        "batch-size": "64",
        "epochs": "100",
        "imgsz": "640",
        "patience": "15"
    },
    "ResourceConfig": {
        "InstanceType": "ml.g5.12xlarge",
        "InstanceCount": 1,
        "VolumeSizeInGB": 150
    },
    "InputDataConfig": [
        {
            "ChannelName": "training",
            "DataSource": {
                "S3DataSource": {
                    "S3DataType": "S3Prefix",
                    "S3Uri": "s3://work-bucket/vindr-cxr/processed/",
                    "S3DataDistributionType": "FullyReplicated"
                }
            }
        }
    ],
    "CheckpointConfig": {
        "S3Uri": "s3://work-bucket/checkpoints/yolov8s-vindr-v1/"
    },
    "OutputDataConfig": {
        "S3OutputPath": "s3://work-bucket/output/"
    },
    "EnableManagedSpotTraining": true,
    "StoppingCondition": {
        "MaxRuntimeInSeconds": 10800,
        "MaxWaitTimeInSeconds": 172800
    },
    "Tags": [
        { "Key": "name", "Value": "say2-preproject-6team-hyunwoo" }
    ]
}
```

### 6.4 인스턴스 스케줄링 주의

> **주의**: 현재 DenseNet 멀티GPU 학습이 ml.g5.12xlarge에서 진행 중.
> YOLOv8 학습은 DenseNet 완료 후 실행하거나, 동시 실행 시 별도 인스턴스 할당 필요.
> 교육 계정 GPU 인스턴스 Quota 확인 필수.

### 6.5 S3 경로 계획

```
s3://work-bucket/
├── vindr-cxr/
│   ├── raw/                    # 원본 DICOM (Kaggle 다운로드)
│   ├── processed/              # PNG 640x640 + YOLO labels
│   │   ├── images/train/
│   │   ├── images/val/
│   │   ├── labels/train/
│   │   ├── labels/val/
│   │   └── data.yaml
│   └── annotations/           # 원본 CSV + 병합된 CSV
├── code/
│   └── yolov8_sourcedir.tar.gz
├── checkpoints/
│   └── yolov8s-vindr/
└── output/
    └── yolov8s-vindr/
        └── model.tar.gz       # best.pt + last.pt

(work-bucket = pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an)
```

### 6.6 SageMaker 학습 스크립트 구조

```
yolov8_sourcedir/
├── train.py          # SageMaker 엔트리포인트 (EFA/NCCL 환경변수 포함)
├── preprocess.py     # DICOM→PNG + CSV→YOLO 변환
├── requirements.txt  # ultralytics, pydicom, ensemble-boxes
└── data.yaml         # 클래스 정의

requirements.txt:
  ultralytics>=8.0
  pydicom
  ensemble-boxes
  opencv-python-headless
```

---

## 7. 배포 — Lambda

### 7.1 배포 아키텍처 (Layer 1과 동일 패턴)

```
[클라이언트] → [Lambda Function URL] → [YOLOv8 추론]
                                          ├── base64 이미지 입력
                                          ├── YOLOv8 bbox 추론
                                          └── JSON 응답 (boxes, classes, scores)
```

### 7.2 Lambda 구성

| 항목 | 설정 |
|------|------|
| **런타임** | Container (Python 3.12) |
| **메모리** | 4096 MB (YOLOv8s ~45MB 모델) |
| **타임아웃** | 60초 |
| **Ephemeral Storage** | 2048 MB (모델 캐시) |
| **모델 로딩** | S3에서 /tmp 다운로드 → 캐시 |
| **태그** | `project: say2-preproject-6team` (필수) |

### 7.3 Dockerfile

```dockerfile
FROM public.ecr.aws/lambda/python:3.12

# PyTorch CPU + Ultralytics
RUN pip install --no-cache-dir \
    torch torchvision --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir \
    ultralytics \
    Pillow \
    numpy \
    boto3

COPY lambda_function.py ${LAMBDA_TASK_ROOT}/
COPY index.html ${LAMBDA_TASK_ROOT}/

CMD ["lambda_function.handler"]
```

### 7.4 응답 포맷

```json
{
  "status": "success",
  "detections": [
    {
      "class_id": 10,
      "class_name": "Pleural_effusion",
      "confidence": 0.87,
      "bbox": {
        "x_min": 120, "y_min": 380,
        "x_max": 350, "y_max": 520
      },
      "bbox_normalized": {
        "x_center": 0.367, "y_center": 0.703,
        "width": 0.359, "height": 0.219
      }
    }
  ],
  "image_size": {"width": 640, "height": 640},
  "model": "yolov8s-vindr",
  "inference_time_ms": 45
}
```

---

## 8. Requirements

### 8.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | VinDr-CXR 18K 이미지 획득 및 S3 저장 | High | Pending |
| FR-02 | DICOM → PNG 640x640 변환 파이프라인 | High | Pending |
| FR-03 | 다중 어노테이터 bbox WBF 병합 | High | Pending |
| FR-04 | CSV → YOLO 포맷 변환 | High | Pending |
| FR-05 | YOLOv8s fine-tuning 코드 작성 | High | Pending |
| FR-06 | SageMaker 학습 잡 실행 | High | Pending |
| FR-07 | mAP@0.5 ≥ 0.30 달성 | High | Pending |
| FR-08 | Lambda 컨테이너 배포 | Medium | Pending |
| FR-09 | 테스트 페이지 bbox 시각화 | Medium | Pending |
| FR-10 | Layer 1 세그멘테이션 결과와 bbox 매핑 | Low | Pending |

### 8.2 Non-Functional Requirements

| Category | Criteria | Measurement |
|----------|----------|-------------|
| Performance | Lambda 추론 < 10초 (cold start 포함) | CloudWatch |
| Performance | 모델 크기 < 100MB (S3 → /tmp 로딩) | 파일 크기 |
| Accuracy | mAP@0.5 ≥ 0.30 (VinDr-CXR 벤치마크 기준) | 학습 로그 |
| Cost | SageMaker 학습 < $5 (Spot, 1~2h) | AWS 비용 탐색기 |
| Cost | Lambda 호출당 < $0.01 | CloudWatch |

---

## 9. Success Criteria

### 9.1 Definition of Done

- [ ] VinDr-CXR 데이터 S3 저장 완료
- [ ] 전처리 파이프라인 검증 (샘플 100장)
- [ ] YOLOv8s fine-tuning 완료 (mAP@0.5 ≥ 0.30)
- [ ] Lambda 배포 및 Function URL 활성화
- [ ] 테스트 페이지에서 bbox 시각화 동작 확인
- [ ] Layer 1 + Layer 2 결합 테스트

### 9.2 Quality Criteria

- [ ] 14개 클래스 중 주요 8개 (Lung Opacity, Nodule/Mass, Pleural effusion, Cardiomegaly, Aortic enlargement, Pleural thickening, Pulmonary fibrosis, Calcification) AP ≥ 0.25
- [ ] 소수 클래스 (Pneumothorax 220건, Atelectasis 339건) 과적합 방지 확인
- [ ] Lambda cold start ≤ 15초

---

## 10. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| VinDr-CXR DICOM 용량 ~50GB → SageMaker 저장 공간 부족 | High | Medium | 노트북 인스턴스 200GB 볼륨 사용. 변환 후 DICOM 원본 삭제 |
| 소수 클래스 (Pneumothorax 220건) 성능 저조 | Medium | High | 클래스별 가중치 조정, focal loss 적용, 추가 데이터 증강 |
| Kaggle API 인증 실패 (SageMaker 환경) | Medium | Low | Kaggle JSON 토큰 S3 업로드 → 노트북에서 복사 |
| YOLOv8 + PyTorch CPU Lambda 컨테이너 10GB 초과 | High | Medium | ultralytics 최소 설치, 불필요 패키지 제거, 모델은 S3에서 런타임 로딩 |
| 다중 어노테이터 불일치율 높음 → 노이즈 bbox | Medium | Medium | WBF + majority voting (2/3 동의 필수) |
| SageMaker Spot 중단 | Low | Medium | 체크포인트 10 epoch마다 저장, 자동 재시작 |
| DenseNet 학습과 GPU 인스턴스 충돌 | Medium | High | DenseNet 완료 후 YOLOv8 실행. 또는 교육 계정 Quota 내 동시 실행 확인 |

---

## 11. 구현 로드맵

### Phase 1: 데이터 준비 (Day 1-2)

```
1. Kaggle API 설정 (SageMaker 노트북)
2. VinDr-CXR 다운로드 → S3 raw/ 업로드
3. DICOM → PNG 640x640 변환
4. 다중 어노테이터 WBF 병합
5. CSV → YOLO txt 변환
6. train/val split (80/20)
7. data.yaml 생성
8. S3 processed/ 업로드
```

### Phase 2: 모델 학습 (Day 2-3)

```
1. train.py 작성 (EFA/NCCL 환경변수 + Ultralytics DDP)
   - DenseNet train_multigpu.py 패턴 적용
2. sourcedir.tar.gz 패키징 → S3 업로드
3. ★ DenseNet 학습 완료 대기 (g5.12xlarge 공유)
4. SageMaker 학습 잡 제출 (ml.g5.12xlarge, 4-GPU Spot)
5. 학습 모니터링 (CloudWatch Logs)
6. best.pt 다운로드 → 평가
7. mAP 미달 시: lr/epochs/augmentation 조정 → 재학습
```

### Phase 3: 배포 (Day 3-4)

```
1. lambda_function.py 작성
2. index.html 테스트 페이지 (bbox SVG 오버레이)
3. Docker build → ECR push
4. Lambda 생성 → Function URL
5. 통합 테스트 (샘플 이미지 5장)
```

---

## 12. 기술 스택

| 구분 | 기술 | 버전 |
|------|------|------|
| Object Detection | Ultralytics YOLOv8 | 8.x (latest) |
| Deep Learning | PyTorch | 2.x |
| 이미지 처리 | pydicom, Pillow | latest |
| bbox 병합 | ensemble-boxes (WBF) | latest |
| 학습 인프라 | AWS SageMaker | - |
| 배포 | AWS Lambda (Container) | Python 3.12 |
| 컨테이너 | Docker (ECR) | - |
| 모델 저장 | AWS S3 | - |

---

## 13. Next Steps

1. [ ] Design 문서 작성 (`layer2_yolov8.design.md`)
2. [ ] SageMaker 노트북에서 Kaggle CLI 설정
3. [ ] 데이터 전처리 코드 작성 (`preprocess.py`)
4. [ ] YOLOv8 학습 코드 작성 (`train.py`)
5. [ ] 학습 실행 및 평가
6. [ ] Lambda 배포

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-22 | Initial draft | hyunwoo |
