# YOLOv8 VinDr-CXR 14-Class Detection — Work Summary

## 개요
VinDr-CXR 데이터셋 기반 YOLOv8s 14클래스 병변 탐지 모델.
DenseNet-121(분류)과 함께 Layer 2의 보조 탐지 모듈로 사용.

## 아키텍처
- **모델**: YOLOv8s (11.2M params, COCO pretrained → VinDr-CXR fine-tune)
- **역할**: L2b — 병변 위치(바운딩박스) 제공, L2a DenseNet과 상호보완
- **파이프라인**: L1 Segmentation → **L2a DenseNet + L2b YOLOv8** → L3 Clinical Logic

## 데이터셋: VinDr-CXR
- **원본**: Kaggle vinbigdata-chest-xray-abnormalities-detection
- **이미지**: 15,000장 (train 12,000 + test 3,000)
- **어노테이터**: 17명 라디올로지스트, 이미지당 3명 독립 판독
- **박스 합성**: WBF (Weighted Box Fusion), iou_thr=0.5, skip_box_thr=0.33
- **최종 데이터**: train 6,059장 / val 1,516장 / labels 23,905개

### 14 클래스
| ID | Class | ID | Class |
|----|-------|----|-------|
| 0 | Aortic_enlargement | 7 | Lung_Opacity |
| 1 | Atelectasis | 8 | Nodule_Mass |
| 2 | Calcification | 9 | Other_lesion |
| 3 | Cardiomegaly | 10 | Pleural_effusion |
| 4 | Consolidation | 11 | Pleural_thickening |
| 5 | ILD | 12 | Pneumothorax |
| 6 | Infiltration | 13 | Pulmonary_fibrosis |

## 학습 설정
- **인스턴스**: SageMaker ml.g5.12xlarge (A10G x4, 24GB each)
- **배치**: 64 (GPU당 16)
- **이미지 크기**: 1024
- **Epochs**: 100 (patience=20 → epoch 66에서 조기종료)
- **LR**: 0.01 → 0.01 (cosine)
- **Augmentation**: 의료영상 특화 (mosaic=0, mixup=0, hsv_h/s=0, flipud=0)

### 주요 환경 패치
- `numpy.trapz` → `numpy.trapezoid` (.pth 파일로 DDP 서브프로세스 대응)
- `ray` 라이브러리 제거 (ultralytics raytune 콜백 충돌)
- `ultralytics==8.3.52` 고정 (최신 버전은 YOLO26 기본)
- `YOLO_OFFLINE=1` (모델 자동 다운로드 차단)

## 학습 결과 (Best: Epoch 46)
| Metric | Value |
|--------|-------|
| mAP@0.5 | 12.0% |
| mAP@0.5:0.95 | 5.0% |
| Precision | 22.1% |
| Recall | 15.1% |
| 학습 시간 | ~48분 |

### 성능 해석
- 14클래스, 6,059장 의료 데이터 → 낮은 mAP는 정상 범위
- 파이프라인에서 DenseNet(분류) + YOLOv8(위치) 조합으로 사용
- 단독 정확도보다 "병변 위치 힌트" 역할이 핵심

## S3 경로
| 항목 | S3 Key |
|------|--------|
| 학습된 모델 | `models/yolov8_vindr_best.pt` (22.6MB) |
| 학습 결과 | `output/yolov8_vindr/` |
| 전처리 데이터 | `vindr-cxr/processed/` (images, labels, data.yaml) |
| 원본 CSV | `vindr-cxr/raw/train.csv` |
| 기본 모델 | `models/yolov8s.pt` (COCO pretrained) |

## Lambda 배포
| 항목 | 값 |
|------|-----|
| Lambda 이름 | `layer2b-yolov8` |
| ECR 리포 | `layer2b-yolov8` |
| Function URL | `https://yoaval7laoc4ngnkr7uod7dufm0nmxib.lambda-url.ap-northeast-2.on.aws/` |
| 메모리 | 3008 MB |
| 타임아웃 | 180초 |
| 추론 설정 | conf=0.15, iou=0.45, imgsz=1024, CPU |

## 파일 구조

### 학습 코드 (`layer2_detection/yolov8/`)
```
train.py                  # SageMaker 멀티GPU 학습 스크립트
preprocess_vindr.py       # 전처리 파이프라인 (Kaggle→WBF→YOLO format)
preprocess_vindr.ipynb    # 전처리 노트북 (SageMaker에서 실행)
yolov8_train_local.ipynb  # 노트북 학습 (최종 사용 버전)
```

### 배포 (`deploy/`)
```
deploy_layer2b.py                  # 배포 스크립트
layer2b_yolov8/lambda_function.py  # Lambda 핸들러
layer2b_yolov8/index.html          # 테스트 페이지
layer2b_yolov8/Dockerfile          # 컨테이너 이미지
```

## 트러블슈팅 히스토리
1. SageMaker Training Job × 5회 실패 → 노트북 직접 학습으로 전환
2. `torch.cuda.get_device_properties(i).total_memory` (total_mem 아님)
3. `ultralytics>=8.3.0` → YOLO26 설치됨 → `==8.3.52` 고정
4. numpy 2.x `trapz` 제거 → `.pth` 파일 monkey-patch
5. ray 라이브러리 충돌 → `pip uninstall ray`
6. opencv-python GUI 의존성 → `opencv-python-headless` 사용
7. Docker OCI manifest → `--provenance=false`

## 작업 일자
- 2026-03-22: 전처리 완료, 학습 완료, Lambda 배포 완료
