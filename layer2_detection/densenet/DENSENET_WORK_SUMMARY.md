# Layer 2: DenseNet-121 14-Disease Detection - 작업 요약

> 작성일: 2026-03-22

## 개요

**목표**: MIMIC-CXR PA 흉부 X-Ray 이미지에서 CheXpert 14개 질환을 동시 탐지하는 Multi-label Classification 모델 구축 + Lambda 서버리스 배포

**모델**: DenseNet-121 (ImageNet pretrained → MIMIC-CXR Fine-tuned)

**결과**: Mean AUROC 0.701 (998장 테스트셋), Lambda Function URL 배포 완료

---

## 타임라인

### Day 1 (2026-03-20) — 데이터 전처리 파이프라인

| 단계 | 내용 | 결과 |
|------|------|------|
| CSV 병합 | metadata + split + chexpert 3종 → Master CSV | 377,095행 |
| PA 필터링 | ViewPosition == 'PA' (정면만) | 377,095 → 96,155 |
| 불량 제거 + U-Ones | NaN→0, Uncertain(-1)→1(양성) 변환 | 96,155 → 94,380 |
| pos_weight 계산 | 14개 질환별 클래스 불균형 가중치 산출 | pos_weights.json |
| p10 서브셋 | p10 환자군으로 소규모 실험셋 구성 | 9,118장 (train 8,993 / val 65 / test 60) |

### Day 2 (2026-03-21) — 학습 스크립트 + 첫 학습

- **p10 → 전체 PA 전환 결정**: 서브셋 테스트 단계가 복잡도만 증가 → 바로 전체 94K 프로덕션 학습
- **All-in-one 학습 스크립트 (`train.py`)** 완성:
  - S3에서 CSV 3종 직접 로드 → 전체 PA Master CSV 내부 생성
  - 이미지 S3 선택 다운로드 (PA만, ThreadPoolExecutor 32병렬)
  - 2-Stage Fine-tuning (Stage1: classifier 5ep + Stage2: full 25ep)
  - BCEWithLogitsLoss + pos_weight, 스팟 체크포인트
- **원클릭 제출 노트북** (`submit_training_jobs.ipynb`): 셀 2개만 실행하면 Training Job 제출
- **쿼터 이슈**: ml.g5.xlarge 스팟 1개 제한 → DenseNet을 ml.g4dn.xlarge로 변경하여 해결
- **densenet121-mimic-cxr-v1 (p10)**: AUROC 0.748 달성

### Day 3 (2026-03-22) — 스케일업 + 배포 + 평가

#### Session 1: 실패 분석 + v3 스크립트
- **v1/v2 Training Job 실패 원인 분석**:
  - densenet121-full-pa-v2: 디스크 부족 (80GB에 94K 이미지 ~48GB + 모델/캐시)
- **v3 수정사항**:
  - 볼륨 80GB → 150GB
  - 인스턴스 ml.g5.xlarge → ml.g5.12xlarge (A10G x4)
  - atomic checkpoint (`.tmp` → `os.replace`)
  - 디스크 모니터링 추가

#### Session 2: Multi-GPU 스크립트 + v6 제출
- **`train_multigpu.py`** 작성:
  - nn.DataParallel 4 GPU 병렬
  - 배치 128 (GPU당 32), num_workers 16
  - EFA/NCCL/OMP 환경변수 사전 설정
  - gradient clipping, drop_last
- **v6 Training Job 제출** (SageMaker 노트북에서)

#### Session 3: 학습 완료 + 배포 + 평가
- **v6 학습 완료**: 30 epochs, 4x A10G GPU, 94,380장 PA 이미지
  - Best Val AUROC: 0.814
- **모델 스왑**: epoch 17 checkpoint → best_model.pth (27.2MB, raw state_dict)
- **Lambda 배포**: ECR → Docker → Lambda → Function URL
  - Endpoint: `https://pk67s3qrp3b3xluqkcp6neqly40kduol.lambda-url.ap-northeast-2.on.aws/`
- **종합 성능평가**: 998장 테스트셋, 14개 질환 전체 메트릭

---

## 학습 아키텍처

### 2-Stage Fine-tuning
```
Stage 1 (Epoch 1~5)     Stage 2 (Epoch 6~30)
├── Feature Extractor    ├── Feature Extractor
│   └── FROZEN           │   └── TRAINABLE
├── Classifier           ├── Classifier
│   └── TRAINABLE        │   └── TRAINABLE
├── LR: 1e-4             ├── LR: 1e-5 (1/10)
└── 목적: 빠른 적응       └── 목적: 미세 조정
```

### 인프라
| 항목 | v1 (p10 테스트) | v6 (프로덕션) |
|------|-----------------|---------------|
| 인스턴스 | ml.g4dn.xlarge (T4 1개) | ml.g5.12xlarge (A10G 4개) |
| GPU 메모리 | 16GB | 24GB x 4 = 96GB |
| 스토리지 | 80GB | 150GB |
| 배치 크기 | 32 | 128 (GPU당 32) |
| 데이터 | 9,118장 (p10) | 94,380장 (전체 PA) |
| 에폭 | 30 (5+25) | 30 (5+25) |
| 비용 | ~$1 (스팟) | ~$15-20 (스팟) |

---

## 성능 평가 결과

### 998장 테스트셋 전체 메트릭

| 질환 | AUROC | Sensitivity | Specificity | F1 | Prevalence |
|------|-------|-------------|-------------|-----|-----------|
| **Edema** | **0.854** | 0.979 | 0.462 | 0.383 | 14.6% |
| **Pleural Effusion** | **0.832** | 0.885 | 0.541 | 0.547 | 25.4% |
| **Pneumothorax** | **0.759** | 0.833 | 0.651 | 0.080 | 1.8% |
| Support Devices | 0.741 | 0.789 | 0.567 | 0.333 | 12.8% |
| No Finding | 0.736 | 0.474 | 0.844 | 0.486 | 24.7% |
| Cardiomegaly | 0.726 | 0.923 | 0.386 | 0.415 | 19.5% |
| Atelectasis | 0.724 | 0.865 | 0.455 | 0.384 | 17.1% |
| Pleural Other | 0.709 | 0.795 | 0.545 | 0.123 | 3.9% |
| Consolidation | 0.688 | 0.897 | 0.335 | 0.184 | 7.8% |
| Lung Opacity | 0.635 | 0.838 | 0.348 | 0.509 | 31.0% |
| Pneumonia | 0.627 | 0.797 | 0.363 | 0.403 | 22.7% |
| Fracture | 0.612 | 0.489 | 0.749 | 0.149 | 4.7% |
| Enlarged CM | 0.605 | 0.594 | 0.566 | 0.150 | 6.4% |
| **Lung Lesion** | **0.569** | 0.643 | 0.464 | 0.121 | 5.6% |

### 요약
| 메트릭 | 값 |
|--------|-----|
| **Mean AUROC** | **0.701** |
| Mean Sensitivity | 0.772 |
| Mean Specificity | 0.520 |
| Mean F1 | 0.305 |
| Macro F1 | 0.305 |
| Micro F1 | 0.338 |

### CheXpert 벤치마크 비교 (5개 경쟁 질환)
| 질환 | Ours | CheXpert (2019) | 차이 |
|------|------|-----------------|------|
| Atelectasis | 0.724 | 0.858 | -0.134 |
| Cardiomegaly | 0.726 | 0.854 | -0.128 |
| Consolidation | 0.688 | 0.939 | -0.251 |
| Edema | 0.854 | 0.941 | -0.087 |
| Pleural Effusion | 0.832 | 0.936 | -0.104 |

> CheXpert 논문은 방사선과 전문의 3명 합의 라벨 + 200장 소규모 테스트셋 사용.
> 우리 모델은 U-Ones 자동 라벨 + 998장 대규모 테스트셋으로 조건이 다름.

---

## 생성된 파일 목록

### 학습 관련
| 파일 | 설명 |
|------|------|
| `layer2_detection/densenet/train.py` | Single-GPU all-in-one 학습 (v1) |
| `layer2_detection/densenet/train_multigpu.py` | Multi-GPU 4x A10G 학습 (v3~v6) |
| `layer2_detection/densenet/training_job_config.json` | SageMaker v1 설정 |
| `layer2_detection/densenet/training_job_config_multigpu.json` | SageMaker Multi-GPU 설정 |
| `layer2_detection/densenet/submit_multigpu_job.ipynb` | SageMaker 제출 노트북 |
| `layer2_detection/densenet/TRAINING_JOB_GUIDE.md` | Training Job 설정 가이드 |

### 추론/평가 관련
| 파일 | 설명 |
|------|------|
| `layer2_detection/densenet/detection_model.py` | DetectionModel 래퍼 클래스 |
| `layer2_detection/densenet/eval_local.py` | 로컬 평가 스크립트 (998장, 실제 사용) |
| `layer2_detection/densenet/eval_densenet.py` | SageMaker 평가 스크립트 (미사용) |
| `layer2_detection/densenet/run_eval.py` | SageMaker 평가 제출 (미사용) |
| `layer2_detection/densenet/eval_results.json` | 평가 결과 JSON |
| `layer2_detection/densenet/roc_data.json` | ROC 커브 데이터 |

### 배포 관련
| 파일 | 설명 |
|------|------|
| `deploy/layer2_detection/lambda_function.py` | Lambda 핸들러 (GET→UI, POST→API) |
| `deploy/layer2_detection/Dockerfile` | Lambda 컨테이너 (PyTorch CPU) |
| `deploy/layer2_detection/index.html` | 테스트 페이지 (Dark theme) |
| `deploy/deploy_layer2.py` | 배포 자동화 스크립트 |

### S3 모델 아티팩트
```
s3://pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an/
├── models/detection/densenet121.pth          ← 서빙용 (best_model.pth, 27.2MB)
├── output/densenet121-eval/eval_results.json ← 평가 결과
└── output/densenet-multigpu-v6-.../          ← Training Job 출력 (model.tar.gz)
```

---

## 주요 트러블슈팅

| 문제 | 원인 | 해결 |
|------|------|------|
| Training Job 디스크 부족 | 80GB에 94K 이미지(~48GB) + 모델/캐시 | 150GB로 확장 |
| 스팟 쿼터 충돌 | ml.g5.xlarge 스팟 1개 제한 (Layer 1과 충돌) | ml.g4dn.xlarge로 변경 |
| Lambda 태그 오류 | `say2-preproject-6team` → `pre-*team` 패턴 불일치 | `pre-project-6team`으로 변경 |
| Function URL OPTIONS 오류 | AllowMethods에 OPTIONS 포함 (6자 초과) | OPTIONS 제거 |
| 로컬 평가 인코딩 오류 | cp949 코덱으로 em dash 출력 불가 | `python -X utf8` 실행 |
| SageMaker 평가 불가 | 로컬 CLI에 sagemaker:CreateTrainingJob 권한 없음 | 로컬에서 직접 평가 실행 |
| DataParallel 모델 로드 | 가중치 키에 `module.` 접두사 포함 | `module.` 접두사 제거 로직 추가 |

---

## Lambda 배포 정보

| 항목 | 값 |
|------|-----|
| ECR 리포지토리 | `layer2-detection` |
| Lambda 함수 | `layer2-detection` |
| 메모리 | 2048 MB |
| 타임아웃 | 120초 |
| Function URL | `https://pk67s3qrp3b3xluqkcp6neqly40kduol.lambda-url.ap-northeast-2.on.aws/` |
| 이미지 크기 | ~1.8GB (PyTorch CPU + DenseNet-121) |
| 콜드스타트 | ~15-20초 (모델 S3 다운로드 + 로드) |
| 웜스타트 | ~0.5-1초 |

### API
- `GET /` → 테스트 UI (Dark theme, 샘플 갤러리, 드래그앤드롭)
- `POST /` `{"action": "detect", "image": "<base64>"}` → 14개 질환 확률
- `POST /` `{"action": "list_samples"}` → 샘플 이미지 목록
