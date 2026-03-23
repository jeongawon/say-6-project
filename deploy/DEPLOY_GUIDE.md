# Lambda 배포 가이드

## 개요
흉부 X-Ray 모달 v2를 Lambda Container Image로 배포.
오케스트레이터가 `lambda.invoke()` 한 번으로 전체 6-Layer 파이프라인 실행.

## 아키텍처
```
오케스트레이터 → Lambda (chest-xray-modal-v2) → JSON 응답
                  │
                  ├── S3에서 CXR 이미지 다운로드
                  ├── Layer 1: U-Net 세그멘테이션 (CPU)
                  ├── Layer 2: DenseNet-121 + YOLOv8 (CPU)
                  ├── Layer 3: Clinical Logic (순수 코드)
                  ├── Layer 4: Cross-Validation (순수 코드)
                  ├── Layer 5: RAG - FAISS (CPU)
                  ├── Layer 6: Bedrock API 호출
                  └── 어노테이션 이미지 S3 업로드
```

## Lambda 설정
| 항목 | 값 |
|------|-----|
| 함수명 | chest-xray-modal-v2 |
| 패키지 타입 | Container Image (ECR) |
| 메모리 | 4096 MB |
| 타임아웃 | 300초 (5분) |
| 아키텍처 | x86_64 |
| Role | say-2-lambda-bedrock-role (Bedrock + S3 접근) |
| 임시 스토리지 | 2048 MB (/tmp에 모델 캐시) |

## 환경 변수
| 키 | 값 | 설명 |
|---|---|---|
| MODEL_BUCKET | pre-project-practice-hyunwoo-...  | 모델 가중치 S3 버킷 |
| MODEL_PREFIX | models | 모델 가중치 S3 prefix |
| RESULT_PREFIX | results | 결과 저장 S3 prefix |

## 배포 순서

### 1. ECR 리포지토리 생성
```python
ecr = boto3.client('ecr', region_name='ap-northeast-2')
ecr.create_repository(repositoryName='chest-xray-modal-v2')
```

### 2. Docker 이미지 빌드 & 푸시
```bash
# ECR 로그인
aws ecr get-login-password --region ap-northeast-2 | \
  docker login --username AWS --password-stdin 666803869796.dkr.ecr.ap-northeast-2.amazonaws.com

# 빌드
docker build -t chest-xray-modal-v2 -f deploy/Dockerfile .

# 태그
docker tag chest-xray-modal-v2:latest \
  666803869796.dkr.ecr.ap-northeast-2.amazonaws.com/chest-xray-modal-v2:latest

# 푸시
docker push \
  666803869796.dkr.ecr.ap-northeast-2.amazonaws.com/chest-xray-modal-v2:latest
```

### 3. Lambda 함수 생성
```python
lambda_client = boto3.client('lambda', region_name='ap-northeast-2')

lambda_client.create_function(
    FunctionName='chest-xray-modal-v2',
    Role='arn:aws:iam::666803869796:role/say-2-lambda-bedrock-role',
    PackageType='Image',
    Code={
        'ImageUri': '666803869796.dkr.ecr.ap-northeast-2.amazonaws.com/chest-xray-modal-v2:latest'
    },
    Timeout=300,
    MemorySize=4096,
    EphemeralStorage={'Size': 2048},
    Environment={
        'Variables': {
            'MODEL_BUCKET': 'pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an',
            'MODEL_PREFIX': 'models',
            'RESULT_PREFIX': 'results'
        }
    },
    Architectures=['x86_64']
)
```

### 4. 모델 가중치 S3 업로드
```python
# DenseNet-121 (이미 학습 완료)
s3.upload_file('densenet121.pth', BUCKET, 'models/densenet121.pth')

# U-Net (학습 후)
s3.upload_file('unet_lung_heart.pth', BUCKET, 'models/unet_lung_heart.pth')

# YOLOv8 (학습 후)
s3.upload_file('yolov8_vindr.pt', BUCKET, 'models/yolov8_vindr.pt')
```

### 5. 테스트 호출
```python
import json

response = lambda_client.invoke(
    FunctionName='chest-xray-modal-v2',
    InvocationType='RequestResponse',
    Payload=json.dumps({
        'patient_id': 'p10000032',
        'cxr_image_s3_path': 's3://pre-project-practice-hyunwoo-.../data/p10_pa/files/p10/p10000032/...',
        'patient_info': {
            'age': 67, 'sex': 'M',
            'chief_complaint': '흉통, 호흡곤란, 기침',
            'vitals': {'HR': 110, 'BP': '90/60', 'SpO2': 88, 'RR': 28, 'Temp': 38.2}
        },
        'prior_results': [
            {'modal': 'ecg', 'summary': '정상 동성리듬, STEMI 아님'}
        ]
    })
)

result = json.loads(response['Payload'].read())
print(json.dumps(json.loads(result['body']), indent=2, ensure_ascii=False))
```

## Cold Start vs Warm Start
| | Cold Start | Warm Start |
|---|---|---|
| 발생 시점 | 첫 호출 / 15분 이상 미사용 후 | 연속 호출 시 |
| 모델 다운로드 | S3 → /tmp (~5-10초) | 스킵 (캐시) |
| 모델 로드 | PyTorch 로드 (~3-5초) | 스킵 (메모리 유지) |
| 추론 | ~15-25초 | ~15-25초 |
| **총 소요** | **~25-40초** | **~15-25초** |

## 비용
| 항목 | 금액 |
|------|------|
| 호출 1회 (30초, 4096MB) | ~$0.002 (약 2.6원) |
| 하루 10회 | ~$0.02 (약 26원) |
| 월 300회 | ~$0.60 (약 780원) |
| 미사용 시 | $0 |

## 모델 가중치 관리
모델은 Container Image에 넣지 않고 **S3에 별도 저장**하는 이유:
1. 모델 재학습 시 이미지 재빌드 불필요 — S3만 교체
2. Container Image 크기 절감 (~3GB → ~1.5GB)
3. 여러 버전 모델을 환경 변수로 전환 가능

---

## 레이어별 독립 Lambda 배포 (현재 운영 방식)

위의 통합 Lambda는 최종 오케스트레이터용 설계이고, 현재는 **레이어별 독립 Lambda 엔드포인트**로 각각 배포하여 개별 테스트 중.

### 배포 현황

| Layer | Lambda 함수명 | ECR 리포지토리 | Function URL | 이미지 크기 | 메모리 |
|-------|-------------|---------------|-------------|------------|--------|
| Layer 1 (Segmentation) | layer1-segmentation | layer1-segmentation | `https://jwhljyevn3hm44nhvs5zcdstmi0tmuvi.lambda-url.ap-northeast-2.on.aws/` | ~1.5GB | 3072MB |
| Layer 2 (Detection) | layer2-detection | layer2-detection | `https://pk67s3qrp3b3xluqkcp6neqly40kduol.lambda-url.ap-northeast-2.on.aws/` | ~1.5GB | 3072MB |
| Layer 3 (Clinical Logic) | layer3-clinical-logic | layer3-clinical-logic | `https://ihq6gjldxbulfke5xd2xexnoqe0vyrxt.lambda-url.ap-northeast-2.on.aws/` | ~200MB | 256MB |

### Layer 3 배포 상세

Layer 3은 순수 Python(GPU/PyTorch 불필요)이라 다른 레이어 대비 매우 가볍다.

| 항목 | 값 |
|------|-----|
| 함수명 | layer3-clinical-logic |
| 패키지 타입 | Container Image (ECR) |
| 베이스 이미지 | public.ecr.aws/lambda/python:3.12 |
| 의존성 | numpy만 |
| 이미지 크기 | ~200MB (Layer 1/2의 1/7) |
| 메모리 | 256MB |
| 타임아웃 | 30초 |
| 임시 스토리지 | 512MB |
| Cold Start | ~2초 |
| 처리 시간 | ~0.0003초/건 |
| 비용 | 호출당 ~$0.0001 (0.1원) |

### Layer 3 배포 스크립트

```bash
# 전체 배포 (소스 복사 → ECR → Docker → Lambda → Function URL)
python deploy/deploy_layer3.py

# Function URL만 확인
python deploy/deploy_layer3.py --step url

# 소스 코드만 빌드 디렉토리에 복사
python deploy/deploy_layer3.py --step source
```

### Docker 빌드 주의사항

Lambda는 OCI provenance attestation을 지원하지 않으므로 반드시 `--provenance=false` 플래그 필요:

```bash
docker build --provenance=false --platform linux/amd64 -t <tag> .
```

### Layer 3 API 액션

| action | 설명 | 예시 |
|--------|------|------|
| list_scenarios | 사용 가능한 시나리오 목록 | `{"action":"list_scenarios"}` |
| scenario | 미리 정의된 시나리오 실행 (chf, pneumonia, tension_pneumo, normal) | `{"action":"scenario","scenario":"chf"}` |
| random | 랜덤 입력 생성 후 실행 | `{"action":"random"}` |
| custom | 사용자 커스텀 입력 | `{"action":"custom","input":{...}}` |

### 위험도 3단계 분류

| 등급 | 조건 | 예시 |
|------|------|------|
| CRITICAL | alert=True (긴장성 기흉, ETT 이탈 등) | Tension Pneumothorax |
| URGENT | severity "severe"인 소견 2개 이상 | CHF (Cardiomegaly severe + Edema severe) |
| ROUTINE | 그 외 | Pneumonia, Normal |
