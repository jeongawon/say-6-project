# Design: Dr. AI Radiologist 아키텍처 v2 고도화

> 작성일: 2026-03-24
> 레벨: Dynamic
> 상태: Design
> 아키텍처: Option C (실용적 균형)
> Plan 참조: docs/01-plan/features/architecture-v2.plan.md

---

## Context Anchor

| 항목 | 내용 |
|------|------|
| **WHY** | 7개 Lambda의 PyTorch 중복 배포로 인한 비용·성능 비효율을 해소하고, Function URL 공개 노출 보안 문제를 제거한다 |
| **WHO** | 프로젝트 6팀 (의료 AI 흉부 X-Ray 분석 시스템 개발) |
| **RISK** | ONNX 변환 시 추론 정확도 손실 (atol>1e-5), 기존 버킷 오염, Layer 코드 이식 누락 |
| **SUCCESS** | ONNX vs PyTorch 결과 atol≤1e-5, E2E 소견서 정상 생성, v1 엔드포인트 정상 유지 |
| **SCOPE** | deploy/v2/ 하위에 새 구조 생성. 기존 deploy/ 및 7개 Lambda는 절대 수정하지 않음 |

---

## 1. Overview

### 1.1 설계 목표
기존 7개 Lambda + PyTorch 구조를 2개 Lambda + ONNX Runtime + Step Functions로 통합한다.
Option C (실용적 균형) 아키텍처를 적용하여 `shared/`에 공용 모듈(result_store, config)만 추출하고,
나머지는 원본 설계를 최대한 유지한다.

### 1.2 선택된 아키텍처: Option C
- **shared/**: result_store.py, config.py (2개 파일만 공용화)
- **lambda_a/**: flat 파일 구조 (inference_seg/densenet/yolo 개별 파일)
- **lambda_b/**: 기존 L3/L5/L6 코드 디렉토리 복사
- Dockerfile에서 `COPY ../shared .`로 공용 모듈 주입

---

## 2. 디렉토리 구조

```
deploy/v2/
├─ shared/                          # 공용 모듈 (Lambda A/B 공유)
│   ├─ result_store.py              # Claim-Check 패턴 (S3ResultStore)
│   └─ config.py                    # AWS 리전, S3 버킷, 모델 경로 설정
│
├─ lambda_a/                        # Vision 통합 Lambda
│   ├─ Dockerfile
│   ├─ lambda_function.py           # task 분기 핸들러 (seg/densenet/yolo)
│   ├─ model_loader.py              # S3 Lazy Load + /tmp 캐시
│   ├─ inference_seg.py             # L1 세그멘테이션 로직 이식
│   ├─ inference_densenet.py        # L2 DenseNet 로직 이식
│   ├─ inference_yolo.py            # L2b YOLOv8 로직 이식
│   └─ requirements.txt             # onnxruntime, pillow, numpy, boto3
│
├─ lambda_b/                        # 분석 + 소견서 통합 Lambda
│   ├─ Dockerfile
│   ├─ lambda_function.py           # L3→L5→L6 순차 실행 핸들러
│   ├─ requirements.txt             # boto3, numpy, faiss-cpu, fastembed
│   ├─ clinical_logic/              # 기존 layer3 코드 복사
│   │   ├─ engine.py
│   │   ├─ clinical_engine.py
│   │   ├─ cross_validation.py
│   │   ├─ differential.py
│   │   ├─ models.py
│   │   ├─ thresholds.py
│   │   └─ rules/                   # 14개 질환 Rule
│   │       ├─ atelectasis.py
│   │       ├─ cardiomegaly.py
│   │       └─ ... (14개)
│   ├─ rag/                         # 기존 layer5 코드 복사
│   │   ├─ config.py
│   │   ├─ rag_service.py
│   │   └─ query_builder.py
│   └─ bedrock_report/              # 기존 layer6 코드 복사
│       ├─ config.py
│       ├─ report_generator.py
│       ├─ prompt_templates.py
│       └─ models.py
│
├─ step_functions/
│   └─ state_machine.json           # ASL 정의 (EXPRESS 타입)
│
└─ scripts/
    ├─ convert_to_onnx.py           # 3개 모델 PyTorch→ONNX 변환
    ├─ compare_results.py           # ONNX vs PyTorch 결과 비교
    └─ deploy.sh                    # ECR 빌드 + Lambda/StepFunctions 배포
```

---

## 3. 모듈 상세 설계

### 3.1 shared/config.py

```python
import os

class Config:
    REGION = os.environ.get("AWS_REGION", "ap-northeast-2")
    S3_BUCKET = os.environ.get("S3_BUCKET",
        "pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an")

    # ONNX 모델 S3 경로
    MODELS = {
        "seg": "models/onnx/unet.onnx",
        "densenet": "models/onnx/densenet.onnx",
        "yolo": "models/onnx/yolov8.onnx",
    }

    # /tmp 캐시 경로
    TMP_DIR = "/tmp"

    # Claim-Check 결과 저장 경로 접두사
    RESULT_PREFIX = "runs/"
```

### 3.2 shared/result_store.py

**인터페이스 설계**: `ResultStoreBase` ABC로 추상화, 현재는 `S3ResultStore` 구현.

```python
from abc import ABC, abstractmethod

class ResultStoreBase(ABC):
    @abstractmethod
    def save(self, run_id: str, stage: str, data: dict) -> str:
        """결과 저장 후 URI 반환"""
        pass

    @abstractmethod
    def load(self, uri: str) -> dict:
        """URI에서 결과 로드"""
        pass

class S3ResultStore(ResultStoreBase):
    def __init__(self, bucket: str, prefix: str = "runs/"):
        self.s3 = boto3.client("s3")
        self.bucket = bucket
        self.prefix = prefix

    def save(self, run_id, stage, data) -> str:
        key = f"{self.prefix}{run_id}/{stage}.json"
        self.s3.put_object(Bucket=self.bucket, Key=key,
            Body=json.dumps(data, ensure_ascii=False, default=str),
            ContentType="application/json")
        return f"s3://{self.bucket}/{key}"

    def load(self, uri: str) -> dict:
        parts = uri.replace("s3://", "").split("/", 1)
        obj = self.s3.get_object(Bucket=parts[0], Key=parts[1])
        return json.loads(obj["Body"].read())

def get_result_store(config) -> ResultStoreBase:
    return S3ResultStore(bucket=config.S3_BUCKET, prefix=config.RESULT_PREFIX)
```

### 3.3 lambda_a/model_loader.py

**전략**: S3에서 ONNX 모델을 `/tmp`로 다운로드, 글로벌 변수로 세션 캐시.

```python
_sessions = {}  # 글로벌 캐시 (Lambda 인스턴스 수명 동안 유지)

def get_model(task: str, config) -> ort.InferenceSession:
    if task in _sessions:
        return _sessions[task]

    s3_key = config.MODELS[task]
    local_path = f"{config.TMP_DIR}/{task}.onnx"

    if not os.path.exists(local_path):
        s3 = boto3.client("s3")
        s3.download_file(config.S3_BUCKET, s3_key, local_path)

    session = ort.InferenceSession(local_path, providers=["CPUExecutionProvider"])
    _sessions[task] = session
    return session
```

- **Cold start**: S3 다운로드 + ONNX 세션 생성 (모델당 수 초)
- **Warm start**: `_sessions` 캐시 히트 → 0초
- **/tmp 용량**: 3개 모델 총 ~134MB (512MB 한도 내 여유 378MB)

### 3.4 lambda_a/lambda_function.py

**핸들러 흐름**:
1. event에서 `task`, `image_s3_uri`, `run_id` 추출
2. `get_model(task)`로 ONNX 세션 로드
3. S3에서 이미지 로드 → PIL.Image
4. task에 따라 `inference_seg/densenet/yolo` 분기 실행
5. `result_store.save()`로 결과 S3에 저장
6. `{"status": "ok", "task": task, "result_uri": uri}` 반환

**입력 스키마**:
```json
{
  "task": "seg | densenet | yolo",
  "image_s3_uri": "s3://bucket/path/image.jpg",
  "run_id": "step-functions-execution-id"
}
```

**출력 스키마**:
```json
{
  "status": "ok | failed",
  "task": "seg | densenet | yolo",
  "result_uri": "s3://bucket/runs/{run_id}/{task}.json"
}
```

### 3.5 Lambda A 추론 모듈

#### inference_seg.py (L1 세그멘테이션)
- **이식 원본**: `deploy/layer1_segmentation/lambda_function.py`
- **변경**: `torch` 호출 → `session.run(None, {"image": input_array})[0]`
- **보존**: 이미지 전처리(resize 512×512, normalize), 마스크 후처리(argmax, 클래스별 분리), CTR 계산, CP angle 계산, 좌/우 폐 면적비, 중심선 보정(L/R 교차 픽셀 재분류)
- **출력**: `{"mask_base64", "measurements": {"ctr", "cp_angle_left/right", "lung_area_ratio", ...}, "class_areas", "processing_time"}`

#### inference_densenet.py (L2 DenseNet-121)
- **이식 원본**: `deploy/layer2_detection/lambda_function.py`
- **변경**: `torch` 호출 → ONNX Runtime
- **보존**: 이미지 전처리(resize 224×224, normalize), sigmoid 적용, threshold 판정
- **출력**: `{"predictions": [{"disease", "probability", "status"}], "processing_time"}`
- **질환 목록**: 14개 (Atelectasis, Cardiomegaly, Consolidation, Edema, ...)

#### inference_yolo.py (L2b YOLOv8)
- **이식 원본**: `deploy/layer2b_yolov8/lambda_function.py`
- **변경**: `ultralytics YOLO` 클래스 → ONNX Runtime 직접 추론
- **주의**: NMS 후처리를 직접 구현해야 할 수 있음 (export 옵션에 따라 다름)
- **출력**: `{"detections": [{"class", "confidence", "bbox": {"x1", "y1", "x2", "y2"}}], "processing_time"}`
- **클래스 목록**: 19개 VinDr 클래스

### 3.6 lambda_b/lambda_function.py

**핸들러 흐름**:
1. `parallel_results`에서 3개 Vision 결과 URI 수신
2. 각 결과를 `result_store.load(uri)`로 S3에서 로드
3. 상태 확인: seg/densenet 실패 → 파이프라인 중단, yolo 실패 → `{"detections": []}` 대체
4. L3 임상 로직 엔진 실행 (`clinical_logic/`)
5. L5 RAG 검색 (`rag/`)
6. L6 Bedrock 소견서 생성 (`bedrock_report/`)
7. 최종 결과 S3 저장 + 반환

**입력 스키마**:
```json
{
  "parallel_results": [
    {"status": "ok", "task": "seg", "result_uri": "s3://..."},
    {"status": "ok", "task": "densenet", "result_uri": "s3://..."},
    {"status": "ok|failed", "task": "yolo", "result_uri": "s3://..."}
  ],
  "patient_info": {"age": 72, "sex": "M", "chief_complaint": "dyspnea"},
  "run_id": "step-functions-execution-id"
}
```

**에러 핸들링 규칙**:

| 실패 모듈 | 동작 | 이유 |
|-----------|------|------|
| seg (L1) | **파이프라인 중단** | CTR, CP angle 등 필수 계측값 |
| densenet (L2) | **파이프라인 중단** | 14질환 분류 결과 필수 |
| yolo (L2b) | **bbox 빈 배열로 계속** | 보조 정보, 없어도 소견서 생성 가능 |

### 3.7 Step Functions State Machine

**타입**: EXPRESS (동기 실행)
**run_id**: `$$.Execution.Id` (Step Functions 자동 생성)

```
Client → API Gateway → Step Functions
  │
  ├─ [1] PreprocessInput
  │       Lambda A (task=preprocess)
  │       base64 이미지 → S3 URI 변환
  │
  ├─ [2] ParallelVisionInference (Parallel)
  │       ├─ Branch 1: Lambda A (task=seg)
  │       │   Retry: 3회, Catch → Fallback_Seg (failed)
  │       ├─ Branch 2: Lambda A (task=densenet)
  │       │   Retry: 3회, Catch → Fallback_DenseNet (failed)
  │       └─ Branch 3: Lambda A (task=yolo)
  │           Retry: 3회, Catch → Fallback_YOLO (Graceful Degradation)
  │
  └─ [3] AnalysisAndReport
          Lambda B (L3→L5→L6)
          Retry: 2회
          → 최종 소견서 반환
```

**ASL 정의**: `deploy/v2/step_functions/state_machine.json` (원본 문서의 4단계 ASL 그대로 사용)

**Parallel 결과 매핑**: `ResultPath: "$.parallel_results"` → 배열 형태로 Lambda B에 전달

---

## 4. 데이터 흐름

### 4.1 전체 파이프라인

```
                    ┌──────────────────────────────────────┐
                    │         Step Functions (EXPRESS)       │
                    │                                        │
  Client ──────►   │  [PreprocessInput]                     │
  (base64 image)   │       │ image_s3_uri                   │
                    │       ▼                                │
                    │  [ParallelVisionInference]             │
                    │       ├─ Lambda A (seg)     ──► S3     │
                    │       ├─ Lambda A (densenet) ──► S3    │
                    │       └─ Lambda A (yolo)    ──► S3     │
                    │       │ 3x result_uri                  │
                    │       ▼                                │
                    │  [AnalysisAndReport]                   │
                    │       └─ Lambda B                      │
                    │           ├─ load S3 results           │
                    │           ├─ L3: 임상 로직             │
                    │           ├─ L5: RAG 검색              │
                    │           └─ L6: Bedrock 소견서        │
                    │                                        │
  ◄──────────────   │  최종 소견서 JSON 반환                  │
                    └──────────────────────────────────────┘
```

### 4.2 Claim-Check 패턴 상세

```
S3 저장 경로:
s3://{bucket}/runs/{execution_id}/
├─ seg.json          # L1 세그멘테이션 결과 (~500KB)
├─ densenet.json     # L2 14질환 분류 결과 (~2KB)
├─ yolo.json         # L2b 객체 탐지 결과 (~10KB)
└─ final_report.json # 최종 소견서 (~50KB)
```

Step Functions 페이로드에는 **URI만** 전달 (256KB 제한 우회):
```json
{"result_uri": "s3://bucket/runs/exec-id-123/seg.json"}
```

### 4.3 S3 버킷 사용 규칙

| 경로 | 용도 | 권한 |
|------|------|------|
| `models/onnx/` | ONNX 모델 저장 | 읽기 (Lambda A) |
| `runs/{execution_id}/` | 중간 결과 + 최종 소견서 | 읽기/쓰기 (Lambda A/B) |
| `web/test-layer1/samples/` | 테스트 이미지 | 읽기 |
| `say1-pre-project-1~7` | **기존 버킷 (절대 쓰기 금지)** | 읽기 전용 |

---

## 5. Dockerfile 설계

### 5.1 Lambda A Dockerfile

```dockerfile
FROM public.ecr.aws/lambda/python:3.12

# shared 모듈 복사
COPY shared/result_store.py ${LAMBDA_TASK_ROOT}/
COPY shared/config.py ${LAMBDA_TASK_ROOT}/

# Lambda A 코드 복사
COPY lambda_a/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY lambda_a/*.py ${LAMBDA_TASK_ROOT}/

CMD ["lambda_function.lambda_handler"]
```

**빌드 컨텍스트**: `deploy/v2/` (shared 접근을 위해 상위 디렉토리)
**빌드 명령**: `docker build -f lambda_a/Dockerfile -t dr-ai-v2-lambda-a .`

### 5.2 Lambda B Dockerfile

```dockerfile
FROM public.ecr.aws/lambda/python:3.12

# shared 모듈 복사
COPY shared/result_store.py ${LAMBDA_TASK_ROOT}/
COPY shared/config.py ${LAMBDA_TASK_ROOT}/

# Lambda B 코드 복사
COPY lambda_b/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY lambda_b/*.py ${LAMBDA_TASK_ROOT}/
COPY lambda_b/clinical_logic/ ${LAMBDA_TASK_ROOT}/clinical_logic/
COPY lambda_b/rag/ ${LAMBDA_TASK_ROOT}/rag/
COPY lambda_b/bedrock_report/ ${LAMBDA_TASK_ROOT}/bedrock_report/

CMD ["lambda_function.lambda_handler"]
```

**빌드 컨텍스트**: `deploy/v2/`
**빌드 명령**: `docker build -f lambda_b/Dockerfile -t dr-ai-v2-lambda-b .`

---

## 6. Lambda 설정

### 6.1 Lambda A 설정

| 항목 | 값 | 이유 |
|------|-----|------|
| 함수 이름 | `dr-ai-v2-lambda-a` | v2 구분 |
| 메모리 | 3008 MB | ONNX 모델 로드 + 추론 |
| 타임아웃 | 120초 | Cold start + 모델 다운로드 |
| /tmp 크기 | 512 MB (기본값) | 3개 모델 ~134MB |
| IAM Role | `say-2-lambda-bedrock-role` | 기존 역할 활용 |
| 환경변수 | `S3_BUCKET`, `AWS_REGION` | config.py에서 참조 |

### 6.2 Lambda B 설정

| 항목 | 값 | 이유 |
|------|-----|------|
| 함수 이름 | `dr-ai-v2-lambda-b` | v2 구분 |
| 메모리 | 2048 MB | RAG + Bedrock 호출 |
| 타임아웃 | 180초 | Bedrock 소견서 생성 대기 |
| IAM Role | `say-2-lambda-bedrock-role` | Bedrock InvokeModel 권한 필요 |
| 환경변수 | `S3_BUCKET`, `AWS_REGION` | config.py에서 참조 |

---

## 7. ONNX 변환 설계

### 7.1 변환 대상

| 모델 | 원본 | 입력 크기 | 예상 ONNX 크기 | 변환 방식 |
|------|------|-----------|----------------|-----------|
| UNet | HuggingFace 모델 | (1, 3, 512, 512) | ~85MB | `torch.onnx.export()` |
| DenseNet-121 | S3 densenet121.pth | (1, 3, 224, 224) | ~27MB | `torch.onnx.export()` |
| YOLOv8 | S3 yolov8_vindr_best.pt | (1, 3, 640, 640) | ~22MB | `ultralytics .export(format="onnx")` |

### 7.2 변환 검증

```python
# 각 모델별 동일성 검증
torch_output = model(dummy_input).numpy()
onnx_output = session.run(None, {"image": dummy_input.numpy()})[0]
np.testing.assert_allclose(torch_output, onnx_output, atol=1e-5)
```

### 7.3 S3 모델 저장 경로

```
s3://pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an/
├── models/
│   ├── onnx/                   ← v2 신규
│   │   ├── unet.onnx
│   │   ├── densenet.onnx
│   │   └── yolov8.onnx
│   ├── segmentation/           ← v1 기존 (유지)
│   ├── detection/              ← v1 기존 (유지)
│   └── yolov8_vindr_best.pt   ← v1 기존 (유지)
```

---

## 8. IAM 권한 설계

### 8.1 Lambda 실행 역할 (say-2-lambda-bedrock-role)

기존 역할에 추가 필요한 권한:

```json
{
  "Effect": "Allow",
  "Action": [
    "s3:GetObject",
    "s3:PutObject"
  ],
  "Resource": "arn:aws:s3:::pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an/*"
}
```

### 8.2 Step Functions 실행 역할

```json
{
  "Effect": "Allow",
  "Action": [
    "lambda:InvokeFunction"
  ],
  "Resource": [
    "arn:aws:lambda:ap-northeast-2:666803869796:function:dr-ai-v2-lambda-a",
    "arn:aws:lambda:ap-northeast-2:666803869796:function:dr-ai-v2-lambda-b"
  ]
}
```

### 8.3 API Gateway → Step Functions 권한

```json
{
  "Effect": "Allow",
  "Action": [
    "states:StartSyncExecution"
  ],
  "Resource": "arn:aws:states:ap-northeast-2:666803869796:stateMachine:dr-ai-radiologist-v2"
}
```

---

## 9. 에러 핸들링 설계

### 9.1 Step Functions 레벨

| 상태 | Retry | Catch | 동작 |
|------|-------|-------|------|
| Task_Segmentation | 3회 (2s, backoff 2.0) | → Fallback_Seg | `{"status": "failed"}` |
| Task_DenseNet | 3회 (2s, backoff 2.0) | → Fallback_DenseNet | `{"status": "failed"}` |
| Task_YOLO | 3회 (2s, backoff 2.0) | → Fallback_YOLO | Graceful: `{"detections": []}` |
| AnalysisAndReport | 2회 (3s, backoff 2.0) | - | 실패 시 전체 중단 |

### 9.2 Lambda B 레벨 (Graceful Degradation)

```python
# Lambda B에서의 에러 처리 로직
for result in parallel_results:
    if result["status"] == "failed":
        if result["task"] in ("seg", "densenet"):
            # 필수 모듈 실패 → 파이프라인 중단
            return {"statusCode": 500, "error": f"{task} 실패"}
        elif result["task"] == "yolo":
            # YOLO만 허용 → 빈 배열로 대체
            vision_data["yolo"] = {"detections": [], "processing_time": 0}
```

---

## 10. 테스트 설계

### 10.1 단위 테스트

| 테스트 | 대상 | 방법 | 성공 기준 |
|--------|------|------|-----------|
| Lambda A seg | 세그멘테이션 추론 | `aws lambda invoke --payload '{"task":"seg",...}'` | status=ok, mask_base64 존재 |
| Lambda A densenet | DenseNet 추론 | `aws lambda invoke --payload '{"task":"densenet",...}'` | status=ok, 14질환 predictions |
| Lambda A yolo | YOLOv8 추론 | `aws lambda invoke --payload '{"task":"yolo",...}'` | status=ok, detections 배열 |
| Lambda B | 분석+소견서 | 모의 result_uri로 호출 | statusCode=200, report 존재 |

### 10.2 E2E 테스트

```bash
# CHF (울혈성 심부전) 시나리오
aws stepfunctions start-sync-execution \
  --state-machine-arn "arn:aws:states:ap-northeast-2:666803869796:stateMachine:dr-ai-radiologist-v2" \
  --input '{"image_base64": "...", "patient_info": {"age": 72, "sex": "M", "chief_complaint": "dyspnea"}}'

# 검증: 소견서에 Cardiomegaly, Pleural Effusion, Edema 언급 확인
```

### 10.3 ONNX vs PyTorch 비교

```bash
python deploy/v2/scripts/compare_results.py \
  --old-endpoint "기존 Lambda Function URL" \
  --new-function "dr-ai-v2-lambda-a" \
  --image "s3://bucket/web/test-layer1/samples/sample_1.jpg"

# 검증: DenseNet 14질환 확률 atol≤1e-5
```

### 10.4 Graceful Degradation 테스트

```bash
# Lambda A yolo를 의도적으로 실패시킨 후 (잘못된 모델 경로 등)
# Step Functions 전체 실행 → 소견서가 bbox 없이 정상 생성되는지 확인
```

---

## 11. Implementation Guide

### 11.1 구현 순서

| 순서 | 모듈 | 파일 | 의존성 | 예상 라인 |
|------|------|------|--------|-----------|
| 1 | shared | config.py | 없음 | ~25 |
| 2 | shared | result_store.py | boto3 | ~60 |
| 3 | scripts | convert_to_onnx.py | torch, onnxruntime | ~80 |
| 4 | lambda_a | model_loader.py | boto3, onnxruntime | ~30 |
| 5 | lambda_a | inference_seg.py | numpy, PIL, onnxruntime | ~150 |
| 6 | lambda_a | inference_densenet.py | numpy, PIL, onnxruntime | ~80 |
| 7 | lambda_a | inference_yolo.py | numpy, PIL, onnxruntime | ~100 |
| 8 | lambda_a | lambda_function.py | 4~7 모듈 | ~60 |
| 9 | lambda_a | Dockerfile + requirements.txt | - | ~15 |
| 10 | lambda_b | lambda_function.py | clinical_logic, rag, bedrock_report | ~80 |
| 11 | lambda_b | clinical_logic/ | 기존 L3 코드 복사 | ~500+ |
| 12 | lambda_b | rag/ | 기존 L5 코드 복사 | ~200+ |
| 13 | lambda_b | bedrock_report/ | 기존 L6 코드 복사 | ~300+ |
| 14 | lambda_b | Dockerfile + requirements.txt | - | ~20 |
| 15 | step_functions | state_machine.json | Lambda A/B ARN | ~200 |
| 16 | scripts | deploy.sh | aws cli | ~80 |
| 17 | scripts | compare_results.py | boto3, numpy | ~60 |

### 11.2 파일 생성/수정 요약

- **새로 생성**: 17개 파일 + clinical_logic/rag/bedrock_report 디렉토리 (기존 코드 복사)
- **기존 수정**: 0개 (v1 코드 절대 수정하지 않음)
- **예상 총 라인**: ~1,500줄 (신규 작성) + ~1,000줄 (기존 코드 복사)

### 11.3 Session Guide

**Module Map**:

| Module Key | 모듈 | 파일 수 | 설명 |
|------------|------|---------|------|
| `module-1` | shared + scripts | 4개 | 공용 모듈 + ONNX 변환/비교 스크립트 |
| `module-2` | lambda_a | 7개 | Vision 통합 Lambda (model_loader + 3개 inference + handler) |
| `module-3` | lambda_b | 5개+ | 분석+소견서 Lambda (handler + L3/L5/L6 코드 복사) |
| `module-4` | step_functions + deploy | 3개 | ASL 정의 + 배포 스크립트 |

**Recommended Session Plan**:

| 세션 | Module | 예상 작업 | 비고 |
|------|--------|-----------|------|
| 세션 1 | module-1 | shared 모듈 + ONNX 변환 스크립트 | 기반 작업, 독립적 |
| 세션 2 | module-2 | Lambda A 전체 구현 | 기존 L1/L2/L2b 코드 참조 필요 |
| 세션 3 | module-3 | Lambda B 전체 구현 | 기존 L3/L5/L6 코드 복사+이식 |
| 세션 4 | module-4 | Step Functions ASL + 배포 + 테스트 | 전체 통합 |

**사용법**:
```bash
/pdca do architecture-v2                          # 전체 구현
/pdca do architecture-v2 --scope module-1         # shared + scripts만
/pdca do architecture-v2 --scope module-2         # Lambda A만
/pdca do architecture-v2 --scope module-1,module-2 # 세션 1+2 동시
```

---

## 12. 절대 주의사항 (설계 제약)

1. **say1-pre-project-1 ~ say1-pre-project-7 버킷**: 읽기 전용, 쓰기 절대 금지
2. **기존 7개 Lambda**: 코드 수정 절대 금지 (참조만 가능)
3. **기존 엔드포인트**: 삭제 금지 (v2 검증 완료 전까지 유지)
4. **추론 로직**: torch 호출만 ONNX로 교체, 나머지 전처리/후처리는 100% 동일하게 이식
5. **모델 변환 후**: 반드시 동일 이미지로 PyTorch vs ONNX 결과 비교 검증 (atol≤1e-5)
6. **shared/ 모듈**: Dockerfile에서 COPY로 주입, import 경로는 flat (from config import Config)
7. **Docker 빌드 컨텍스트**: `deploy/v2/` 디렉토리 (shared 접근을 위해)
