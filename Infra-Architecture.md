# 멀티모달 임상 의사결정 지원 시스템 — 인프라 설계

> 목적: ECG + CXR + 혈액검사 3개 모달을 AWS에 배포하여 중앙 오케스트레이터(Bedrock Agent)가 능동적으로 호출
> 핵심 흐름: 환자 정보 → Bedrock Agent 판단 → 모달 순차 호출 → 종합 진단

---

## 전체 시스템 구조

```
                    ┌─────────────────────────┐
                    │     Bedrock Agent       │
                    │   (중앙 오케스트레이터)      │
                    │   - Claude 기반 LLM      │
                    │   - 검사 판단 + 종합        │
                    └─────┬─────┬─────┬───────┘
                          │     │     │
              tool 호출   │     │     │   tool 호출
                    ┌─────▼──┐ ┌▼────▼──┐ ┌──────┐
                    │  ECG   │ │  CXR   │ │ 혈액  │
                    │  모달  │ │  모달  │ │ 모달  │
                    └───┬────┘ └───┬────┘ └──┬───┘
                        │         │          │
                    ┌───▼─────────▼──────────▼───┐
                    │          S3 버킷            │
                    │  ecg/ cxr/ lab/ models/    │
                    └────────────────────────────┘
```

## 3개 모달 개요

| 모달 | 입력 | 모델 | 출력 | GPU 필요 |
|------|------|------|------|:--------:|
| ECG (심전도) | 파형 npy + 나이/성별 | S4/1D-CNN (PyTorch) | 24개 질환 확률 | ✅ |
| CXR (흉부 X-ray) | DICOM/PNG 이미지 | CNN (ResNet/DenseNet) | 폐부종, 기흉 등 | ✅ |
| 혈액검사 (Lab) | 수치 JSON (칼륨, BNP 등) | 규칙 기반 + XGBoost | 이상 수치 플래그 | ❌ |

---

## 능동형 호출 흐름 (시나리오)

```
Step 1: 환자 도착 → 기본 정보 입력
  {age: 72, gender: F, 증상: "흉통, 호흡곤란", 과거력: ["고혈압"]}

Step 2: Bedrock Agent 첫 번째 판단
  "흉통 + 호흡곤란 → ECG 먼저"
  → 의료진에게 "ECG 촬영 권고" 알림
  → 촬영 완료 → ECG 모달 호출

Step 3: ECG 결과 → 두 번째 판단
  ECG: {심방세동: 87%, 고칼륨혈증: 45%, 심부전: 72%}
  "고칼륨혈증 의심 → 혈액검사 필요"
  → 혈액검사 모달 호출

Step 4: 혈액 결과 → 세 번째 판단
  Lab: {칼륨: 6.2↑, BNP: 1200↑, 크레아티닌: 2.8↑}
  "심부전 + BNP 상승 → CXR로 폐부종 확인"
  → CXR 모달 호출

Step 5: CXR 결과 → 최종 종합
  CXR: {폐부종: 78%, 심비대: 65%}
  
  최종: "급성 심부전 악화 + 심방세동 + 고칼륨혈증
         → 긴급 조치 권고: 이뇨제, 심장내과 협진, 전해질 모니터링"
```

---

## 공통 구성 요소

모든 옵션에서 동일한 부분:

```
[S3 버킷: clinical-ai-data]
  ecg/
    waveforms/       ← ECG 파형 npy (158K개, ~7.2GB)
    model/           ← ECG 모델 가중치 (~50MB)
  cxr/
    images/          ← CXR 이미지 (DICOM/PNG)
    model/           ← CXR 모델 가중치 (~200MB)
  lab/
    model/           ← 혈액검사 모델 (~5MB)
  test_cases/        ← 데모용 시나리오별 테스트 케이스

[Bedrock Agent] (중앙 오케스트레이터)
  - Claude 기반 LLM
  - 3개 모달을 "tool"로 등록
  - 환자 증상 기반으로 어떤 모달을 호출할지 판단
  - 이전 모달 결과를 보고 다음 모달 호출 결정
  - 모든 결과를 종합하여 최종 판단
```

---

## 옵션 1: SageMaker Endpoint (추천 ⭐)

### 아키텍처

```
환자 정보 입력
      │
      ▼
┌─────────────────┐
│  Bedrock Agent  │  "흉통+호흡곤란 → ECG 분석 필요"
│  (중앙 오케스트) │
└────────┬────────┘
         │ ool 호출t
         ▼
┌─────────────────┐     ┌──────────┐
│  SageMaker      │────→│  S3      │
│  Endpoint       │←────│ (파형npy)│
│                 │     └──────────┘
│  - PyTorch 모델 │
│  - GPU (ml.g4dn)│
│  - 실시간 추론     │
└────────┬────────┘
         │ JSON 응답

         ▼
┌─────────────────┐
│  Bedrock Agent  │  "심방세동 87%, 고칼륨혈증 45%
│  결과 수신      │   → 혈액검사 권고"
└─────────────────┘
```

### 구성 상세

| 구성 요소 | 설정 | 비고 |
|----------|------|------|
| SageMaker Model | PyTorchModel | model.tar.gz (코드+가중치) |
| Instance | ml.g4dn.xlarge | GPU 1개, 4 vCPU, 16GB RAM |
| Endpoint | 실시간 (Real-time) | 응답 ~0.5초 |
| 입력 | JSON: {age, gender, ecg_s3_path} | |
| 출력 | JSON: {predictions, alerts, embedding} | |
| Bedrock 연동 | Agent Action Group | Lambda 프록시로 연결 |

### 배포 흐름

```
1. 모델 패키징
   model.tar.gz
     ├── model.pt          (학습된 가중치)
     ├── inference.py       (추론 코드)
     └── requirements.txt   (wfdb, resampy, torch)
   
   ※ urgency_weights.npy는 학습 단계에서만 사용 (손실 함수 가중치)
      추론 패키지에 포함하지 않음. 긴급도 판단은 Bedrock Agent가 수행.

2. SageMaker Endpoint 생성
   → PyTorchModel 등록
   → Endpoint Configuration (ml.g4dn.xlarge)
   → Endpoint 배포

3. Bedrock Agent 연동
   → Action Group 생성
   → Lambda 프록시 함수 (Agent → SageMaker 호출)
   → OpenAPI 스키마 등록
---

## 모달별 배포 흐름 상세

### ECG 모달

```
[데이터 소스]
MIMIC-IV ECG 파형 (.npy) → S3 ecg/waveforms/
MIMIC-IV patients.csv    → 나이/성별

[모델 패키징]
model.tar.gz
  ├── model.pt           (S4/1D-CNN 가중치)
  ├── inference.py
  └── requirements.txt   (wfdb, resampy, torch)

[배포]
→ SageMaker Endpoint (ml.g4dn.xlarge, GPU)

[입력]  {age, gender, ecg_s3_path}
        └── inference.py가 S3에서 .npy 파형 직접 읽기

[출력]
{
  "predictions": {"atrial_fibrillation": 0.87, "heart_failure": 0.72, ...},
  "abnormal_flags": {"heart_rate": {"value": 142, "status": "CRITICAL_HIGH"}}
}
```

### CXR 모달 (흉부 X-ray)

```
[데이터 소스]
CXR 이미지 (DICOM/PNG) → S3 cxr/images/
MIMIC-IV patients.csv  → 나이/성별

[모델 패키징]
model.tar.gz
  ├── model.pt           (ResNet/DenseNet 가중치)
  ├── inference.py
  └── requirements.txt   (torchvision, Pillow, pydicom)

[배포]
→ SageMaker Endpoint (ml.g4dn.xlarge, GPU)

[입력]  {age, gender, cxr_s3_path}
        └── inference.py가 S3에서 DICOM/PNG 읽기 → PNG 변환 후 CNN 입력

[출력]
{
  "predictions": {"pulmonary_edema": 0.78, "cardiomegaly": 0.65, ...},
  "abnormal_flags": {"pulmonary_edema": {"value": 0.78, "status": "HIGH"}}
}
```

### Lab 모달 (혈액검사)

```
[데이터 소스]
MIMIC-IV labevents.csv   → WBC, Hemoglobin, Platelet, Creatinine,
                            BUN, Sodium, Potassium, Glucose, AST, Albumin
MIMIC-IV chartevents.csv → Heart Rate, Temperature, MAP
MIMIC-IV patients.csv    → 나이

※ 실제 병원 환경: EMR 시스템에서 자동 수집
  데모/PoC 환경: MIMIC-IV에서 patient_id 기준으로 수치 추출 후
                S3 test_cases/에 JSON으로 저장해두고 사용

[모델 패키징]
model.tar.gz
  ├── final_ensemble_model.joblib  (XGBoost+LightGBM+CatBoost)
  ├── label_encoder.joblib
  ├── inference.py
  └── requirements.txt   (scikit-learn, xgboost, lightgbm, catboost, joblib)

[배포]
→ SageMaker Endpoint (ml.t3.medium, CPU — GPU 불필요)

[입력]  {age, wbc, hemoglobin, platelet, creatinine, bun,
         sodium, potassium, glucose, ast, albumin,
         heart_rate, temperature, map}
        ※ S3 파일 읽기 없음 — JSON 수치값 직접 수신

[출력]
{
  "predicted_group": "Sepsis_Group",
  "probabilities": {"Sepsis_Group": 0.72, "Cardio_Group": 0.18, ...},
  "abnormal_flags": {
    "potassium":  {"value": 6.1, "status": "CRITICAL_HIGH"},
    "creatinine": {"value": 2.8, "status": "HIGH"}
  }
}
```

### 3개 모달 비교

| | ECG | CXR | Lab |
|--|:--:|:--:|:--:|
| 입력 | S3 .npy 파형 | S3 DICOM/PNG | JSON 수치값 직접 |
| 데이터 소스 | MIMIC-IV ECG | CXR 이미지 | MIMIC-IV labevents + chartevents |
| GPU | ✅ 필요 | ✅ 필요 | ❌ 불필요 |
| 인스턴스 | ml.g4dn.xlarge | ml.g4dn.xlarge | ml.t3.medium |
| 추론 시간 | ~0.5초 | ~0.5초 | ~0.1초 |
| 모델 형식 | .pt (PyTorch) | .pt (PyTorch) | .joblib (sklearn) |

---

### inference.py (SageMaker용)

### inference.py (SageMaker용)

```python
def model_fn(model_dir):
    """모델 로딩"""
    model = ECGClassifier(backbone)
    model.load_state_dict(torch.load(f"{model_dir}/model.pt"))
    return model.eval()

def input_fn(request_body, content_type):
    """입력 파싱: S3에서 파형 읽기"""
    data = json.loads(request_body)
    # S3에서 npy 로딩
    signal = load_from_s3(data['ecg_s3_path'])
    age_norm = (data['age'] - 18) / 83
    gender_enc = 1.0 if data['gender'] == 'M' else 0.0
    return signal, np.array([age_norm, gender_enc])

def predict_fn(input_data, model):
    """추론"""
    signal, demo = input_data
    # 전처리 + 4 chunk 예측 평균
    predictions = run_inference(model, signal, demo)
    return predictions

def output_fn(predictions, accept):
    """결과 JSON 반환"""
    return json.dumps({
        "predictions": [...],
        "alerts": [...],
        "embedding": [...]
    })
```

### Bedrock Agent 연동 (Lambda 프록시)

```python
# Lambda: Bedrock Agent → SageMaker Endpoint
def lambda_handler(event, context):
    # Bedrock Agent에서 받은 파라미터
    age = event['parameters']['age']
    gender = event['parameters']['gender']
    ecg_path = event['parameters']['ecg_s3_path']
    
    # SageMaker Endpoint 호출
    response = sagemaker_runtime.invoke_endpoint(
        EndpointName='ecg-modal-endpoint',
        Body=json.dumps({
            'age': age, 'gender': gender,
            'ecg_s3_path': ecg_path
        }),
        ContentType='application/json'
    )
    
    return json.loads(response['Body'].read())
```

### 비용 (월 기준)

| 항목 | 비용 |
|------|------|
| ml.g4dn.xlarge (24시간 상시) | ~$380/월 |
| ml.g4dn.xlarge (하루 8시간) | ~$127/월 |
| S3 (10GB) | ~$0.23/월 |
| Lambda (프록시) | ~$1/월 |
| Bedrock Agent | 호출당 과금 |

### 장단점

| 장점 | 단점 |
|------|------|
| GPU 사용 → 빠른 추론 (~0.5초) | 상시 운영 시 비용 높음 |
| 모델 크기 제한 없음 | SageMaker 설정 복잡도 |
| 오토스케일링 지원 | |
| Bedrock Agent와 자연스러운 연동 | |

---

## 옵션 2: Lambda + API Gateway

### 아키텍처

```
환자 정보 입력
      │
      ▼
┌─────────────────┐
│  Bedrock Agent  │
└────────┬────────┘
         │ tool 호출
         ▼
┌─────────────────┐
│  API Gateway    │
│  (REST API)     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌──────────┐     ┌──────────┐
│  Lambda         │────→│  S3      │     │  EFS     │
│  (CPU 추론)     │←────│ (파형npy)│     │ (모델)   │
│                 │────→│          │     │          │
│  - 10GB 메모리  │←────└──────────┘     └──────────┘
│  - 15분 타임아웃│
└────────┬────────┘
         │ JSON 응답
         ▼
┌─────────────────┐
│  Bedrock Agent  │
└─────────────────┘
```

### 구성 상세

| 구성 요소 | 설정 | 비고 |
|----------|------|------|
| Lambda | Python 3.11 | 컨테이너 이미지 배포 |
| 메모리 | 10,240 MB | CPU 추론에 충분 |
| 타임아웃 | 60초 | 추론 ~3-5초 |
| 스토리지 | EFS 마운트 | 모델 가중치 저장 |
| API Gateway | REST API | Bedrock Agent에서 호출 |

### Lambda 함수

```python
import torch, json, boto3, numpy as np

# 콜드스타트 시 모델 로딩 (EFS에서)
model = load_model('/mnt/efs/model.pt')

def handler(event, context):
    body = json.loads(event['body'])
    
    # S3에서 파형 읽기
    signal = load_npy_from_s3(body['ecg_s3_path'])
    
    # 인구통계
    demo = np.array([
        (body['age'] - 18) / 83,
        1.0 if body['gender'] == 'M' else 0.0
    ])
    
    # CPU 추론
    predictions = run_inference(model, signal, demo)
    
    return {
        'statusCode': 200,
        'body': json.dumps(predictions)
    }
```

### 비용 (월 기준)

| 항목 | 비용 |
|------|------|
| Lambda (1000회/일, 5초/회) | ~$15/월 |
| API Gateway | ~$3.50/월 |
| EFS (1GB) | ~$0.30/월 |
| S3 (10GB) | ~$0.23/월 |
| 합계 | ~$19/월 |

### 장단점

| 장점 | 단점 |
|------|------|
| 비용 매우 저렴 | GPU 없음 → 느림 (3~5초) |
| 서버리스 → 관리 불필요 | 콜드스타트 10~30초 |
| 사용한 만큼만 과금 | 모델 크기 제한 (EFS 필요) |
| 간단한 구성 | PyTorch 컨테이너 이미지 필요 |

---

## 옵션 3: EKS (Kubernetes)

### 아키텍처

```
환자 정보 입력
      │
      ▼
┌─────────────────┐
│  Bedrock Agent  │
└────────┬────────┘
         │ tool 호출
         ▼
┌─────────────────┐
│  ALB            │
│  (로드밸런서)    │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────┐
│  EKS Cluster                    │
│                                 │
│  ┌───────────┐  ┌───────────┐  │
│  │  ECG Pod  │  │  ECG Pod  │  │     ┌──────────┐
│  │  (GPU)    │  │  (GPU)    │  │────→│  S3      │
│  │  replica  │  │  replica  │  │←────│ (파형npy)│
│  └───────────┘  └───────────┘  │     └──────────┘
│                                 │
│  ┌───────────┐                  │
│  │  CXR Pod  │  (다른 모달도   │
│  │           │   같은 클러스터) │
│  └───────────┘                  │
└─────────────────────────────────┘
```

### 구성 상세

| 구성 요소 | 설정 | 비고 |
|----------|------|------|
| EKS Cluster | 1.28+ | 관리형 Kubernetes |
| Node Group | g4dn.xlarge × 2 | GPU 노드 |
| ECG Deployment | replicas: 2 | 고가용성 |
| Service | ClusterIP + ALB Ingress | 외부 노출 |
| HPA | CPU 70% 기준 오토스케일 | 2~4 pods |

### Kubernetes 매니페스트

```yaml
# ecg-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ecg-modal
spec:
  replicas: 2
  template:
    spec:
      containers:
      - name: ecg-inference
        image: ECR_REPO/ecg-modal:latest
        ports:
## 옵션 비교 요약 (3개 모달 기준)

| 항목 | SageMaker | Lambda | EKS |
|------|:---------:|:------:|:---:|
| 추론 속도 | ~0.5초 | ECG 3-5초, Lab 0.5초 | ~0.5초 |
| GPU | ✅ (ECG, CXR) | ❌ | ✅ |
| 월 비용 (3모달) | ~$400-800 | ~$40-60 | ~$900-1200 |
| 구성 난이도 | 중 | 하 | 상 |
| 오토스케일 | ✅ | ✅ (자동) | ✅ |
| 콜드스타트 | 없음 (상시) | 10~30초 | 없음 |
| 멀티모달 통합 | 모달별 Endpoint | 모달별 Lambda | 한 클러스터 |
| Bedrock 연동 | Agent Action Group | Agent Action Group | Agent Action Group |
| 추천 단계 | PoC/프로덕션 | PoC/데모 | 프로덕션 |

### 3개 모달 비용 상세

## 추천 전략

```
Phase 1 (지금): 로컬에서 ECG 모델 학습 + 평가
Phase 2 (데모): Lambda × 3 모달 배포 → 비용 ~$41/월
               Bedrock Agent에 3개 tool 등록
               테스트 케이스로 능동형 흐름 시연
Phase 3 (PoC):  SageMaker × 3 Endpoint → GPU 추론
               실시간 응답 3초 이내 달성
Phase 4 (프로덕션): EKS → 멀티모달 한 클러스터
               고가용성, CI/CD, 모니터링
```

### Bedrock Agent Tool 등록 (3개 모달)

```json
{
  "tools": [
    {
      "name": "analyze_ecg",
      "description": "ECG 파형을 분석하여 24개 심혈관/비심혈관 질환을 예측합니다",
      "parameters": {
        "age": "환자 나이",
        "gender": "환자 성별 (M/F)",
        "ecg_s3_path": "ECG 파형 파일 S3 경로"
      }
    },
    {
      "name": "analyze_cxr",
      "description": "흉부 X-ray 이미지를 분석하여 폐부종, 기흉 등을 예측합니다",
      "parameters": {
        "age": "환자 나이",
        "gender": "환자 성별",
        "cxr_s3_path": "CXR 이미지 S3 경로"
      }
    },
    {
      "name": "analyze_lab",
      "description": "혈액검사 수치를 분석하여 이상 소견을 판별합니다",
      "parameters": {
        "patient_id": "환자 ID",
        "lab_values": "혈액검사 수치 JSON (칼륨, BNP, 크레아티닌 등)"
      }
    }
  ]
}
```

현재 단계에서는 ECG 모델 학습에 집중하고, 배포는 Phase 2(Lambda)로 빠르게 데모 가능한 형태를 먼저 만드는 게 효율적입니다.

| 모달 | 메모리 | 실행시간 | 비용 (1000회/일) |
|------|-------|---------|:-----------:|
| ECG | 10GB | ~5초 | $15/월 |
| CXR | 10GB | ~5초 | $15/월 |
| Lab | 1GB | ~0.5초 | $1/월 |
| API Gateway × 3 | | | $10/월 |
| 합계 | | | ~$41/월 |

**EKS (한 클러스터)**

| 구성 | 인스턴스 | 비용 |
|------|---------|:----:|
| EKS 클러스터 | | $73/월 |
| GPU 노드 × 2 | g4dn.xlarge | $760/월 |
| CPU 노드 × 1 | m5.large (Lab용) | $70/월 |
| ALB | | $22/월 |
| 합계 | | ~$925/월 |
apiVersion: v1
kind: Service
metadata:
  name: ecg-modal-service
spec:
  type: ClusterIP
  ports:
  - port: 80
    targetPort: 8080
```

### FastAPI 서버 (컨테이너 내부)

```python
from fastapi import FastAPI
import torch, boto3

app = FastAPI()
model = load_model('/models/best_model.pt')

@app.post("/predict")
async def predict(request: ECGRequest):
    signal = load_from_s3(request.ecg_s3_path)
    demo = preprocess_demographics(request.age, request.gender)
    predictions = run_inference(model, signal, demo)
    return predictions

@app.get("/health")
async def health():
    return {"status": "healthy"}
```

### 비용 (월 기준)

| 항목 | 비용 |
|------|------|
| EKS 클러스터 | ~$73/월 |
| g4dn.xlarge × 2 (24시간) | ~$760/월 |
| ALB | ~$22/월 |
| ECR | ~$1/월 |
| S3 (10GB) | ~$0.23/월 |
| 합계 | ~$856/월 |

### 장단점

| 장점 | 단점 |
|------|------|
| 멀티 모달 통합 배포 (ECG+CXR+EHR 한 클러스터) | 비용 가장 높음 |
| GPU + 오토스케일링 | Kubernetes 운영 복잡도 |
| 고가용성 (replica) | 초기 설정 시간 |
| CI/CD 파이프라인 구축 용이 | 소규모에는 오버엔지니어링 |
| 프로덕션 레디 | |

---

## 옵션 비교 요약

| 항목 | SageMaker | Lambda | EKS |
|------|:---------:|:------:|:---:|
| 추론 속도 | ~0.5초 | ~3-5초 | ~0.5초 |
| GPU | ✅ | ❌ | ✅ |
| 월 비용 | ~$130-380 | ~$19 | ~$856 |
| 구성 난이도 | 중 | 하 | 상 |
| 오토스케일 | ✅ | ✅ (자동) | ✅ |
| 콜드스타트 | 없음 (상시) | 10~30초 | 없음 |
| 멀티모달 통합 | 모달별 Endpoint | 모달별 Lambda | 한 클러스터 |
| Bedrock 연동 | Agent Action Group | Agent Action Group | Agent Action Group |
| 추천 단계 | PoC/프로덕션 | PoC/데모 | 프로덕션 |

---

## 추천 전략

```
Phase 1 (지금): 로컬에서 모델 학습 + 평가
Phase 2 (데모): Lambda로 빠르게 배포 → 비용 $19/월
Phase 3 (PoC):  SageMaker Endpoint → GPU 추론, Bedrock Agent 연동
Phase 4 (프로덕션): EKS → 멀티모달 통합, 고가용성
```

현재 단계에서는 모델 학습에 집중하고, 배포는 Phase 2(Lambda)로 빠르게 데모 가능한 형태를 먼저 만드는 게 효율적입니다.

---

## 옵션별 개념 정리

### 옵션 1: SageMaker Endpoint

**SageMaker가 뭔가**

AWS가 ML 모델을 배포하기 위해 만든 전용 서비스다. 모델 파일을 올리면 AWS가 서버 관리, 스케일링, 헬스체크를 다 해준다.

**핵심 흐름**

```
model.tar.gz (모델+코드 묶음)
      │
      ▼
SageMaker Model 등록
      │
      ▼
Endpoint Configuration (어떤 인스턴스 쓸지)
      │
      ▼
Endpoint 생성 (실제 서버 띄움)
      │
      ▼
HTTP POST 요청 → 추론 결과 반환
```

**이 프로젝트에서 동작 방식**

```
Bedrock Agent
    │ tool 호출
    ▼
Lambda (프록시)        ← Agent는 Lambda URL만 알면 됨
    │
    ▼
SageMaker Endpoint    ← 실제 GPU 서버에서 모델 추론
    │
    ▼
Lambda → Agent로 결과 반환
```

Lambda가 중간에 있는 이유: Bedrock Agent는 OpenAPI 스키마 기반으로 tool을 호출하는데, SageMaker Endpoint를 직접 tool로 등록하기 어려워서 Lambda가 변환 역할을 한다.

- 장점: GPU 상시 대기 → 응답 0.5초, 모델 크기 제한 없음
- 단점: 서버가 항상 켜져 있어서 월 $380 고정 비용

---

### 옵션 2: Lambda + API Gateway

**Lambda가 뭔가**

코드만 올리면 AWS가 요청 올 때만 서버를 켜서 실행하고 끄는 서버리스 서비스다. 서버가 없을 때는 비용이 0이다.

**핵심 흐름**

```
요청 없음 → 서버 없음 (비용 0)
      │
요청 도착
      │
      ▼
Lambda 컨테이너 시작 (콜드스타트 10~30초)
      │
      ▼
모델 로딩 (EFS에서) + 추론
      │
      ▼
결과 반환 후 컨테이너 대기 (웜스타트 준비)
```

**API Gateway가 뭔가**

Lambda 앞에 붙는 HTTP 엔드포인트다. `https://xxx.execute-api.amazonaws.com/predict` 같은 URL을 만들어줘서 Bedrock Agent가 HTTP로 호출할 수 있게 해준다.

**EFS가 왜 필요한가**

Lambda는 기본 스토리지가 512MB라 PyTorch 모델을 담기 어렵다. EFS(Elastic File System)를 마운트하면 `/mnt/efs/model.pt`처럼 파일시스템처럼 접근할 수 있다.

**이 프로젝트에서 동작 방식**

```
Bedrock Agent
    │ tool 호출 (HTTP POST)
    ▼
API Gateway
    │
    ▼
Lambda (CPU로 추론, EFS에서 모델 로딩)
    │
    ▼
결과 반환
```

- 장점: 월 $19, 관리 불필요, 사용한 만큼만 과금
- 단점: GPU 없어서 ECG/CXR 추론 3~5초, 콜드스타트 문제

---

### 옵션 3: EKS (Kubernetes)

**EKS가 뭔가**

Kubernetes를 AWS에서 관리형으로 제공하는 서비스다. 컨테이너(Docker)를 여러 서버에 분산 배포하고 관리하는 오케스트레이션 플랫폼이다.

**핵심 구조**

```
EKS Cluster (전체 관리 단위)
  │
  ├── Node Group (실제 EC2 서버들)
  │     ├── g4dn.xlarge (GPU 서버 1)
  │     └── g4dn.xlarge (GPU 서버 2)
  │
  └── Pod (컨테이너 실행 단위)
        ├── ECG Pod (replica 2개)  ← 서버 2대에 분산
        ├── CXR Pod (replica 2개)
        └── Lab Pod (replica 1개)
```

**Pod가 뭔가**

Docker 컨테이너를 감싸는 Kubernetes의 최소 실행 단위다. ECG 모달 FastAPI 서버가 컨테이너로 패키징되어 Pod 안에서 실행된다.

**ALB가 왜 필요한가**

Pod가 여러 개 있을 때 요청을 분산시켜주는 로드밸런서다. Bedrock Agent는 ALB URL 하나만 알면 되고, ALB가 알아서 여유 있는 Pod로 라우팅한다.

**HPA가 뭔가**

Horizontal Pod Autoscaler. CPU 사용률이 70% 넘으면 Pod를 자동으로 늘리고, 줄어들면 다시 줄인다.

**이 프로젝트에서 동작 방식**

```
Bedrock Agent
    │ tool 호출
    ▼
ALB (로드밸런서)
    │
    ├──→ ECG Pod 1 (GPU)
    ├──→ ECG Pod 2 (GPU)  ← 트래픽 분산
    │
    ▼
FastAPI 서버 (컨테이너 내부)
    │
    ▼
결과 반환
```

- 장점: 3개 모달 한 클러스터 통합, 고가용성, CI/CD 구축 용이
- 단점: 월 $856, Kubernetes 운영 복잡도, 소규모엔 오버엔지니어링

---

### 3개 옵션 핵심 차이 한 줄 요약

```
SageMaker: "ML 전용 서버 상시 대기"  → 빠르고 간단, 비용 중간
Lambda:    "요청 올 때만 실행"        → 느리고 싸고 관리 없음
EKS:       "컨테이너 클러스터 운영"   → 빠르고 유연, 비용 높고 복잡
```
