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
    │  → 14개 클래스 병변 바운딩박스 탐지 (VinDr-CXR) + 세그 기반 후처리
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
├── thresholds.py                    # ★ 단일 소스 (Single Source of Truth) — 모든 임계값/상수 중앙 관리
├── Dockerfile                       # Docker 빌드 설정 (빌드 컨텍스트: v3/)
├── requirements.txt                 # Python 의존성 목록
│
├── layer1_segmentation/             # Stage 1: UNet 세그멘테이션
│   ├── __init__.py
│   ├── model.py                     # UNet ONNX 추론 + CTR/CP angle/폐면적비 + 마스크 후처리
│   └── preprocessing.py             # 이미지 전처리 (320x320 grayscale)
│
├── layer2_detection/                # Stage 2: 질환 탐지
│   ├── __init__.py
│   ├── densenet.py                  # DenseNet-121 14-label 분류 (224x224 ImageNet 정규화)
│   ├── yolo.py                      # YOLOv8 14-class 물체 탐지 (1024x1024 letterbox)
│   └── yolo_postprocess.py          # YOLO 후처리 (세그 기반 보정, CTR 보완, 경계 FP 필터)
│
├── layer3_clinical_logic/           # Stage 3: 임상 로직 엔진
│   ├── __init__.py
│   ├── engine.py                    # 14개 규칙 순차 실행 + 교차검증 + 감별진단 오케스트레이터
│   ├── models.py                    # 입출력 데이터클래스 (AnatomyMeasurements, DenseNetPredictions 등)
│   ├── cross_validation.py          # DenseNet vs YOLO vs Logic 3중 소스 교차검증
│   ├── differential.py              # 감별진단 엔진 (동반 소견 패턴 매칭)
│   ├── pertinent_negatives.py       # 유의미한 음성 소견 판정
│   ├── thresholds.py                # → 루트 thresholds.py 재수출 (하위 호환)
│   └── rules/                       # 14개 질환별 규칙 파일
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
| `thresholds.py` (루트) | 임계값/상수 변경 시 | ★ 단일 소스 — DenseNet, YOLO, CTR, CP angle, 폐면적비 등 모든 상수 |
| `layer3_clinical_logic/differential.py` | 감별진단 패턴 추가/수정 시 | `DIFFERENTIAL_PATTERNS` 리스트에 새 패턴 추가 |
| `report/prompt_templates.py` | 소견서 프롬프트 커스터마이징 시 | Bedrock Claude에 전달하는 시스템/유저 프롬프트 수정 |
| `layer1_segmentation/model.py` | UNet 모델 교체 시 | ONNX 입출력 형식이 바뀌면 추론 로직 수정 필요 |
| `layer1_segmentation/preprocessing.py` | UNet 전처리 변경 시 | 입력 크기(320x320), 정규화 방식 변경 시 |
| `layer2_detection/densenet.py` | DenseNet 모델 교체 시 | 입력 크기(224x224), 라벨 순서, 정규화 방식 수정 |
| `layer2_detection/yolo.py` | YOLOv8 모델 교체 시 | 입력 크기(1024x1024), 클래스 목록, NMS 파라미터 수정 |
| `main.py` | 새 엔드포인트 추가, 모델 추가 시 | lifespan에서 모델 로딩, 새 라우트 추가 |

### 수정 빈도별 정리

- **자주 수정**: `thresholds.py` (루트), `rules/*.py`, `prompt_templates.py`, `pipeline.py`
- **가끔 수정**: `config.py`, `differential.py`, `yolo_postprocess.py`, `main.py`
- **모델 교체 시만**: `model.py`, `densenet.py`, `yolo.py`, `preprocessing.py`

---

## ONNX 모델 파일 위치

모델 파일은 K8s PVC로 런타임에 마운트됩니다. 로컬 테스트 시 직접 경로를 지정하세요.

| 모델 | 파일명 | 크기 (약) | 설명 |
|------|--------|-----------|------|
| UNet | `unet_seg.onnx` | ~85MB | 세그멘테이션 (입력: 1x1x320x320, 출력: mask + view + age + sex) |
| DenseNet-121 | `densenet121.onnx` | ~27MB | 14-질환 분류 (입력: 1x3x224x224, 출력: logits 1x14) |
| YOLOv8 | `yolov8_vindr.onnx` | ~22MB | 14-클래스 탐지 (입력: 1x3x1024x1024, 출력: 1x18xN, VinDr-CXR) |

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

## v3 QA 개선사항 (2026-03-26)

83건 MIMIC-CXR PA 이미지 + CheXpert GT 라벨 기반 전수 검증 후 적용된 개선사항입니다.

### 구조 개선

| 항목 | Before | After |
|------|--------|-------|
| 하드코딩 매직넘버 | 137건 / 18파일 산재 | **0건** — `thresholds.py` 단일소스 |
| DenseNet 임계값 | 문헌 기반 추정값 | **Youden's J 최적값** (5,000장 PA 기반) |
| YOLO 클래스 | 19개 (미사용 포함) | **14개** (VinDr-CXR 유효 클래스) |
| Lateral View | 처리 없음 (마스크 붕괴) | **자동 거부 게이트** (view 분류 활용) |

### 검출 품질 개선

| 항목 | Before | After | 효과 |
|------|--------|-------|------|
| Pneumothorax FP | 22건 | 8건 | -63% (세그 보조검출 + 교차배제) |
| Fracture FP | 8건 | 5건 | -38% (threshold 상향) |
| Enlarged_CM FP | 12건 | 7건 | -42% (2차소견 분류) |
| 평균 양성 소견 | ~11건/케이스 | **4.0건** | -64% |
| Cardiomegaly FN | 17건 | **0건** | CTR 기반 보완 (supplement_cardiomegaly) |

### 추가된 기능

- **마스크 후처리**: connected component 분석 + 횡격막 클리핑 (L Lung 소실, Heart 하방 확장 방지)
- **YOLO 후처리**: 세그 기반 bbox 보정, CTR 기반 Cardiomegaly 보완, 경계 FP 필터
- **PTX 세그 보조 검출**: 폐면적 급감 + 기관 편위로 YOLO 미검출 보완 (교차배제 포함)
- **14개 Rule 개선**: severity/confidence 체계, 2차소견 분류, 감별진단 3패턴 추가
- **교차검증 override**: 2/3 소스 양성 시 Rule 재검토 플래그
- **프론트엔드**: 드롭다운 테스트 UI (83건), 측정 SVG 오버레이 라벨링, Lateral 경고 배너

### 남은 과제

| 질환 | GT 대비 배율 | 원인 |
|------|-------------|------|
| Consolidation | 4.5x | DenseNet AUC 0.682 (모델 한계) |
| Edema | 3.3x | borderline 과검출 |
| Lung_Lesion | 6.0x | GT 2건 (통계 불안정) |
| Pleural_Other | 8.0x | GT 1건 (통계 불안정) |

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
