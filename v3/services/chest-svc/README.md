# chest-svc — 흉부 X-Ray AI 분석 마이크로서비스

> **담당: 박현우**
> 6-Layer CXR 파이프라인을 FastAPI 마이크로서비스로 구현한 모듈입니다.
> ONNX 모델 3개(UNet, DenseNet-121, YOLOv8)를 로드하여 흉부 X선 영상을 분석하고,
> 14개 질환 판정 + 임상 로직 + Bedrock Claude 소견서 생성까지 수행합니다.

---

## 서비스 개요

| 항목 | 내용 |
|------|------|
| 프레임워크 | FastAPI + uvicorn |
| 모델 런타임 | ONNX Runtime (CPU) |
| 소견서 생성 | AWS Bedrock Claude |
| 유사 케이스 검색 | rag-svc (HTTP) |
| 포트 | 8000 |
| 헬스체크 | `/healthz` (liveness), `/readyz` (readiness) |

### 6-Layer 파이프라인 흐름

```
[이미지 입력]
    │
    ▼
Stage 1: Segmentation (UNet ONNX)
    │  → 심장/폐/종격동 세그멘테이션 + CTR, CP angle, 폐면적비 측정
    ▼
Stage 2a: DenseNet-121 (ONNX)
    │  → 14개 질환 확률 (CheXpert 표준)
    ▼
Stage 2b: YOLOv8 (ONNX)
    │  → 19개 클래스 병변 바운딩박스 탐지 (VinDr-CXR)
    ▼
Stage 3: Clinical Logic Engine
    │  → 14개 규칙 기반 판정 + 교차검증 + 감별진단 + 위험도 분류
    ▼
Stage 4: Cross-Validation Summary
    │  → DenseNet vs YOLO vs Clinical Logic 3중 소스 일치도 요약
    ▼
Stage 5+6: RAG + Report Generation
    │  → rag-svc 유사 케이스 검색 + Bedrock Claude 소견서 생성
    ▼
[최종 응답: findings + summary + report + metadata]
```

---

## 디렉토리 구조 및 파일별 역할

```
chest-svc/
├── main.py                          # FastAPI 앱 진입점, ONNX 모델 lifespan 로딩, /predict 엔드포인트
├── config.py                        # pydantic-settings 환경변수 관리 (모델 경로, Bedrock 설정 등)
├── pipeline.py                      # 6-stage 파이프라인 오케스트레이터 (핵심 파일)
├── Dockerfile                       # Docker 빌드 설정 (빌드 컨텍스트: v3/)
├── requirements.txt                 # Python 의존성 목록
│
├── layer1_segmentation/             # Stage 1: UNet 세그멘테이션
│   ├── __init__.py
│   ├── model.py                     # UNet ONNX 추론 + CTR/CP angle/폐면적비 계산
│   └── preprocessing.py             # 이미지 전처리 (320x320 grayscale)
│
├── layer2_detection/                # Stage 2: 질환 탐지
│   ├── __init__.py
│   ├── densenet.py                  # DenseNet-121 14-label 분류 (224x224 ImageNet 정규화)
│   └── yolo.py                      # YOLOv8 19-class 물체 탐지 (1024x1024 letterbox)
│
├── layer3_clinical_logic/           # Stage 3: 임상 로직 엔진
│   ├── __init__.py
│   ├── engine.py                    # 14개 규칙 순차 실행 + 교차검증 + 감별진단 오케스트레이터
│   ├── models.py                    # 입출력 데이터클래스 (AnatomyMeasurements, DenseNetPredictions 등)
│   ├── cross_validation.py          # DenseNet vs YOLO vs Logic 3중 소스 교차검증
│   ├── differential.py              # 감별진단 엔진 (동반 소견 패턴 매칭)
│   ├── thresholds.py                # 질환별 DenseNet threshold (pos_weight 기반)
│   └── rules/                       # [v2에서 마이그레이션] 14개 질환별 규칙 파일
│       ├── __init__.py
│       ├── atelectasis.py           # 무기폐
│       ├── cardiomegaly.py          # 심비대
│       ├── consolidation.py         # 경화
│       ├── edema.py                 # 폐부종
│       ├── enlarged_cm.py           # 심종격동 비대
│       ├── fracture.py              # 골절
│       ├── lung_lesion.py           # 폐 병변
│       ├── lung_opacity.py          # 폐 음영 (다른 결과에 의존)
│       ├── no_finding.py            # 정상 소견 (전체 결과 확인 후 판정)
│       ├── pleural_effusion.py      # 흉수
│       ├── pleural_other.py         # 기타 흉막 질환
│       ├── pneumonia.py             # 폐렴 (임상정보 + 다른 결과에 의존)
│       ├── pneumothorax.py          # 기흉
│       └── support_devices.py       # 삽입 기구
│
└── report/                          # Stage 5+6: 소견서 생성
    ├── __init__.py
    ├── chest_report_generator.py    # Bedrock Claude 호출 + 응답 파싱
    └── prompt_templates.py          # 시스템/유저 프롬프트 템플릿 (한/영)
```

---

## 팀원이 수정해야 할 파일 목록

### 박현우 주요 수정 포인트

| 파일 | 수정 상황 | 설명 |
|------|-----------|------|
| `pipeline.py` | 파이프라인 순서 변경, 단계 추가/제거 시 | 6단계 실행 순서와 데이터 흐름을 제어하는 핵심 파일 |
| `config.py` | 환경변수 추가 시 | 새 설정값이 필요하면 `Settings` 클래스에 필드 추가 |
| `layer3_clinical_logic/rules/*.py` | 임상 로직 수정 시 | v2에서 복사된 14개 규칙 파일. 임계값, 판정 기준 변경 가능 |
| `layer3_clinical_logic/thresholds.py` | DenseNet threshold 조정 시 | 질환별 양성 판정 기준값 변경 |
| `layer3_clinical_logic/differential.py` | 감별진단 패턴 추가/수정 시 | `DIFFERENTIAL_PATTERNS` 리스트에 새 패턴 추가 |
| `report/prompt_templates.py` | 소견서 프롬프트 커스터마이징 시 | Bedrock Claude에 전달하는 시스템/유저 프롬프트 수정 |
| `layer1_segmentation/model.py` | UNet 모델 교체 시 | ONNX 입출력 형식이 바뀌면 추론 로직 수정 필요 |
| `layer1_segmentation/preprocessing.py` | UNet 전처리 변경 시 | 입력 크기(320x320), 정규화 방식 변경 시 |
| `layer2_detection/densenet.py` | DenseNet 모델 교체 시 | 입력 크기(224x224), 라벨 순서, 정규화 방식 수정 |
| `layer2_detection/yolo.py` | YOLOv8 모델 교체 시 | 입력 크기(1024x1024), 클래스 목록, NMS 파라미터 수정 |
| `main.py` | 새 엔드포인트 추가, 모델 추가 시 | lifespan에서 모델 로딩, 새 라우트 추가 |

### 수정 빈도별 정리

- **자주 수정**: `pipeline.py`, `rules/*.py`, `prompt_templates.py`, `thresholds.py`
- **가끔 수정**: `config.py`, `differential.py`, `main.py`
- **모델 교체 시만**: `model.py`, `densenet.py`, `yolo.py`, `preprocessing.py`

---

## ONNX 모델 파일 위치

모델 파일은 K8s PVC로 런타임에 마운트됩니다. 로컬 테스트 시 직접 경로를 지정하세요.

| 모델 | 파일명 | 크기 (약) | 설명 |
|------|--------|-----------|------|
| UNet | `unet_seg.onnx` | ~85MB | 세그멘테이션 (입력: 1x1x320x320, 출력: mask + view + age + sex) |
| DenseNet-121 | `densenet121.onnx` | ~27MB | 14-질환 분류 (입력: 1x3x224x224, 출력: logits 1x14) |
| YOLOv8 | `yolov8_vindr.onnx` | ~22MB | 19-클래스 탐지 (입력: 1x3x1024x1024, 출력: 1x23xN) |

**기본 모델 디렉토리**: `/app/models` (환경변수 `MODEL_DIR`로 변경 가능)

로컬에서 모델 파일을 준비하려면:
```bash
# 예: 로컬 models 디렉토리에 ONNX 파일 배치
mkdir -p ./models
# unet_seg.onnx, densenet121.onnx, yolov8_vindr.onnx 를 models/ 에 복사
export MODEL_DIR=./models
```

---

## 로컬 실행 방법

### 1. uvicorn 직접 실행

```bash
cd v3/services/chest-svc

# 가상환경 생성 및 활성화
python -m venv .venv
source .venv/bin/activate

# 의존성 설치
pip install -r requirements.txt

# shared 스키마 경로 설정 (Docker 밖에서 실행 시)
export PYTHONPATH="/path/to/v3/shared:$PYTHONPATH"

# 환경변수 설정
export MODEL_DIR=./models          # ONNX 모델 디렉토리
export LOG_LEVEL=DEBUG             # 디버그 로그
export RAG_URL=http://localhost:8001  # rag-svc 주소 (미연결 시 자동 skip)

# 서버 실행
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 2. Docker 실행

```bash
# 빌드 컨텍스트는 v3/ 디렉토리
cd v3

# 빌드
docker build -f services/chest-svc/Dockerfile -t chest-svc:latest .

# 실행 (모델 디렉토리를 볼륨 마운트)
docker run -p 8000:8000 \
  -v /path/to/models:/app/models \
  -e LOG_LEVEL=DEBUG \
  -e BEDROCK_REGION=ap-northeast-2 \
  -e AWS_ACCESS_KEY_ID=... \
  -e AWS_SECRET_ACCESS_KEY=... \
  chest-svc:latest
```

---

## API 스펙

### POST /predict

흉부 X선 이미지를 분석하여 소견서를 생성합니다.

#### 요청 (Request)

```json
{
  "patient_id": "P001",
  "modal": "chest",
  "patient_info": {
    "age": 65,
    "sex": "M",
    "chief_complaint": "흉통, 호흡곤란",
    "history": "고혈압, 당뇨"
  },
  "data": {
    "image_base64": "<base64 인코딩된 흉부 X선 이미지>"
  },
  "context": {
    "prior_results": [
      {
        "modal": "ecg",
        "summary": "정상 동성리듬",
        "findings": {}
      }
    ],
    "report_language": "ko"
  }
}
```

#### 응답 (Response)

```json
{
  "status": "success",
  "modal": "chest",
  "findings": [
    {
      "name": "Cardiomegaly",
      "detected": true,
      "confidence": 0.9,
      "detail": "CTR 0.58 (>0.50); DenseNet 확률 0.82; YOLO bbox 탐지"
    },
    {
      "name": "Pleural_Effusion",
      "detected": false,
      "confidence": 0.1,
      "detail": ""
    }
  ],
  "summary": "Detected: Cardiomegaly | Risk: routine",
  "report": "...(Bedrock Claude가 생성한 전문 소견서)...",
  "metadata": {
    "timings": {
      "segmentation": 0.312,
      "densenet": 0.089,
      "yolo": 0.245,
      "clinical_logic": 0.005,
      "report": 2.134
    },
    "total_time": 2.801,
    "risk_level": "routine",
    "alert_flags": [],
    "detected_count": 1,
    "differential_diagnosis": [],
    "cross_validation_summary": {
      "high_agreement": ["Cardiomegaly"],
      "medium_agreement": [],
      "low_agreement": [],
      "flags": []
    },
    "segmentation_view": "PA",
    "report_metadata": {
      "model_used": "global.anthropic.claude-sonnet-4-6",
      "input_tokens": 2500,
      "output_tokens": 1200,
      "latency_ms": 2100,
      "rag_used": false,
      "report_language": "ko"
    }
  }
}
```

### GET /healthz

Liveness probe (프로세스 생존 확인).

```json
{"status": "ok"}
```

### GET /readyz

Readiness probe (모델 로딩 완료 확인). 모델 미로딩 시 503 반환.

```json
{"status": "ready", "models": ["unet", "densenet", "yolo"]}
```

---

## v2에서 마이그레이션된 파일

아래 파일들은 v2 Lambda 기반 코드에서 v3 K8s 마이크로서비스로 마이그레이션되었습니다.

| 파일 | 마이그레이션 상태 | 비고 |
|------|-------------------|------|
| `layer3_clinical_logic/rules/*.py` (14개) | v2에서 복사됨 | 임상 로직 규칙은 v2와 동일. 필요 시 수정 |
| `layer3_clinical_logic/engine.py` | v2 기반 리팩토링 | 오케스트레이터 구조 유지, import 경로 변경 |
| `layer3_clinical_logic/models.py` | v2에서 복사됨 | 데이터클래스 구조 동일 |
| `layer3_clinical_logic/cross_validation.py` | v2에서 복사됨 | 교차검증 로직 동일 |
| `layer3_clinical_logic/differential.py` | v2에서 복사됨 | 감별진단 패턴 동일 |
| `layer3_clinical_logic/thresholds.py` | v2에서 복사됨 | threshold 값 동일 |
| `report/prompt_templates.py` | v2 기반 수정 | 프롬프트 구조 유지, RAG 섹션 추가 |
| `report/chest_report_generator.py` | v2 기반 리팩토링 | S3 제거, 직접 Bedrock 호출로 변경 |
| `layer1_segmentation/model.py` | v2 기반 리팩토링 | Lambda → ONNX Runtime 직접 호출로 변경 |
| `layer2_detection/densenet.py` | v2 기반 리팩토링 | 동일 |
| `layer2_detection/yolo.py` | v2 기반 리팩토링 | 동일 |

---

## 환경변수 목록

| 변수명 | 기본값 | 설명 |
|--------|--------|------|
| `MODEL_DIR` | `/app/models` | ONNX 모델 파일 디렉토리 경로 |
| `RAG_URL` | `http://rag-svc:8000` | rag-svc 서비스 URL |
| `BEDROCK_REGION` | `ap-northeast-2` | AWS Bedrock 리전 |
| `BEDROCK_MODEL_ID` | `global.anthropic.claude-sonnet-4-6` | Bedrock 모델 ID |
| `BEDROCK_MAX_TOKENS` | `4096` | Bedrock 최대 토큰 수 |
| `BEDROCK_TEMPERATURE` | `0.2` | Bedrock 온도 (첫 시도) |
| `BEDROCK_RETRY_TEMPERATURE` | `0.0` | Bedrock 온도 (재시도) |
| `LOG_LEVEL` | `INFO` | 로그 레벨 (DEBUG/INFO/WARNING/ERROR) |
| `PORT` | `8000` | 서비스 포트 |
