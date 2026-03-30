# Design: v3-eks-migration

> v2 Lambda → v3 EKS 마이크로서비스 마이그레이션 설계서
> 작성일: 2026-03-25
> 피처: v3-eks-migration
> PDCA Phase: Design
> 아키텍처: Option C (Pragmatic Balance) + K8s 12-Factor 운영 규약

---

## Context Anchor

| 항목 | 내용 |
|------|------|
| **WHY** | Lambda 콜드스타트/단일 모달 한계 극복, 팀원별 독립 서비스 개발 체계 구축 |
| **WHO** | 6팀 5명 (박현우-chest, 원정아-ecg, 팀원C-blood, 팀원D-orchestrator, 팀원E-shared) |
| **RISK** | K8s 학습곡선, 서비스 간 통신 장애, ONNX 변환 정합성, Bedrock 비용 |
| **SUCCESS** | 로컬 minikube에서 환자→순차검사→종합소견서 E2E 성공, 이후 EKS 무중단 이전 |
| **SCOPE** | 8개 서비스 (chest/ecg/blood/orchestrator/rag/report/auth/patient) + K8s + CI/CD |

---

## 1. Overview

### 1-1. 설계 원칙

**K8s 운영 규약 (12-Factor App 핵심 3가지)**

| 원칙 | 구현 | 이유 |
|------|------|------|
| **설정은 환경변수** | `config.py` (pydantic-settings) | ConfigMap/Secret으로 local/eks 환경 분기 |
| **헬스체크 2종** | `/healthz` (liveness) + `/readyz` (readiness) | 모델 로딩 중 트래픽 차단, Pod 이상 감지 |
| **시작/종료 라이프사이클** | FastAPI `lifespan` | Pod 생성 시 모델 1회 로딩, 종료 시 정리 |

**코드 아키텍처 원칙 (Option C)**

- v2 핵심 로직 재사용 (Lambda 핸들러만 제거)
- 공통 Pydantic 스키마만 shared로 공유 (별도 패키지화 안 함)
- 과도한 레이어 분리 없음 (domain/application/infrastructure X)
- 서비스별 독립 Dockerfile, 독립 requirements.txt

---

## 2. 서비스 공통 패턴

모든 서비스가 동일하게 적용하는 3개 파일 + 2개 엔드포인트.

### 2-1. config.py — 환경변수 기반 설정

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # K8s ConfigMap에서 주입
    database_url: str = "postgresql://postgres:postgres@postgres-svc:5432/drai"
    redis_url: str = "redis://redis-svc:6379/0"
    model_dir: str = "/models"
    rag_url: str = "http://rag-svc:8000/search"
    report_url: str = "http://report-svc:8000/generate"
    bedrock_region: str = "ap-northeast-2"
    bedrock_model_id: str = "anthropic.claude-sonnet-4-6-20250514"
    log_level: str = "INFO"

    class Config:
        env_file = ".env"  # 로컬 개발 시 .env 파일 지원

settings = Settings()
```

**환경별 값 주입:**

| 환경변수 | local (ConfigMap) | eks (ConfigMap) |
|----------|-------------------|-----------------|
| `DATABASE_URL` | `postgresql://postgres:postgres@postgres-svc:5432/drai` | `postgresql://user:pass@rds-endpoint:5432/drai` |
| `REDIS_URL` | `redis://redis-svc:6379/0` | `redis://elasticache-endpoint:6379/0` |
| `MODEL_DIR` | `/models` (PV) | `/models` (EFS) |

### 2-2. main.py — K8s 라이프사이클 + 프로브

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from config import settings
import logging

logger = logging.getLogger(__name__)

# 서비스 상태
state = {"ready": False, "models": {}}

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Pod 생성 시 1회 실행 — 모델/리소스 로딩"""
    logger.info("Starting up: loading resources...")
    # 서비스별 초기화 로직 (아래 서비스별 설계에서 구체화)
    await startup()
    state["ready"] = True
    logger.info("Ready to serve requests")
    yield
    # Pod 종료 시 정리
    logger.info("Shutting down: cleaning up...")
    await shutdown()

app = FastAPI(title="service-name", lifespan=lifespan)

@app.get("/healthz")
def liveness():
    """Liveness probe — Pod이 살아있나"""
    return {"status": "ok"}

@app.get("/readyz")
def readiness():
    """Readiness probe — 요청 받을 준비 됐나"""
    if not state["ready"]:
        raise HTTPException(status_code=503, detail="not ready")
    return {"status": "ready"}
```

### 2-3. Dockerfile — 공통 패턴

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# 의존성 먼저 (Docker 캐시 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드
COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 2-4. 공통 스키마 (shared/schemas.py)

```python
from pydantic import BaseModel
from typing import Optional

class PatientInfo(BaseModel):
    age: int
    sex: str                          # "M" | "F"
    chief_complaint: str
    history: list[str] = []

class Finding(BaseModel):
    name: str
    detected: bool
    confidence: float
    detail: str = ""

class PredictRequest(BaseModel):
    patient_id: str
    patient_info: PatientInfo
    data: dict                        # 모달마다 다름
    context: dict = {}                # 이전 모달 결과 요약

class PredictResponse(BaseModel):
    status: str = "success"
    modal: str
    findings: list[Finding]
    summary: str
    report: str                       # 모달별 소견서
    metadata: dict = {}

class RAGRequest(BaseModel):
    query: str
    modal: str
    top_k: int = 5

class RAGResponse(BaseModel):
    results: list[dict]

class ReportRequest(BaseModel):
    patient_id: str
    patient_info: PatientInfo
    modal_reports: list[dict]

class ReportResponse(BaseModel):
    status: str = "success"
    report: str                       # 종합 소견서
    diagnosis: str
```

---

## 3. 서비스별 상세 설계

### 3-1. chest-svc (박현우)

**파일 구조:**

```
services/chest-svc/
├── main.py                        ← FastAPI + lifespan (ONNX 3개 로딩)
├── config.py                      ← 환경변수 (model_dir, rag_url, bedrock)
├── pipeline.py                    ← 6단계 순차 실행 통합
├── layer1_segmentation/
│   ├── preprocessing.py           ← v2 그대로 (이미지 리사이즈, 정규화)
│   └── model.py                   ← PyTorch→ONNX Runtime 추론으로 교체
├── layer2_detection/
│   ├── densenet.py                ← ONNX Runtime (14질환 확률)
│   └── yolo.py                    ← ONNX Runtime (병변 bbox)
├── layer3_clinical_logic/
│   ├── engine.py                  ← v2 거의 그대로 복사
│   ├── cross_validation.py        ← v2 그대로
│   ├── differential.py            ← v2 그대로
│   └── rules/                     ← v2 14개 질환 규칙 그대로
├── report/
│   ├── chest_report_generator.py  ← Bedrock 호출 → 흉부 소견서
│   └── prompt_templates.py        ← v2 프롬프트 재사용
├── Dockerfile
└── requirements.txt
```

**lifespan 초기화:**

```python
async def startup():
    import onnxruntime as ort
    state["models"]["unet"] = ort.InferenceSession(f"{settings.model_dir}/unet_seg.onnx")
    state["models"]["densenet"] = ort.InferenceSession(f"{settings.model_dir}/densenet121.onnx")
    state["models"]["yolo"] = ort.InferenceSession(f"{settings.model_dir}/yolov8_vindr.onnx")

async def shutdown():
    state["models"].clear()
```

**pipeline.py 흐름:**

```python
async def run(req: PredictRequest, models: dict, settings: Settings) -> PredictResponse:
    # Layer 1: 세그멘테이션
    seg_result = segment(req.data["image_base64"], models["unet"])

    # Layer 2: DenseNet + YOLO
    disease_probs = classify(seg_result.lung_crop, models["densenet"])
    bboxes = detect(req.data["image_base64"], models["yolo"])

    # Layer 3: Clinical Logic (v2 engine 그대로)
    clinical = engine.analyze(seg_result, disease_probs, bboxes, req.patient_info)

    # RAG: 유사 케이스 검색 (HTTP)
    rag_results = await http_post(settings.rag_url, {
        "query": clinical.summary, "modal": "chest", "top_k": 5
    })

    # Report: 흉부 소견서 생성 (Bedrock)
    report = await generate_chest_report(clinical, rag_results, req.patient_info)

    return PredictResponse(
        modal="chest",
        findings=clinical.findings,
        summary=clinical.summary,
        report=report,
        metadata={"inference_time_ms": elapsed}
    )
```

**v2 마이그레이션 핵심:**
- `layer1~3`: Lambda `event`/`context` 파라미터 → 함수 파라미터로 교체
- `layer1~2`: PyTorch `model.forward()` → ONNX `session.run()` 교체
- `layer3`: 거의 변경 없음 (순수 Python 로직)
- `report`: S3 임시 저장 제거, Bedrock 호출 로직 유지

**K8s 리소스:**

```yaml
resources:
  requests:
    cpu: "1"
    memory: "2Gi"
  limits:
    cpu: "1"
    memory: "2Gi"
readinessProbe:
  httpGet:
    path: /readyz
    port: 8000
  initialDelaySeconds: 30    # ONNX 3개 로딩 시간
  periodSeconds: 5
livenessProbe:
  httpGet:
    path: /healthz
    port: 8000
  periodSeconds: 10
```

---

### 3-2. ecg-svc (원정아)

**파일 구조:**

```
services/ecg-svc/
├── main.py                      ← FastAPI + lifespan
├── config.py                    ← 환경변수
├── analyzer.py                  ← ECG 분석 메인 로직
├── models/                      ← ECG 분석 모델 (원정아 구현)
├── report/
│   └── ecg_report_generator.py  ← Bedrock 호출 → 심전도 소견서
├── Dockerfile
└── requirements.txt
```

**K8s 리소스:**

```yaml
resources:
  requests: { cpu: "500m", memory: "1Gi" }
  limits: { cpu: "500m", memory: "1Gi" }
readinessProbe:
  httpGet: { path: /readyz, port: 8000 }
  initialDelaySeconds: 10
```

---

### 3-3. blood-svc (팀원C)

**파일 구조:**

```
services/blood-svc/
├── main.py                      ← FastAPI + lifespan (모델 없음, 즉시 ready)
├── config.py
├── analyzer.py                  ← 혈액검사 수치 분석 + 이상치 판정
├── reference_ranges.py          ← 정상 범위 테이블
├── report/
│   └── blood_report_generator.py
├── Dockerfile
└── requirements.txt
```

**특이사항:** ML 모델 없음 → 규칙 기반 → readiness 즉시 true, `initialDelaySeconds: 2`

**K8s 리소스:**

```yaml
resources:
  requests: { cpu: "250m", memory: "512Mi" }
readinessProbe:
  initialDelaySeconds: 2       # 모델 로딩 없음
```

---

### 3-4. central-orchestrator (팀원D)

**파일 구조:**

```
services/central-orchestrator/
├── main.py                      ← FastAPI + lifespan (DB/Redis 연결)
├── config.py
├── orchestrator.py              ← LLM 순차 루프 엔진 (핵심)
├── session_manager.py           ← 세션 상태 관리 (PG + Redis)
├── modal_client.py              ← 모달 서비스 HTTP 클라이언트
├── prompts.py                   ← Bedrock 프롬프트 템플릿
├── Dockerfile
└── requirements.txt
```

**orchestrator.py 핵심 로직:**

```python
async def run_sequential_exam(patient_id: str, patient_info: PatientInfo):
    session = await session_manager.create(patient_id, patient_info)
    accumulated_results = []

    while True:
        # 1. Bedrock에 "다음 검사?" 질의
        next_modal = await ask_bedrock_next_exam(
            patient_info, accumulated_results
        )

        # 2. 종료 판단
        if next_modal == "DONE":
            break

        # 3. 해당 모달 서비스 호출
        result = await modal_client.predict(
            modal=next_modal,
            patient_id=patient_id,
            patient_info=patient_info,
            context=accumulated_results
        )

        # 4. 결과 누적
        accumulated_results.append(result)
        await session_manager.update(session.id, result)

        # 5. 안전장치: max 5회
        if len(accumulated_results) >= 5:
            break

    # 6. 종합 소견서 생성
    final_report = await http_post(settings.report_url, {
        "patient_id": patient_id,
        "patient_info": patient_info.model_dump(),
        "modal_reports": accumulated_results
    })

    return final_report
```

**modal_client.py — 서비스 라우팅:**

```python
MODAL_URLS = {
    "chest": f"http://chest-svc:8000/predict",
    "ecg": f"http://ecg-svc:8000/predict",
    "blood": f"http://blood-svc:8000/predict",
}
```

**lifespan 초기화:**

```python
async def startup():
    # PostgreSQL 연결 풀
    state["db"] = await asyncpg.create_pool(settings.database_url)
    # Redis 연결
    state["redis"] = aioredis.from_url(settings.redis_url)
    state["ready"] = True

async def shutdown():
    await state["db"].close()
    await state["redis"].close()
```

**K8s 리소스:**

```yaml
resources:
  requests: { cpu: "250m", memory: "512Mi" }
readinessProbe:
  initialDelaySeconds: 5       # DB/Redis 연결 시간
```

---

### 3-5. rag-svc (팀원E)

**파일 구조:**

```
services/rag-svc/
├── main.py                      ← FastAPI + lifespan (FAISS 인덱스 로딩)
├── config.py
├── rag_service.py               ← FAISS 검색 + bge-small 임베딩
├── query_builder.py             ← 모달별 쿼리 구성
├── Dockerfile
└── requirements.txt
```

**lifespan 초기화:**

```python
async def startup():
    import faiss
    from sentence_transformers import SentenceTransformer
    state["models"]["embedder"] = SentenceTransformer("BAAI/bge-small-en-v1.5")
    state["models"]["index"] = faiss.read_index(f"{settings.model_dir}/faiss_index.bin")
    state["ready"] = True
```

**K8s 리소스:**

```yaml
resources:
  requests: { cpu: "500m", memory: "1Gi" }
readinessProbe:
  initialDelaySeconds: 15      # FAISS + 임베딩 모델 로딩
```

---

### 3-6. report-svc (팀원E)

**파일 구조:**

```
services/report-svc/
├── main.py                      ← FastAPI (모델 없음, 즉시 ready)
├── config.py
├── report_generator.py          ← Bedrock Claude → 종합 소견서
├── prompt_templates.py          ← 종합 소견서 프롬프트
├── Dockerfile
└── requirements.txt
```

**report_generator.py 핵심:**

```python
async def generate_comprehensive_report(
    patient_info: PatientInfo,
    modal_reports: list[dict]
) -> str:
    """3개 모달 소견서 합산 → Bedrock Claude → 종합 소견서"""
    prompt = build_prompt(patient_info, modal_reports)
    response = await bedrock_invoke(
        model_id=settings.bedrock_model_id,
        prompt=prompt
    )
    return response
```

---

### 3-7. auth-svc / patient-svc (P2, 후순위)

Sprint 4에서 구현. 설계만 명시.

**auth-svc:** JWT 발급(`POST /login`) + 검증(`GET /verify`) + FastAPI 미들웨어
**patient-svc:** 환자 CRUD (`POST/GET/PUT /patients`) + PostgreSQL 연동

---

## 4. K8s 매니페스트 설계

### 4-1. base/ — 공통 Deployment + Service

**chest-svc.yaml (대표 예시):**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: chest-svc
  namespace: dr-ai
  labels:
    app: chest-svc
spec:
  replicas: 1
  selector:
    matchLabels:
      app: chest-svc
  template:
    metadata:
      labels:
        app: chest-svc
    spec:
      containers:
      - name: chest-svc
        image: chest-svc:latest        # local: 로컬 빌드 / eks: ECR URL
        ports:
        - containerPort: 8000
        envFrom:
        - configMapRef:
            name: dr-ai-config
        volumeMounts:
        - name: models
          mountPath: /models
          readOnly: true
        resources:
          requests:
            cpu: "1"
            memory: "2Gi"
          limits:
            cpu: "1"
            memory: "2Gi"
        livenessProbe:
          httpGet:
            path: /healthz
            port: 8000
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /readyz
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 5
      volumes:
      - name: models
        persistentVolumeClaim:
          claimName: models-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: chest-svc
  namespace: dr-ai
spec:
  selector:
    app: chest-svc
  ports:
  - port: 8000
    targetPort: 8000
```

### 4-2. overlays/local/ — minikube

**configmap.yaml:**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: dr-ai-config
  namespace: dr-ai
data:
  DATABASE_URL: "postgresql://postgres:postgres@postgres-svc:5432/drai"
  REDIS_URL: "redis://redis-svc:6379/0"
  MODEL_DIR: "/models"
  RAG_URL: "http://rag-svc:8000/search"
  REPORT_URL: "http://report-svc:8000/generate"
  BEDROCK_REGION: "ap-northeast-2"
  LOG_LEVEL: "DEBUG"
```

**postgres.yaml:**

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
  namespace: dr-ai
spec:
  serviceName: postgres-svc
  replicas: 1
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
      - name: postgres
        image: postgres:16
        ports:
        - containerPort: 5432
        env:
        - name: POSTGRES_DB
          value: "drai"
        - name: POSTGRES_USER
          value: "postgres"
        - name: POSTGRES_PASSWORD
          value: "postgres"
        volumeMounts:
        - name: pg-data
          mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
  - metadata:
      name: pg-data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 1Gi
---
apiVersion: v1
kind: Service
metadata:
  name: postgres-svc
  namespace: dr-ai
spec:
  selector:
    app: postgres
  ports:
  - port: 5432
```

**redis.yaml:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis
  namespace: dr-ai
spec:
  replicas: 1
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
      - name: redis
        image: redis:7
        ports:
        - containerPort: 6379
---
apiVersion: v1
kind: Service
metadata:
  name: redis-svc
  namespace: dr-ai
spec:
  selector:
    app: redis
  ports:
  - port: 6379
```

**pv-models.yaml:**

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: models-pv
spec:
  capacity:
    storage: 1Gi
  accessModes: ["ReadOnlyMany"]
  hostPath:
    path: /data/models              # minikube mount 경로
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: models-pvc
  namespace: dr-ai
spec:
  accessModes: ["ReadOnlyMany"]
  resources:
    requests:
      storage: 1Gi
```

### 4-3. overlays/eks/ — AWS

**configmap.yaml:**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: dr-ai-config
  namespace: dr-ai
data:
  DATABASE_URL: "postgresql://drai_user:${DB_PASSWORD}@drai-rds.xxxxx.ap-northeast-2.rds.amazonaws.com:5432/drai"
  REDIS_URL: "redis://drai-cache.xxxxx.apne2.cache.amazonaws.com:6379/0"
  MODEL_DIR: "/models"
  RAG_URL: "http://rag-svc:8000/search"
  REPORT_URL: "http://report-svc:8000/generate"
  BEDROCK_REGION: "ap-northeast-2"
  LOG_LEVEL: "INFO"
```

---

## 5. Docker Compose (K8s 이전 빠른 테스트)

Sprint 1~2에서 K8s 전에 Docker Compose로 빠르게 통합 테스트.

```yaml
# docker-compose.yml
version: "3.9"

services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: drai
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    ports: ["5432:5432"]

  redis:
    image: redis:7
    ports: ["6379:6379"]

  chest-svc:
    build: ./services/chest-svc
    ports: ["8001:8000"]
    environment:
      DATABASE_URL: postgresql://postgres:postgres@postgres:5432/drai
      REDIS_URL: redis://redis:6379/0
      MODEL_DIR: /models
      RAG_URL: http://rag-svc:8000/search
    volumes:
      - ./models:/models:ro
    depends_on: [postgres, redis]

  ecg-svc:
    build: ./services/ecg-svc
    ports: ["8002:8000"]
    environment:
      RAG_URL: http://rag-svc:8000/search
    depends_on: [postgres, redis]

  blood-svc:
    build: ./services/blood-svc
    ports: ["8003:8000"]
    environment:
      RAG_URL: http://rag-svc:8000/search
    depends_on: [postgres, redis]

  rag-svc:
    build: ./services/rag-svc
    ports: ["8004:8000"]
    environment:
      MODEL_DIR: /models
    volumes:
      - ./models:/models:ro

  report-svc:
    build: ./services/report-svc
    ports: ["8005:8000"]
    environment:
      BEDROCK_REGION: ap-northeast-2

  central-orchestrator:
    build: ./services/central-orchestrator
    ports: ["8000:8000"]
    environment:
      DATABASE_URL: postgresql://postgres:postgres@postgres:5432/drai
      REDIS_URL: redis://redis:6379/0
      CHEST_URL: http://chest-svc:8000/predict
      ECG_URL: http://ecg-svc:8000/predict
      BLOOD_URL: http://blood-svc:8000/predict
      REPORT_URL: http://report-svc:8000/generate
      BEDROCK_REGION: ap-northeast-2
    depends_on:
      - postgres
      - redis
      - chest-svc
      - ecg-svc
      - blood-svc
      - rag-svc
      - report-svc
```

---

## 6. v2 → v3 코드 마이그레이션 상세

### 6-1. 마이그레이션 규칙

| 변경 유형 | v2 | v3 | 작업량 |
|-----------|-----|-----|--------|
| Lambda 핸들러 제거 | `def handler(event, context):` | `async def predict(req: PredictRequest):` | 각 서비스 1회 |
| S3 임시 저장 제거 | `s3.put_object()` / `s3.get_object()` | 함수 인자로 직접 전달 | 모든 서비스 |
| PyTorch → ONNX | `model(tensor)` | `session.run(None, {"input": array})` | Layer 1, 2, 2b |
| S3 모델 로딩 → PV | `s3.download_file()` | `ort.InferenceSession("/models/xxx.onnx")` | Layer 1, 2, 2b |
| Function URL → K8s DNS | `https://xxx.lambda-url.xxx` | `http://rag-svc:8000/search` | 오케스트레이터, RAG 호출 |
| IAM 인증 제거 | `aws4auth` 헤더 | 불필요 (K8s 내부 통신) | 모든 서비스 간 호출 |

### 6-2. 변경 없는 코드 (그대로 복사)

- `layer3_clinical_logic/engine.py` — 순수 Python, AWS 의존성 없음
- `layer3_clinical_logic/rules/` — 14개 질환 규칙 전체
- `layer3_clinical_logic/cross_validation.py`
- `layer3_clinical_logic/differential.py`
- `report/prompt_templates.py` — Bedrock 프롬프트

---

## 7. 데이터베이스 스키마

### 7-1. PostgreSQL 테이블

```sql
-- 환자 정보
CREATE TABLE patients (
    id VARCHAR(20) PRIMARY KEY,           -- "P-20260324-001"
    age INT NOT NULL,
    sex CHAR(1) NOT NULL,
    chief_complaint TEXT,
    history TEXT[],
    created_at TIMESTAMP DEFAULT NOW()
);

-- 검사 세션
CREATE TABLE exam_sessions (
    id SERIAL PRIMARY KEY,
    patient_id VARCHAR(20) REFERENCES patients(id),
    status VARCHAR(20) DEFAULT 'in_progress', -- in_progress | completed
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

-- 모달 결과
CREATE TABLE modal_results (
    id SERIAL PRIMARY KEY,
    session_id INT REFERENCES exam_sessions(id),
    modal VARCHAR(10) NOT NULL,            -- chest | ecg | blood
    findings JSONB NOT NULL,
    summary TEXT,
    report TEXT,                            -- 모달별 소견서
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 종합 소견서
CREATE TABLE comprehensive_reports (
    id SERIAL PRIMARY KEY,
    session_id INT REFERENCES exam_sessions(id),
    report TEXT NOT NULL,
    diagnosis TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### 7-2. Redis 사용

```
# 세션 캐시 (TTL 1시간)
session:{session_id} → JSON { patient_id, status, accumulated_results }

# 오케스트레이터 상태 (순차 루프 중간 상태)
exam:{session_id}:step → INT (현재 몇 번째 검사)
exam:{session_id}:results → LIST [modal_result_1, modal_result_2, ...]
```

---

## 8. CI/CD 파이프라인

### 8-1. GitHub Actions (서비스별 독립 빌드)

```yaml
# .github/workflows/chest-svc.yml
name: chest-svc CI/CD
on:
  push:
    paths: ["services/chest-svc/**"]
    branches: [mimic-cxr-v3-eks]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    - name: Build Docker image
      run: docker build -t chest-svc:${{ github.sha }} services/chest-svc/
    - name: Push to ECR (EKS only)
      if: github.ref == 'refs/heads/mimic-cxr-v3-eks'
      run: |
        aws ecr get-login-password | docker login --username AWS --password-stdin $ECR_URL
        docker tag chest-svc:${{ github.sha }} $ECR_URL/chest-svc:${{ github.sha }}
        docker push $ECR_URL/chest-svc:${{ github.sha }}
```

**트리거 규칙:** `services/자기-서비스명/` 폴더 변경 시에만 해당 서비스 CI/CD 실행

---

## 9. 모니터링 설계

### 9-1. Prometheus 메트릭

각 FastAPI 서비스에 `prometheus-fastapi-instrumentator` 추가:

```python
from prometheus_fastapi_instrumentator import Instrumentator
Instrumentator().instrument(app).expose(app)
```

**핵심 메트릭:**
- `http_request_duration_seconds` — 엔드포인트별 응답시간
- `http_requests_total` — 요청 수
- `model_inference_duration_seconds` — 모델 추론 시간 (커스텀)

### 9-2. Grafana 대시보드

| 패널 | 메트릭 |
|------|--------|
| 서비스 상태 | Pod 수, readiness 상태 |
| 응답 시간 | /predict P50, P95, P99 |
| 추론 시간 | 서비스별 모델 추론 시간 |
| 오류율 | 5xx 응답 비율 |
| 순차 루프 | 평균 검사 횟수, 총 E2E 시간 |

---

## 10. 보안 설계

| 영역 | 로컬 (Phase A) | EKS (Phase B) |
|------|----------------|---------------|
| 서비스 간 통신 | K8s 내부 DNS (암호화 없음) | K8s 내부 DNS + NetworkPolicy |
| DB 인증 | 하드코딩 (postgres/postgres) | Secret (AWS Secrets Manager) |
| Bedrock | AWS credential (~/.aws) | IRSA (IAM Roles for Service Accounts) |
| 외부 접근 | minikube port-forward | ALB + HTTPS + WAF |
| JWT (P2) | 비활성화 | auth-svc 미들웨어 |

---

## 11. Implementation Guide

### 11.1 구현 순서

| 순서 | 모듈 | 파일 | 의존성 |
|------|------|------|--------|
| 1 | shared 스키마 | `shared/schemas.py` | 없음 |
| 2 | chest-svc 스캐폴딩 | `main.py`, `config.py`, `Dockerfile` | shared |
| 3 | chest-svc 파이프라인 | `pipeline.py`, `layer1~3/`, `report/` | ONNX 모델 |
| 4 | ecg-svc | 전체 | shared |
| 5 | blood-svc | 전체 | shared |
| 6 | rag-svc | 전체 | FAISS 인덱스 |
| 7 | report-svc | 전체 | Bedrock |
| 8 | central-orchestrator | 전체 | 모든 모달 서비스 |
| 9 | docker-compose.yml | 루트 | 모든 서비스 |
| 10 | K8s base YAML | `k8s/base/` | Docker 이미지 |
| 11 | K8s overlays/local | `k8s/overlays/local/` | base |
| 12 | GitHub Actions | `.github/workflows/` | ECR (Phase B) |

### 11.2 모듈별 예상 파일 수

| 모듈 | 신규 파일 | v2에서 복사 | 합계 |
|------|-----------|-------------|------|
| shared | 1 | 0 | 1 |
| chest-svc | 4 (main, config, pipeline, Dockerfile) | 8 (layer1~3, report) | 12 |
| ecg-svc | 5 | 0 | 5 |
| blood-svc | 5 | 0 | 5 |
| rag-svc | 4 | 2 (rag_service, query_builder) | 6 |
| report-svc | 4 | 1 (prompt_templates) | 5 |
| central-orchestrator | 6 | 0 | 6 |
| k8s base | 7 (6서비스+kustomization) | 0 | 7 |
| k8s local overlay | 5 | 0 | 5 |
| docker-compose | 1 | 0 | 1 |
| CI/CD | 4 | 0 | 4 |
| **합계** | **46** | **11** | **57** |

### 11.3 Session Guide

| 세션 | 모듈 | 예상 작업 | Scope Key |
|------|------|-----------|-----------|
| **Session 1** | shared + chest-svc 스캐폴딩 | schemas.py + main/config/Dockerfile + mock /predict | `module-1` |
| **Session 2** | chest-svc 파이프라인 | layer1~3 마이그레이션 + ONNX + pipeline.py | `module-2` |
| **Session 3** | ecg-svc + blood-svc | 두 모달 서비스 전체 구현 | `module-3` |
| **Session 4** | rag-svc + report-svc | 공유 서비스 구현 | `module-4` |
| **Session 5** | central-orchestrator | LLM 순차 루프 + 세션 관리 | `module-5` |
| **Session 6** | Docker Compose + E2E | 통합 테스트 환경 구축 | `module-6` |
| **Session 7** | K8s manifests | base + overlays/local + minikube 검증 | `module-7` |
| **Session 8** | CI/CD + 모니터링 | GitHub Actions + Prometheus | `module-8` |

**사용법:** `/pdca do v3-eks-migration --scope module-1`
