# SageMaker Training Job 설정 가이드

## 개요
SageMaker Training Job은 노트북과 달리 인스턴스를 자동 생성 → 학습 → 자동 삭제하는 방식.
학습 시간만 과금되고, 스팟 인스턴스로 60~70% 할인 가능.

## 현재 설정 (densenet121-mimic-cxr-v1)

### 작업 기본 정보
- **작업 이름**: densenet121-mimic-cxr-v1
- **IAM 역할**: SKKU_SageMaker_Role (arn:aws:iam::666803869796:role/SKKU_SageMaker_Role)
- **컨테이너**: SageMaker 공식 PyTorch 2.8.0 GPU 이미지
  - `763104351884.dkr.ecr.ap-northeast-2.amazonaws.com/pytorch-training:2.8.0-gpu-py312-cu129-ubuntu22.04-sagemaker`

### 인스턴스
- **타입**: ml.g5.xlarge (NVIDIA A10G 24GB, FP32 31.2 TFLOPS)
- **스토리지**: 80GB (이미지 ~48GB + 여유)
- **스팟**: 활성화 (On-Demand $1.41/hr → 스팟 ~$0.42/hr)
- **최대 실행 시간**: 6시간
- **최대 대기 시간**: 48시간 (스팟 할당 대기 포함)

### 하이퍼파라미터
| 키 | 값 | 설명 |
|---|---|---|
| sagemaker_program | train.py | 실행할 스크립트 |
| sagemaker_submit_directory | s3://.../code/sourcedir.tar.gz | 코드 패키지 S3 경로 |
| sagemaker_region | ap-northeast-2 | 리전 |
| batch-size | 32 | 배치 크기 |
| stage1-epochs | 5 | Stage 1 (classifier only) 에폭 수 |
| stage2-epochs | 25 | Stage 2 (full fine-tune) 에폭 수 |

### S3 경로 구조
```
s3://pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an/
├── code/sourcedir.tar.gz              ← 학습 스크립트 패키지
├── data/p10_pa/                       ← 입력 채널 "train" (이미지 29,911개, ~48GB)
│   └── files/p10/p10XXXXX/sXXXXX/    ← MIMIC-CXR PA 이미지
├── preprocessing/                     ← 입력 채널 "csv"
│   └── p10_train_ready_resplit.csv    ← 학습용 CSV (9,118행)
├── checkpoints/densenet121/           ← 체크포인트 (스팟 중단 복구용)
└── output/                            ← 최종 모델 아티팩트 출력
```

### 데이터 흐름 (SageMaker 내부)
1. SageMaker가 인스턴스 생성
2. S3 데이터 → 로컬 디스크 자동 다운로드
   - train 채널: `/opt/ml/input/data/train/files/p10/...`
   - csv 채널: `/opt/ml/input/data/csv/p10_train_ready_resplit.csv`
3. `train.py` 실행 (하이퍼파라미터가 커맨드라인 인자로 전달됨)
4. 매 에폭 체크포인트 → `/opt/ml/checkpoints/` → SageMaker가 S3 자동 동기화
5. 학습 완료 → best 모델 `/opt/ml/model/` → S3 output 자동 업로드
6. 인스턴스 자동 삭제

## CLI 실행 방법

### 학습 작업 생성
```bash
aws sagemaker create-training-job \
  --cli-input-json file://sagemaker_training/training_job_config.json \
  --region ap-northeast-2
```

### 상태 확인
```bash
aws sagemaker describe-training-job \
  --training-job-name densenet121-mimic-cxr-v1 \
  --region ap-northeast-2 \
  --query '{Status: TrainingJobStatus, Secondary: SecondaryStatus, Duration: TrainingTimeInSeconds}'
```

### 로그 확인 (CloudWatch)
```bash
aws logs get-log-events \
  --log-group-name /aws/sagemaker/TrainingJobs \
  --log-stream-name densenet121-mimic-cxr-v1/algo-1-XXXXXXXXXX \
  --region ap-northeast-2
```

### 작업 중지 (필요 시)
```bash
aws sagemaker stop-training-job \
  --training-job-name densenet121-mimic-cxr-v1 \
  --region ap-northeast-2
```

### 결과 다운로드
```bash
# 모델 아티팩트
aws s3 cp s3://pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an/output/densenet121-mimic-cxr-v1/output/model.tar.gz ./

# 압축 해제하면 best_model.pth + results.json
tar -xzf model.tar.gz
```

## 재실행 시 주의사항
- 작업 이름은 고유해야 함 → 재실행 시 `densenet121-mimic-cxr-v2` 등으로 변경
- training_job_config.json의 TrainingJobName 수정 후 같은 CLI 명령 실행
- 코드 수정 시: train.py 수정 → `tar -czf sourcedir.tar.gz train.py` → S3 재업로드

## 2-Stage Fine-tuning 설명
- **Stage 1 (에폭 1~5)**: DenseNet-121의 feature extractor 동결, 마지막 classifier만 학습
  - ImageNet에서 배운 이미지 특징 추출 능력을 보존
  - classifier만 빠르게 의료 영상 14개 질환에 적응
  - Learning Rate: 1e-4
- **Stage 2 (에폭 6~30)**: 전체 네트워크 fine-tuning
  - Feature extractor도 의료 영상에 맞게 미세 조정
  - Learning Rate: 1e-5 (Stage 1의 1/10, 기존 학습 파괴 방지)

## 스팟 체크포인트 동작
1. 매 에폭 끝에 `/opt/ml/checkpoints/checkpoint.pth` 저장
2. SageMaker가 주기적으로 S3로 동기화
3. 스팟 중단 시 → 새 인스턴스 할당 → S3에서 체크포인트 복원 → 이어서 학습
4. 최대 손실: 1에폭분 학습 (마지막 체크포인트 이후)

## 비용
- ml.g5.xlarge 스팟: ~$0.42/hr
- 예상 학습 시간: 2~3시간
- 예상 총비용: ~$1.0~1.3 (약 1,300~1,700원)
- 데이터 다운로드(S3→인스턴스): 같은 리전이라 무료
