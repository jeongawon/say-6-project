# chest-svc — 흉부 X-Ray AI 분석 마이크로서비스

> **담당: 박현우 | 프로젝트 6팀**
>
> 흉부 X선 영상을 입력받아 14개 질환을 자동 판정하고, 임상 소견서를 생성하는 AI 마이크로서비스입니다.
> ONNX 모델 3개(세그멘테이션 + 분류 + 탐지)의 결과를 규칙 기반 임상 로직으로 교차검증한 뒤,
> AWS Bedrock Claude가 전문의 수준의 한글 소견서를 작성합니다.

---

## 1. 한눈에 보기

| 항목 | 내용 |
|------|------|
| 프레임워크 | FastAPI + uvicorn (ASGI) |
| AI 모델 | UNet (세그멘테이션) + DenseNet-121 (분류) + YOLOv8 (탐지) |
| 모델 런타임 | ONNX Runtime (CPU) |
| 소견서 생성 | AWS Bedrock Claude Sonnet |
| 유사 케이스 | rag-svc 연동 (선택) |
| 코드 규모 | **6,729줄 / 39개 Python 파일** |
| 판정 질환 | 14개 (CheXpert 표준) |
| 포트 | 8000 |

---

## 2. 14개 판정 질환

| # | 영문명 | 한글명 | 설명 |
|---|--------|--------|------|
| 1 | Atelectasis | 무기폐 | 폐의 일부가 허탈(collapse)된 상태 |
| 2 | Cardiomegaly | 심비대 | 심장 크기 확대 (CTR > 0.50) |
| 3 | Consolidation | 경화 | 폐포가 액체/세포로 채워진 상태 |
| 4 | Edema | 폐부종 | 폐에 체액이 고인 상태 |
| 5 | Enlarged Cardiomediastinum | 심종격동 비대 | 종격동(가슴 중앙) 확장 |
| 6 | Fracture | 골절 | 늑골 등의 골절 |
| 7 | Lung Lesion | 폐 병변 | 결절/종괴 등 국소 병변 |
| 8 | Lung Opacity | 폐 음영 | 비특이적 음영 증가 |
| 9 | No Finding | 정상 | 이상 소견 없음 |
| 10 | Pleural Effusion | 흉수 | 흉막강에 체액 저류 |
| 11 | Pleural Other | 기타 흉막 질환 | 흉막 비후/석회화 등 |
| 12 | Pneumonia | 폐렴 | 감염성 폐 경화 |
| 13 | Pneumothorax | 기흉 | 흉막강에 공기 유입 |
| 14 | Support Devices | 삽입 기구 | ETT, 중심정맥관, 흉관 등 |

---

## 3. 파이프라인 구조

```
┌─────────────────────────────────────────────────────────────────┐
│                    POST /predict (이미지 입력)                    │
└─────────────┬───────────────────────────────────────────────────┘
              ▼
┌─────────────────────────────┐
│ ★ Lateral View Gate         │  view == "Lateral" → 즉시 거부
│   (PA/AP만 분석 가능)        │  "측면 촬영은 분석 불가" 반환
└─────────────┬───────────────┘
              ▼
┌─────────────────────────────┐
│ Stage 1: Segmentation       │  UNet ONNX (320x320)
│   - 폐/심장/종격동 마스크    │  → 마스크 후처리 (connected component)
│   - CTR, CP angle 측정      │  → 횡격막 클리핑
│   - 폐면적비, 종격동 폭     │  → view 분류 (AP/PA/Lateral)
└─────────────┬───────────────┘
              ▼
┌──────────────────┐  ┌──────────────────┐
│ Stage 2a:        │  │ Stage 2b:        │
│ DenseNet-121     │  │ YOLOv8           │   ← 병렬 실행
│ 14-질환 확률     │  │ 14-클래스 bbox   │
│ (CheXpert)       │  │ (VinDr-CXR)      │
└────────┬─────────┘  └────────┬─────────┘
         │                     │
         │  ┌──────────────────┘
         ▼  ▼
┌─────────────────────────────┐
│ YOLO 후처리                  │  세그 기반 bbox 보정
│   - CTR 기반 Cardiomegaly   │  CTR≥0.53 & YOLO 미검출 → 보완
│   - 경계 FP 필터 (10%)      │  이미지 가장자리 Other_lesion 제거
│   - per-class threshold     │  PTX 0.15 / Effusion 0.20 / 기타 0.25
└─────────────┬───────────────┘
              ▼
┌─────────────────────────────┐
│ Stage 3: Clinical Logic     │  14개 질환별 Rule 순차 실행
│   Phase 1: 독립 판정 (10개) │  DenseNet + YOLO + 해부학 지표
│   Phase 2: 교차 의존 (3개)  │  Consolidation → Lung Opacity → Pneumonia
│   Phase 3: 최종 판정 (1개)  │  No Finding (전체 결과 확인 후)
│   + 교차검증 + 감별진단     │  3중 소스 일치도 + 패턴 매칭
└─────────────┬───────────────┘
              ▼
┌─────────────────────────────┐
│ Stage 5+6: RAG + Report     │  (선택적 — skip_stages로 비활성화 가능)
│   - rag-svc 유사 케이스     │  cosine similarity 기반 검색
│   - Bedrock Claude 소견서   │  한글/영문 전문의 소견서 생성
└─────────────┬───────────────┘
              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 응답: findings(14개) + summary + report + metadata              │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. 디렉토리 구조

```
chest-svc/                              # 6,729줄 / 39파일
├── main.py                    (241줄)  # FastAPI 진입점, ONNX lifespan, /predict
├── config.py                   (41줄)  # pydantic-settings 환경변수
├── pipeline.py                (514줄)  # 6-stage 오케스트레이터 (핵심)
├── thresholds.py              (312줄)  # ★ Single Source of Truth — 모든 임계값
├── Dockerfile                  (44줄)  # Docker 빌드 (빌드 컨텍스트: v3/)
├── requirements.txt            (11줄)  # 의존성 (fastapi, onnxruntime, scipy 등)
│
├── layer1_segmentation/       (743줄)  # Stage 1
│   ├── model.py               (706줄)  # UNet 추론 + CTR/CP/폐면적 + 마스크 후처리
│   └── preprocessing.py        (36줄)  # 320x320 grayscale 전처리
│
├── layer2_detection/          (751줄)  # Stage 2
│   ├── densenet.py            (135줄)  # DenseNet-121 14-label (224x224)
│   ├── yolo.py                (275줄)  # YOLOv8 14-class (1024x1024)
│   └── yolo_postprocess.py    (340줄)  # 세그 보정 + CTR 보완 + 경계 필터
│
├── layer3_clinical_logic/    (3,070줄)  # Stage 3
│   ├── engine.py              (169줄)  # 14-Rule 오케스트레이터
│   ├── models.py              (112줄)  # 데이터클래스 (입출력 스키마)
│   ├── cross_validation.py     (64줄)  # DenseNet vs YOLO vs Logic 교차검증
│   ├── differential.py        (213줄)  # 감별진단 패턴 매칭
│   ├── pertinent_negatives.py (118줄)  # 유의미한 음성 소견
│   ├── thresholds.py            (6줄)  # → 루트 thresholds.py 재수출
│   └── rules/                (1,543줄)  # 14개 질환별 규칙
│       ├── atelectasis.py     (112줄)  # 무기폐
│       ├── cardiomegaly.py     (77줄)  # 심비대 (CTR + DenseNet + YOLO)
│       ├── consolidation.py   (199줄)  # 경화 (DenseNet 게이트 포함)
│       ├── edema.py           (135줄)  # 폐부종 (SpO2 연동)
│       ├── enlarged_cm.py     (103줄)  # 심종격동 비대
│       ├── fracture.py         (96줄)  # 골절
│       ├── lung_lesion.py     (135줄)  # 폐 병변 (Fleischner 기준)
│       ├── lung_opacity.py    (132줄)  # 폐 음영 (2차소견 감별)
│       ├── no_finding.py      (103줄)  # 정상 (전체 확인 후 판정)
│       ├── pleural_effusion.py(120줄)  # 흉수 (CP angle + YOLO)
│       ├── pleural_other.py    (88줄)  # 기타 흉막
│       ├── pneumonia.py       (156줄)  # 폐렴 (5단계 감별)
│       ├── pneumothorax.py    (150줄)  # 기흉 (세그 보조 검출)
│       └── support_devices.py (105줄)  # 삽입 기구
│
├── report/                    (591줄)  # Stage 5+6
│   ├── chest_report_generator.py (440줄) # Bedrock Claude 호출 + 파싱
│   └── prompt_templates.py    (150줄)  # 시스템/유저 프롬프트 (한/영)
│
└── static/
    └── index.html           (1,425줄)  # 테스트 UI (드롭다운 83건)
```

---

## 5. API 문서

### 5.1 POST /predict — 흉부 X선 분석

#### 요청

```json
{
  "patient_id": "P-2024-001",
  "modal": "chest",
  "patient_info": {
    "age": 72,
    "sex": "M",
    "chief_complaint": "호흡곤란, 하지 부종",
    "history": ["고혈압", "당뇨"]
  },
  "data": {
    "image_base64": "<base64 인코딩된 흉부 X선 JPEG/PNG>"
  },
  "context": {
    "skip_stages": ["rag", "report"],
    "report_language": "ko",
    "prior_results": [
      { "modal": "ecg", "summary": "정상 동성리듬" }
    ]
  }
}
```

| 필드 | 필수 | 설명 |
|------|------|------|
| `patient_id` | O | 환자 식별자 |
| `modal` | O | `"chest"` 고정 |
| `patient_info.age` | O | 나이 |
| `patient_info.sex` | O | `"M"` / `"F"` |
| `patient_info.chief_complaint` | - | 주소 (한글 가능) |
| `patient_info.history` | - | 과거력 리스트 |
| `data.image_base64` | O | Base64 인코딩 이미지 |
| `context.skip_stages` | - | `["rag", "report"]` → RAG/소견서 스킵 (빠른 테스트용) |
| `context.report_language` | - | `"ko"` (기본) / `"en"` |

#### 응답

```json
{
  "status": "success",
  "modal": "chest",
  "findings": [
    {
      "name": "Cardiomegaly",
      "detected": true,
      "confidence": 0.7,
      "detail": "CTR 0.5204 (>0.50); DenseNet 0.60; YOLO bbox conf 0.42",
      "secondary": false,
      "severity": "mild",
      "location": null,
      "recommendation": "추적 관찰 권장 (6개월 후 재검)"
    },
    {
      "name": "Lung_Opacity",
      "detected": true,
      "confidence": 0.4,
      "detail": "DenseNet Lung_Opacity: 0.70; Edema에 의한 음영 (2차)",
      "secondary": true,
      "severity": "mild",
      "location": null,
      "recommendation": null
    }
  ],
  "summary": "Detected: Cardiomegaly, Pleural_Effusion, Edema ... | Risk: critical",
  "report": "...(Bedrock Claude 한글 소견서)...",
  "risk_level": "critical",
  "pertinent_negatives": ["기흉 없음"],
  "suggested_next_actions": [],
  "metadata": {
    "timings": {
      "segmentation": 0.31,
      "densenet": 0.09,
      "yolo": 0.25,
      "clinical_logic": 0.01,
      "report": 0.0
    },
    "total_time": 0.70,
    "detected_count": 8,
    "segmentation_view": "AP",
    "measurements": {
      "ctr": 0.5204,
      "ctr_status": "cardiomegaly",
      "cp_angle_left": 74.05,
      "cp_angle_right": 87.14,
      "lung_area_ratio": 1.331,
      "heart_width_px": 1098,
      "thorax_width_px": 2111
    },
    "yolo_detections": [
      { "class_name": "Cardiomegaly", "confidence": 0.42, "bbox": [1242, 1280, 2349, 2170] }
    ],
    "mask_base64": "<base64 RGBA PNG — 마스크 오버레이>",
    "image_size": [3056, 2544],
    "cross_validation_summary": {
      "high_agreement": ["Cardiomegaly"],
      "medium_agreement": ["Pleural_Effusion"],
      "flags": []
    },
    "differential_diagnosis": ["심인성 폐부종", "울혈성 심부전"]
  }
}
```

#### Finding 필드 설명

| 필드 | 타입 | 설명 |
|------|------|------|
| `name` | string | 질환명 (14개 중 하나) |
| `detected` | boolean | 양성 판정 여부 |
| `confidence` | float | 신뢰도 (0.0~1.0) |
| `detail` | string | 판정 근거 (DenseNet 확률, CTR 값, YOLO bbox 등) |
| `secondary` | boolean | `true` = 다른 질환에 의한 2차 소견 |
| `severity` | string? | `mild` / `moderate` / `severe` / `critical` / `null` |
| `location` | string? | `bilateral` / `left` / `right` / 폐엽명 / `null` |
| `recommendation` | string? | 추천 후속 검사/조치 |

#### Lateral View 거부 응답

Lateral(측면) X선은 PA/AP 전용 모델로 분석할 수 없어 자동 거부됩니다.

```json
{
  "status": "unsupported_view",
  "modal": "chest",
  "findings": [],
  "metadata": { "lateral_rejected": true, "segmentation_view": "Lateral" }
}
```

### 5.2 GET /healthz — Liveness Probe

```json
{"status": "ok"}
```

### 5.3 GET /readyz — Readiness Probe

```json
{"status": "ready", "models": ["unet", "densenet", "yolo"]}
```

모델 미로딩 시 HTTP 503 반환.

---

## 6. ONNX 모델 스펙

### 6.1 모델 파일

| 모델 | 파일명 | 크기 | 입력 | 출력 |
|------|--------|------|------|------|
| UNet | `unet.onnx` | ~85MB | `(1,1,320,320)` float32 | mask `(1,4,320,320)` + view `(1,3)` + age `(1,1)` + sex `(1,1)` |
| DenseNet-121 | `densenet.onnx` | ~27MB | `(1,3,224,224)` float32 | logits `(1,14)` |
| YOLOv8 | `yolov8.onnx` | ~22MB | `(1,3,1024,1024)` float32 | `(1,18,N)` boxes+classes |

기본 경로: `/app/models` (환경변수 `MODEL_DIR`로 변경)

### 6.2 DenseNet 임계값 (Youden's J 최적화)

5,000장 MIMIC-CXR PA 이미지 기반 ROC 분석으로 산출된 최적 임계값입니다.

| 질환 | 임계값 | AUC | 비고 |
|------|--------|-----|------|
| Pleural_Effusion | 0.51 | 0.928 | 최고 AUC |
| Pneumothorax | 0.75 | 0.895 | 세그 보조 검출이 FN 커버 |
| Edema | 0.67 | 0.847 | |
| Consolidation | 0.55 | 0.837 | AUC 높으나 Rule에서 추가 필터링 |
| Cardiomegaly | 0.55 | 0.819 | CTR 보완이 FN 커버 |
| Enlarged_CM | 0.64 | 0.800 | |
| Pneumonia | 0.52 | 0.786 | |
| Lung_Opacity | 0.45 | 0.634 | AUC 낮음 — Rule 감별에 의존 |
| Atelectasis | 0.50 | - | GT 불충분 → 기본값 |
| Fracture | 0.70 | 0.857 | FP 방지 위해 보수적 |
| Support_Devices | 0.68 | 0.605 | |
| Lung_Lesion | 0.70 | - | GT 불충분 → 보수적 |
| Pleural_Other | 0.70 | - | GT 불충분 → 보수적 |
| No_Finding | 0.70 | - | |

모든 임계값은 `thresholds.py` 1개 파일에서 관리됩니다.

### 6.3 UNet 세그멘테이션 클래스

| Class ID | 영역 | 마스크 색상 |
|----------|------|------------|
| 0 | Background | 투명 |
| 1 | Left Lung | 파랑 (rgba 0,100,255,100) |
| 2 | Right Lung | 초록 (rgba 0,200,100,100) |
| 3 | Heart | 빨강 (rgba 255,50,50,120) |
| 4+ | Mediastinum | 노랑 (rgba 255,255,0,80) |

---

## 7. QA 검증 결과

### 83건 MIMIC-CXR GT 대비 (2026-03-26)

| 질환 | GT | 검출 | 배율 | 판정 |
|------|-----|------|------|------|
| Pleural_Effusion | 20 | 30 | 1.5x | ✅ 양호 |
| Support_Devices | 18 | 21 | 1.2x | ✅ 양호 |
| Fracture | 5 | 5 | 1.0x | ✅ 양호 |
| Enlarged_CM | 8 | 7 | 0.9x | ✅ 양호 |
| Pneumothorax | 4 | 8 | 2.0x | ⚠️ 과검출 |
| Lung_Opacity | 22 | 45 | 2.0x | ⚠️ 과검출 |
| Pneumonia | 8 | 20 | 2.5x | ⚠️ 과검출 |
| Atelectasis | 20 | 45 | 2.2x | ⚠️ 과검출 |
| Cardiomegaly | 14 | 38 | 2.7x | ❌ CTR 보완 영향 |
| Consolidation | 6 | 27 | 4.5x | ❌ DenseNet AUC 0.682 |
| Edema | 7 | 23 | 3.3x | ❌ borderline 과검출 |

### 주요 개선 성과

| 항목 | Before → After | 효과 |
|------|---------------|------|
| Pneumothorax FP | 22 → 8건 | -63% |
| Cardiomegaly FN | 17 → 0건 | CTR 기반 보완 |
| 평균 양성 소견 | ~11건 → 4.0건 | -64% |
| Lateral View | 미처리 → 자동 거부 | 11건 F등급 해소 |
| 하드코딩 | 137건 → 0건 | thresholds.py 단일소스 |

---

## 8. 배포/운영

### 로컬 실행

```bash
cd v3/services/chest-svc

# 가상환경
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 환경변수
export MODEL_DIR=./models
export LOG_LEVEL=DEBUG
export PYTHONPATH="../../shared:$PYTHONPATH"

# 실행
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Docker 실행

```bash
cd v3
docker build -f services/chest-svc/Dockerfile -t chest-svc:latest .
docker run -p 8000:8000 \
  -v /path/to/models:/app/models \
  -e LOG_LEVEL=DEBUG \
  -e BEDROCK_REGION=ap-northeast-2 \
  chest-svc:latest
```

### K8s 배포

K8s 매니페스트: `v3/k8s/base/chest-svc.yaml`
- Deployment: 1 replica, CPU 1core / Memory 2Gi
- Service: ClusterIP
- Health: `/healthz` (liveness), `/readyz` (readiness)
- Config: `common-config` + `dr-ai-config` ConfigMap
- Storage: PVC `/models` (ReadOnlyMany)

### 환경변수

| 변수명 | 기본값 | 설명 |
|--------|--------|------|
| `MODEL_DIR` | `/app/models` | ONNX 모델 디렉토리 |
| `RAG_URL` | `http://rag-svc:8000` | RAG 서비스 URL |
| `BEDROCK_REGION` | `ap-northeast-2` | AWS Bedrock 리전 |
| `BEDROCK_MODEL_ID` | `global.anthropic.claude-sonnet-4-6` | Bedrock 모델 |
| `BEDROCK_MAX_TOKENS` | `4096` | 소견서 최대 토큰 |
| `BEDROCK_TEMPERATURE` | `0.2` | 생성 온도 |
| `LOG_LEVEL` | `INFO` | 로그 레벨 |

---

## 9. 알려진 제한사항 + 향후 과제

### 제한사항

| 항목 | 설명 |
|------|------|
| **Lateral View** | PA/AP만 지원. 측면 촬영은 자동 거부됨 |
| **Consolidation 과검출** | DenseNet AUC 0.682 — 모델 판별력 자체의 한계 |
| **AP 뷰 CTR** | AP 촬영 시 심장 확대 → CTR 과대추정 (0.55 보정 적용) |
| **GT 부족 질환** | Lung_Lesion, Pleural_Other — 83건 중 GT 각 2건, 1건 |
| **단일 이미지** | 시리즈 비교(이전 영상 대비 변화) 미지원 |

### 향후 개선 방향

1. **5,000장 전체 Youden's J 재계산** — Consolidation, Atelectasis 임계값 최적화
2. **DenseNet 파인튜닝** — MIMIC-CXR 데이터로 추가 학습 (Consolidation AUC 개선)
3. **YOLO 모델 업그레이드** — VinDr-CXR v2 또는 자체 학습
4. **시리즈 비교** — 이전 영상과의 변화 감지 (follow-up 판정)
5. **분산 추적** — OpenTelemetry 연동 (k8s 환경)
