# ECG Lambda → v3 K8s 통합 분석서

> **목적**: 팀원의 Lambda ECG 프로젝트 기능 분석 + v3 ecg-svc 통합 계획
>
> **소스**: `say-6-project-feature-MIMIC-ECG/` (Lambda 기반)
> **타겟**: `v3/services/ecg-svc/` (K8s 기반)
> **작성일**: 2026-03-30
> **상태**: 분석 완료 (v2 — 수정사항 7건 반영), Plan 수립 대기
> **수정 기반**: `ECG_INTEGRATION_MODIFICATIONS.md` (7개 수정사항 전량 반영)

---

## Part 1: Lambda ECG 프로젝트 기능 분석

### 1.1 프로젝트 구조

```
say-6-project-feature-MIMIC-ECG/
├── app/
│   ├── main.py                  # FastAPI + Mangum Lambda 핸들러
│   ├── schemas.py               # Pydantic 데이터 모델 (PatientInfo 확장)
│   ├── inference.py             # 핵심: ONNX 13-class 추론 엔진
│   ├── signal_processing.py     # HR/QTc 신호 처리
│   ├── model_loader.py          # ONNX 모델 로딩 (S3/로컬/EFS)
│   └── static/
│       └── index.html           # 테스트 대시보드 UI
├── deploy/
│   ├── Dockerfile               # K8s용 Docker 이미지
│   └── k8s/                     # K8s manifest (base + overlays)
├── scripts/
│   └── upload_signals_to_s3.py  # WFDB → .npy 변환 + S3 업로드
├── tests/
│   └── test_inference.py        # 단위 테스트
├── Dockerfile.lambda            # Lambda 컨테이너 이미지
├── requirements.txt             # K8s 의존성
└── requirements-lambda.txt      # Lambda 의존성
```

### 1.2 핵심 기능: ONNX ResNet ML 모델 추론

#### ML 모델 스펙

| 항목 | 값 |
|------|-----|
| **모델 파일** | `ecg_resnet.onnx` (ResNet CNN) |
| **입력 shape** | `(1, 12, 5000)` — 12리드, 500Hz, 10초 |
| **출력** | 13개 class logits → sigmoid → 확률값 [0,1] |
| **런타임** | ONNX Runtime (CUDA 우선 → CPU 폴백) |
| **S3 위치** | `s3://say2-6team/models/ecg_resnet.onnx` |

#### 13개 ECG 병리 분류

| # | Class | 한글명 | 임계값 | 카테고리 |
|---|-------|--------|--------|----------|
| 1 | **stemi** | ST분절 상승 심근경색 | 0.250 | 🔴 응급 |
| 2 | **vfib_vtach** | 심실세동/빈맥 | 0.170 | 🔴 응급 |
| 3 | **avblock_3rd** | 3도 방실차단 | 0.470 | 🔴 응급 |
| 4 | **pe** | 폐색전증 | 0.505 | 🟡 긴급 |
| 5 | **nstemi** | 비ST상승 심근경색 | 0.340 | 🟡 긴급 |
| 6 | **afib** | 심방세동 | 0.345 | 🟡 긴급 |
| 7 | **svt** | 상심실성 빈맥 | 0.345 | 🟡 긴급 |
| 8 | **heart_failure** | 심부전 | 0.835 | ⚪ 일반 |
| 9 | **sepsis** | 패혈증 | 0.530 | ⚪ 일반 |
| 10 | **hyperkalemia** | 고칼륨혈증 | 0.471 | 🔴 응급 |
| 11 | **hypokalemia** | 저칼륨혈증 | 0.815 | ⚪ 일반 |
| 12 | **lbbb** | 좌각차단 | 0.350 | ⚪ 일반 |
| 13 | **arrhythmia** | 부정맥 | 0.720 | ⚪ 일반 |

#### 탐지 알고리즘 상세

```
[Raw Signal (12, 5000)]
        ↓
[1] Per-lead Z-score Normalization
    normalized = (signal - mean) / std
        ↓
[2] ONNX Inference
    logits = model.run(normalized)
    probs = sigmoid(logits)  → 13개 확률값
        ↓
[3] Threshold-Based Detection
    각 class별 커스텀 임계값 적용
        ↓
[4] Emergency Label Filter (핵심!)
    ┌─ 응급 라벨 (stemi, vfib_vtach, avblock_3rd, hyperkalemia)
    │   → 임계값만 넘으면 무조건 탐지 (마진 필터 바이패스)
    │   → 생명 위협 질환 놓침 방지
    └─ 비응급 라벨
        → (확률 - 임계값) >= DETECTION_MARGIN(0.10) 일 때만 탐지
        → 오탐(False Positive) 감소 목적
        ↓
[5] Risk Classification
    Critical: STEMI, VFib, AVBlock → 즉시 개입
    Urgent:   NSTEMI, PE, SVT, Hyperkalemia → 빠른 평가
    Routine:  나머지
```

#### 알려진 모델 한계

| 질환 | 문제 | 비고 |
|------|------|------|
| **hyperkalemia** | FP율 55% | 코드 주석: "재훈련 필요" |
| **PE** | FP 감소 20%만 달성 | 목표 30% 미달 |
| **SVT** | FP 감소 20%만 달성 | 목표 30% 미달 |

### 1.3 신호 처리 (signal_processing.py)

#### Heart Rate 계산

```python
def compute_hr(signal_array, fs=500):
    # Lead II (index 1) 사용
    # scipy.signal.find_peaks로 R-peak 검출
    # - distance=150 samples (300ms 최소 간격)
    # - height=0.3 (최소 진폭)
    # RR interval → HR(bpm) = 60 / mean(RR)
```

#### QTc 보정 (Bazett 공식)

```python
def compute_qtc(hr):
    # QT baseline = 400ms (근사값)
    # QTc = QT / sqrt(RR_sec)
    # RR_sec = 60 / HR
```

### 1.4 모델 로딩 (model_loader.py)

**Lambda 원본 로딩 우선순위 (4단계 폴백):**

```
1. MODEL_PATH 환경변수 (K8s: /mnt/efs/models/ecg_resnet.onnx)
2. /mnt/efs/models/ (EFS 마운트)
3. models/ (로컬 디렉토리)
4. S3 다운로드 → /tmp/ (Lambda 폴백)
   - 버킷: MODEL_BUCKET (say2-6team)
   - 키: MODEL_KEY (models/ecg_resnet.onnx)
```

> ⚠️ **v3 통합 시 단순화 예정** — S3 폴백 제거, K8s 볼륨 마운트만 사용 (수정사항 #2 참조)

**ONNX 세션 생성:**
- Provider: CUDA → CPU 자동 폴백
- 세션 캐싱: 한 번 로드하면 재사용

### 1.5 데이터 스키마

#### 입력: PredictRequest

```python
{
    "patient_id": "test-001",
    "patient_info": {
        "age": 65,
        "sex": "M",
        "chief_complaint": "흉통",
        "history": [],
        # ── 활력징후 (Optional, 추가됨) ──
        "temperature": 37.5,        # ℃
        "blood_pressure": "130/85", # 수축기/이완기
        "spo2": 98.0,              # %
        "respiratory_rate": 16      # /min
    },
    "data": {
        "signal_path": "s3://bucket/path/signal.npy",
        "leads": 12
    },
    "context": {
        "previous_findings": "CXR: cardiomegaly"
    }
}
```

#### 출력: PredictResponse

```python
{
    "status": "success",
    "modal": "ecg",
    "findings": [
        {
            "name": "ST분절 상승 심근경색 (STEMI)",
            "detected": true,
            "confidence": 0.87,
            "detail": "임계값 0.25 기준 감지됨 (확률: 0.87)",
            "severity": "critical",
            "recommendation": "즉각적인 심장 카테터실 활성화 권고"
        },
        // ... 13개 findings
    ],
    "summary": "12-lead ECG 분석: 1개 소견 감지...",
    "report": "ECG Report: ...",
    "risk_level": "critical",
    "pertinent_negatives": ["NSTEMI 음성", "심방세동 음성"],
    "suggested_next_actions": [
        {"action": "혈액검사", "reason": "Troponin 확인", "urgency": "urgent"}
    ],
    "metadata": {
        "hr": 78,
        "qtc": 412,
        "leads": 12,
        "sampling_rate": 500,
        "duration_sec": 10,
        "inference_time_ms": 45
    }
}
```

### 1.6 엔드포인트

#### POST /predict (핵심)

| 항목 | 설명 |
|------|------|
| **입력** | PredictRequest (patient_info + signal_path) |
| **처리** | S3에서 .npy 로드 → normalize → ONNX 추론 → 임계값 판정 |
| **출력** | PredictResponse (13 findings + risk_level + report) |
| **소요시간** | ~50-200ms (모델 로드 후) |

#### POST /simulate (MIMIC-IV 연동) — ❌ v3 통합 시 제거

| 항목 | 설명 |
|------|------|
| **입력** | `{"subject_id": 10019477, "chief_complaint": "흉통"}` |
| **처리** | MIMIC-IV S3에서 환자정보(patients.csv), 활력징후(vitalsign.csv), ECG 신호(.npy) 자동 조회 |
| **출력** | PredictResponse (predict와 동일) |
| **의존성** | pandas (CSV 파싱), MIMIC-IV 데이터셋 (S3) |
| **용도** | 데모/테스트 — 실제 MIMIC 환자 데이터로 시뮬레이션 |

> ⚠️ **v3 제거 사유**: v3 아키텍처에서는 orchestrator가 환자 데이터를 관리하고 모달에 전달함.
> ecg-svc가 직접 환자 DB/S3에 접근하는 건 설계 위반. pandas 의존성도 함께 제거.

#### GET / (테스트 대시보드)

| 항목 | 설명 |
|------|------|
| **기능** | 웹 UI에서 샘플 ECG 선택 → /predict 호출 → 결과 시각화 |
| **샘플** | stemi, normal, afib, vfib, avblock (S3) |
| **파일** | `app/static/index.html` |

### 1.7 의존성

| 패키지 | 버전 | 용도 | K8s 필수 |
|--------|------|------|:--------:|
| fastapi | 0.115.0 | 웹 프레임워크 | ✅ |
| uvicorn | 0.30.0 | ASGI 서버 | ✅ |
| pydantic | 2.7.0 | 데이터 검증 | ✅ |
| numpy | 1.26.4 | 신호 데이터 처리 | ✅ |
| scipy | 1.13.0 | R-peak 검출 (find_peaks) | ✅ |
| onnxruntime | 1.18.0 | ML 모델 추론 | ✅ |
| boto3 | 1.34.0 | S3 접근 (모델/신호) | ✅ |
| mangum | 0.17.0 | Lambda 어댑터 | ❌ 제거 (Lambda 전용) |
| pandas | 2.2.2 | MIMIC CSV 파싱 | ❌ 제거 (/simulate 제거로 불필요) |

### 1.8 K8s 배포 설정 (팀원 원본 → v3 수정 비교)

**팀원 원본 (Lambda 프로젝트):**
```yaml
# deploy/k8s/base/deployment.yaml
containers:
  - name: ecg-svc
    image: ecg-svc:latest
    ports: [8000]
    env:
      - MODEL_PATH: /mnt/efs/models/ecg_resnet.onnx
    resources:
      requests: {memory: 512Mi, cpu: 500m}
      limits:   {memory: 1Gi,  cpu: 1000m}
    volumeMounts:
      - name: efs-models
        mountPath: /mnt/efs/models
volumes:
  - name: efs-models
    persistentVolumeClaim: efs-models-pvc
```

**v3 통합 시 적용할 설정 (수정사항 #1 반영):**
```yaml
containers:
  - name: ecg-svc
    env:
      - name: MODEL_PATH
        value: /models/ecg_resnet.onnx      # /mnt/efs → /models 통일
    volumeMounts:
      - name: models
        mountPath: /models
        subPath: ecg-svc                     # ecg-svc 모델만 마운트
        readOnly: true
```

**모델 파일 로컬 배치:**
```
v3/models/ecg-svc/
└── ecg_resnet.onnx       ← S3 say2-6team에서 다운로드
```

---

## Part 2: 현재 v3 ecg-svc 기능 분석

### 2.1 프로젝트 구조

```
v3/services/ecg-svc/
├── main.py                  # FastAPI, /predict, /healthz, /readyz
├── config.py                # pydantic-settings (Bedrock, RAG 설정)
├── analyzer.py              # 규칙 기반 8모듈 ECG 분석
├── Dockerfile               # python:3.11-slim, 포트 8000
├── requirements.txt         # fastapi, boto3, httpx (가벼움)
├── README.md
└── report/
    ├── __init__.py
    └── ecg_report_generator.py  # Bedrock LLM 한국어 소견서
```

### 2.2 현재 분석 방식: 규칙 기반 8개 모듈

| 모듈 | 분석 항목 | 입력 데이터 |
|------|----------|------------|
| 1. Heart Rate | 서맥/정상/빈맥 | `heart_rate` (정수) |
| 2. Rhythm | AF, SVT, VT | `rhythm_regular`, `p_wave_present`, `rr_intervals` |
| 3. PR Interval | 1도 AV Block, WPW | `pr_interval` (ms) |
| 4. QRS/BBB | RBBB, LBBB | `qrs_duration`, `leads` 진폭 |
| 5. Hypertrophy | LVH, RVH | `leads` R/S 진폭 |
| 6. ST Segment | ST 상승/하강, 관상동맥 영역 | `leads` st_dev |
| 7. QT/QTc | QT 연장/단축 | `qt_interval`, `heart_rate` |
| 8. Axis | 정상/좌축/우축 편위 | `leads` I, aVF |

**입력 데이터 형식:** (Pre-processed JSON — 이미 추출된 파라미터)

```python
{
    "heart_rate": 78,
    "rhythm_regular": True,
    "p_wave_present": True,
    "pr_interval": 160,       # ms
    "qrs_duration": 90,       # ms
    "qt_interval": 400,       # ms
    "rr_intervals": [780, 790, 785],  # ms (optional)
    "leads": {
        "I":   {"r_amp": 0.8, "s_amp": -0.2, "st_dev": 0.0},
        "II":  {"r_amp": 1.2, "s_amp": -0.3, "st_dev": 0.0},
        // ... 12 leads
    }
}
```

### 2.3 Bedrock 소견서 생성 (유지할 기능)

```
환자 정보 + ECG Findings → Bedrock Claude Prompt → 한국어 구조화 소견서
                                                     ├── 1. Rate & Rhythm
                                                     ├── 2. Axis
                                                     ├── 3. Intervals
                                                     ├── 4. ST-T Changes
                                                     ├── 5. Chamber Hypertrophy
                                                     ├── 6. Conduction Abnormalities
                                                     ├── 7. Impression
                                                     └── 8. Clinical Correlation
```

- Bedrock 실패 시 **템플릿 폴백** 동작
- 이전 모달 컨텍스트(chest, blood 결과) 반영 가능

### 2.4 서비스 간 통신

```
central-orchestrator
    ↓ POST http://ecg-svc:8000/predict
    ↓ PredictRequest { patient_id, patient_info, data, context }
ecg-svc
    ↓ analyzer.analyze_ecg(data)
    ↓ generate_ecg_report(findings, bedrock)
    ↓ PredictResponse { findings, summary, report, risk_level }
central-orchestrator
    ↓ 결과 누적 → 다음 모달 결정 (Bedrock LLM)
```

---

## Part 3: GAP 분석 — Lambda vs v3

### 3.1 기능 비교 매트릭스

| 기능 | Lambda ECG | v3 ecg-svc | GAP |
|------|:----------:|:----------:|:---:|
| **ONNX ML 추론** (13 병리) | ✅ | ❌ 규칙 기반 | 🔴 핵심 GAP |
| **Raw Signal 입력** (.npy) | ✅ | ❌ JSON 파라미터 | 🔴 핵심 GAP |
| **S3 신호 로딩** | ✅ | ❌ | 🔴 핵심 GAP |
| **신호 처리** (HR/QTc) | ✅ scipy | ❌ 입력값 의존 | 🟡 중요 |
| **응급 라벨 바이패스** | ✅ | ❌ | 🟡 중요 |
| **질환별 임계값 튜닝** | ✅ 13개 | ❌ | 🟡 중요 |
| **Pertinent Negatives** | ✅ | ✅ (v3에도 있음) | ✅ 호환 |
| **Risk Classification** | ✅ 3단계 | ✅ 3단계 | ✅ 호환 |
| **Bedrock 한국어 소견서** | ❌ 템플릿만 | ✅ | v3 우수 (유지) |
| **K8s Health Probes** | ✅ (팀원 작성) | ✅ | ✅ 호환 |
| **활력징후 스키마** | ✅ 4개 필드 | ❌ | 🟡 스키마 확장 |
| **MIMIC /simulate** | ✅ | ❌ | ❌ 제거 (설계 위반) |
| **테스트 대시보드** | ✅ | ❌ | ⚪ 선택 (tests/에 배치) |
| **규칙 기반 분석** (8모듈) | ❌ | ✅ | 병합 검토 |

### 3.2 핵심 GAP 상세

#### GAP-1: ONNX ML 추론 엔진 부재 (Critical)

```
현재: data(JSON 파라미터) → rule-based analyzer → findings
목표: data(signal_path) → S3 load → normalize → ONNX inference → threshold → findings
```

**필요 파일:** `inference.py` (Lambda의 핵심 로직)
**필요 의존성:** `onnxruntime>=1.18.0`, `numpy>=1.26.4`

#### GAP-2: Raw Signal 처리 부재 (Critical)

```
현재: 이미 추출된 HR, intervals, amplitudes 수신
목표: Raw 12-lead signal (12×5000) 직접 수신 → 자동 처리
```

**필요 파일:** `signal_processing.py`, `model_loader.py`
**필요 의존성:** `scipy>=1.13.0`

#### GAP-3: 스키마 확장 (Important)

```
현재 PatientInfo:
    age, sex, chief_complaint, history

목표 PatientInfo:
    age, sex, chief_complaint, history,
    + temperature (Optional[float])
    + blood_pressure (Optional[str])
    + spo2 (Optional[float])
    + respiratory_rate (Optional[int])
```

**영향 범위:** 전 서비스 (shared/schemas.py) — 하위 호환 (모두 Optional)

---

## Part 4: 통합 계획

### 4.1 통합 전략

```
┌─────────────────────────────────────────────────────────────────┐
│                    통합 전략: Hybrid Approach                      │
│                                                                   │
│  Lambda의 ML 추론 로직 이식 + v3의 K8s/Bedrock 인프라 유지          │
│                                                                   │
│  [Lambda에서 가져올 것]          [v3에서 유지할 것]                  │
│  ├─ inference.py (ONNX 추론)    ├─ K8s manifest                   │
│  ├─ signal_processing.py        ├─ Bedrock 소견서 생성             │
│  └─ 임계값/응급 필터 로직        ├─ config.py (pydantic-settings)  │
│                                  ├─ health probes (/healthz, /readyz)│
│  [Lambda에서 제거할 것]          └─ central-orchestrator 인터페이스 │
│  ├─ model_loader.py S3 폴백                                       │
│  ├─ /simulate 엔드포인트                                           │
│  ├─ Mangum (Lambda 어댑터)                                        │
│  └─ pandas 의존성                                                  │
│                                                                   │
│  [변경할 것]                     [새로 만들 것]                     │
│  ├─ main.py (predict 로직)      ├─ thresholds.py (임계값 SSOT)    │
│  ├─ shared/schemas.py (활력징후) └─ model_loader.py (단순화 재작성) │
│  ├─ requirements.txt                                               │
│  ├─ Dockerfile (모델 마운트)                                       │
│  └─ K8s manifest (리소스/볼륨)                                     │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 통합 후 ecg-svc 구조 (목표)

```
v3/services/ecg-svc/
├── main.py                      # [수정] predict 라우트 → ML 추론 파이프라인 + 조건부 테스트 UI
├── config.py                    # [수정] MODEL_PATH 추가 (/models/ 경로)
├── inference.py                 # [신규] Lambda에서 이식 — ONNX 13-class 추론 (임계값 분리)
├── thresholds.py                # [신규] 임계값 SSOT — inference.py에서 분리 (수정#4)
├── signal_processing.py         # [신규] Lambda에서 이식 — HR/QTc 계산 (변경 없음)
├── model_loader.py              # [신규] 단순화 재작성 — S3 폴백 제거, 로컬만 (수정#2)
├── analyzer.py                  # [유지] 규칙 기반 분석 (signal_path 없을 때 폴백)
├── Dockerfile                   # [수정] scipy, onnxruntime 추가, 모델 볼륨
├── requirements.txt             # [수정] 의존성 추가 (mangum/pandas 제외)
├── README.md                    # [수정] 문서 갱신
└── report/
    ├── __init__.py              # [유지]
    └── ecg_report_generator.py  # [유지] Bedrock LLM 한국어 소견서

v3/models/ecg-svc/               # [신규] 모델 파일 디렉토리 (수정#1)
└── ecg_resnet.onnx

tests/v3/ecg-svc/                # [신규] 테스트 UI 분리 (수정#5)
└── static/
    └── index.html
```

### 4.3 파일별 통합 작업 상세

#### 4.3.1 thresholds.py (신규 — 임계값 SSOT, 수정#4)

**chest-svc에서 thresholds.py 통합 작업 경험을 반영하여 처음부터 분리.**

```python
# thresholds.py (SSOT — Single Source of Truth)
LABEL_NAMES = ["stemi", "vfib_vtach", "avblock_3rd", "pe", "nstemi",
               "afib", "svt", "heart_failure", "sepsis", "hyperkalemia",
               "hypokalemia", "lbbb", "arrhythmia"]

LABEL_THRESHOLDS = {"stemi": 0.250, "vfib_vtach": 0.170, "avblock_3rd": 0.470,
                    "pe": 0.505, "nstemi": 0.340, "afib": 0.345, "svt": 0.345,
                    "heart_failure": 0.835, "sepsis": 0.530, "hyperkalemia": 0.471,
                    "hypokalemia": 0.815, "lbbb": 0.350, "arrhythmia": 0.720}

EMERGENCY_LABELS = {"stemi", "vfib_vtach", "avblock_3rd", "hyperkalemia"}
DETECTION_MARGIN = 0.10

RISK_MAP = {"stemi": "critical", "vfib_vtach": "critical", "avblock_3rd": "critical",
            "nstemi": "urgent", "pe": "urgent", "svt": "urgent", "hyperkalemia": "urgent",
            ...}  # 나머지 "routine"

LABEL_KO = {"stemi": "ST분절 상승 심근경색", "vfib_vtach": "심실세동/빈맥", ...}

ECG_CONFIRMED = {"stemi": True, "afib": True, "lbbb": True, "arrhythmia": True,
                 "svt": True, "vfib_vtach": True, "avblock_3rd": True,
                 "pe": False, "nstemi": False, "heart_failure": False,
                 "sepsis": False, "hyperkalemia": False, "hypokalemia": False}
```

**이점:** 나중에 Youden 최적화 시 thresholds.py만 수정하면 됨

#### 4.3.2 inference.py (Lambda → v3 이식)

**소스:** `say-6-project-feature-MIMIC-ECG/app/inference.py`

**이식할 핵심 함수:**
- `run_inference()`: 핵심 추론 함수
- `_classify_risk()`: 위험도 분류
- `_build_pertinent_negatives()`: 주소증 기반 음성 소견
- `_suggest_next_actions()`: 후속 검사 추천

**상수는 thresholds.py에서 import:**
```python
from thresholds import (
    LABEL_NAMES, LABEL_THRESHOLDS, EMERGENCY_LABELS,
    DETECTION_MARGIN, RISK_MAP, LABEL_KO, ECG_CONFIRMED
)
```

**K8s 적응 변경:**
- S3 신호 로딩 유지 (signal_path가 s3:// 경로일 수 있음)
- Mangum import 제거
- shared/schemas.py import 경로 조정 (`sys.path.insert(0, "/app/shared")`)

#### 4.3.3 signal_processing.py (Lambda → v3 이식)

**소스:** `say-6-project-feature-MIMIC-ECG/app/signal_processing.py`

**이식할 핵심 로직:**
- `compute_hr()`: Lead II R-peak 기반 심박수 계산
- `compute_qtc()`: Bazett 공식 QTc 보정

**변경 불필요** — 독립적 유틸 함수, 그대로 복사 가능

#### 4.3.4 model_loader.py (단순화 재작성 — 수정#2)

**Lambda 원본은 사용하지 않고, K8s 전용으로 단순화 재작성.**

chest-svc도 로컬 파일 로드만 하므로 동일 패턴 적용.
S3 폴백은 불필요한 복잡성 + S3 권한 설정 추가 부담.

```python
import onnxruntime as ort
import os

_session = None

def load_model(model_path: str) -> ort.InferenceSession:
    global _session
    if _session is not None:
        return _session

    if not os.path.exists(model_path):
        raise FileNotFoundError(
            f"Model not found: {model_path}. "
            "모델 볼륨이 마운트되었는지 확인하세요."
        )

    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    _session = ort.InferenceSession(model_path, providers=providers)
    return _session
```

#### 4.3.5 main.py (수정 — /simulate 제거, 테스트 UI 조건부 서빙)

**현재 흐름:**
```python
@app.post("/predict")
async def predict(req: PredictRequest):
    ecg_data = req.data
    findings = analyze_ecg(ecg_data)           # 규칙 기반
    report = generate_ecg_report(findings...)   # Bedrock
    return PredictResponse(...)
```

**통합 후 흐름:**
```python
from contextlib import asynccontextmanager
from model_loader import load_model
from config import settings

# ── lifespan: 서버 시작 시 ONNX 모델 프리로드 (chest-svc 동일 패턴) ──
@asynccontextmanager
async def lifespan(app: FastAPI):
    load_model(settings.model_path)          # 시작 시 모델 로딩 (수 초)
    app.state.model_ready = True
    logger.info("ONNX model loaded: %s", settings.model_path)
    yield
    app.state.model_ready = False

app = FastAPI(lifespan=lifespan)

# ── readyz: 모델 로딩 완료 후에만 200 리턴 ──
@app.get("/readyz")
def readyz():
    if not getattr(app.state, "model_ready", False):
        return JSONResponse({"status": "loading"}, status_code=503)
    return {"status": "ready"}

@app.post("/predict")
async def predict(req: PredictRequest):
    ecg_data = req.data

    # ── 신규: ML 추론 파이프라인 ──
    if "signal_path" in ecg_data:
        signal = load_signal(ecg_data["signal_path"])   # S3/.npy 로드
        ml_findings, metadata = run_inference(signal)    # ONNX 13-class
        hr = compute_hr(signal)                          # 신호 처리
        qtc = compute_qtc(hr)
        metadata.update({"hr": hr, "qtc": qtc})
        findings = ml_findings
    else:
        # ── 폴백: 기존 규칙 기반 (하위 호환) ──
        findings = analyze_ecg(ecg_data)
        metadata = {}

    report = generate_ecg_report(findings...)   # Bedrock (유지)
    return PredictResponse(findings=findings, metadata=metadata, ...)
```

**핵심 포인트:**
- `lifespan`에서 ONNX 모델 프리로드 → 첫 요청 지연 방지
- `/readyz`가 모델 로딩 완료 후에만 200 → K8s가 준비 안 된 Pod에 트래픽 안 보냄
- `signal_path` 유무로 ML/규칙 분기 → 기존 API 100% 하위 호환

**추가: 테스트 UI 조건부 서빙 (수정#5 — chest-svc 동일 패턴):**
```python
_static_dir = os.path.join(os.path.dirname(__file__), "static")

@app.get("/", response_class=HTMLResponse)
def test_ui():
    html_path = os.path.join(_static_dir, "index.html")
    if os.path.exists(html_path):
        with open(html_path) as f:
            return f.read()
    return "<h1>ecg-svc</h1><p>API running.</p>"

if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")
```

**제거 대상 (수정#3, #7):**
- `@app.post("/simulate")` 라우트 전체
- `from mangum import Mangum` / `handler = Mangum(app)` (Lambda 핸들러)
- MIMIC-IV CSV 파싱 관련 코드

#### 4.3.6 config.py (수정 — 수정#1 반영)

**추가할 설정:**

```python
class Settings(BaseSettings):
    # 기존 유지
    bedrock_region: str
    bedrock_model_id: str
    rag_url: str
    log_level: str = "INFO"

    # ── 신규: ML 모델 설정 (수정#1: /models 경로 통일) ──
    model_path: str = "/models/ecg_resnet.onnx"
    signal_bucket: str = "say2-6team"         # ECG 신호 S3 버킷
```

> S3 관련 설정 `model_bucket`, `model_key` 제거 (수정#2: S3 폴백 제거)

#### 4.3.7 shared/schemas.py (수정)

**변경:** Downloads의 schemas.py 적용 (PatientInfo 활력징후 4개 필드 추가)

```python
class PatientInfo(BaseModel):
    age: int
    sex: str
    chief_complaint: str
    history: list[str] = []
    # ── 신규: 활력징후 (전부 Optional — 하위 호환) ──
    temperature: Optional[float] = None
    blood_pressure: Optional[str] = None
    spo2: Optional[float] = None
    respiratory_rate: Optional[int] = None
```

**영향:** 전 서비스 — 모두 Optional이므로 기존 코드 정상 동작

#### 4.3.8 requirements.txt (수정 — mangum/pandas 제외)

```
# 기존 유지
fastapi==0.115.0
uvicorn==0.30.0
pydantic==2.9.0
pydantic-settings==2.5.0
httpx==0.27.0
boto3==1.35.0

# ── 신규 추가 ──
numpy==1.26.4          # 신호 데이터 처리
scipy==1.13.0          # R-peak 검출 (signal_processing)
onnxruntime==1.18.0    # ONNX ML 추론

# ── 제거 대상 (이식하지 않음) ──
# mangum==0.17.0       ← Lambda 어댑터 (수정#7)
# pandas==2.2.2        ← /simulate 전용 (수정#3)
```

#### 4.3.9 Dockerfile (수정)

**현재:** ~150MB 이미지 (가벼움)
**통합 후 예상:** ~800MB (onnxruntime + scipy + numpy)

**변경 포인트:**
- 모델 볼륨 마운트는 Dockerfile 외부 (K8s에서 관리)
- scipy 빌드 의존성 (gcc 등 — slim 이미지에서 필요할 수 있음)
- 멀티스테이지 빌드 검토 (이미지 크기 최적화)

#### 4.3.10 K8s Manifest — ecg-svc.yaml (수정 — 수정#1 반영)

```yaml
# 변경 포인트 (수정#1: /models 경로 통일, subPath 사용)
resources:
  requests: { cpu: 500m,  memory: 512Mi }   # 현재: 250m/512Mi
  limits:   { cpu: 1000m, memory: 1Gi }     # 현재: 500m/1Gi

volumeMounts:
  - name: models                             # 신규: 모델 볼륨
    mountPath: /models
    subPath: ecg-svc                         # ecg-svc 모델만 마운트
    readOnly: true

env:
  - name: MODEL_PATH                         # 신규
    value: /models/ecg_resnet.onnx
```

### 4.4 통합 순서 (수정사항 전량 반영)

| Phase | 작업 | 시간 | 수정사항 |
|-------|------|------|----------|
| 1 | shared/schemas.py 활력징후 추가 | 5분 | (원본 유지) |
| 2 | thresholds.py 생성 (임계값 SSOT) | 10분 | **수정#4** |
| 3 | inference.py 이식 + thresholds import | 25분 | 수정#4 반영 |
| 4 | signal_processing.py 이식 | 5분 | (변경 없음, 그대로 복사) |
| 5 | model_loader.py 단순화 재작성 | 10분 | **수정#2** S3 폴백 제거 |
| 6 | main.py 통합 | 20분 | **수정#3** /simulate 제거, **수정#5** 조건부 static, **수정#7** Mangum 제거 |
| 7 | config.py + requirements + Dockerfile | 15분 | **수정#1** /models 경로, pandas/mangum 제외 |
| 8 | 모델 파일 배치 | 10분 | **수정#1** `v3/models/ecg-svc/ecg_resnet.onnx` |
| 9 | K8s manifest 수정 | 10분 | **수정#1** subPath + 리소스 상향 |
| 10 | Mangum 잔여 코드 확인 | 5분 | **수정#7** |
| 11 | 테스트 UI 배치 | 5분 | **수정#5** `tests/v3/ecg-svc/static/` |
| 12 | 로컬 K8s 검증 | 20분 | docker build → /predict 테스트 |
| (후속) | ECG RAG 인덱스 생성 | 별도 | **수정#6** 통합 후 추가 |

### 4.5 리스크 및 대응

| 리스크 | 영향 | 대응 |
|--------|------|------|
| ONNX 모델 파일 확보 | 🔴 모델 없으면 ML 불가 | S3 `say2-6team/models/ecg_resnet.onnx` 다운로드 |
| 테스트 신호 파일 부재 | 🟡 검증 불가 | Lambda의 test-samples/ S3에서 .npy 복사 |
| Docker 이미지 사이즈 증가 | 🟡 빌드 시간 | 멀티스테이지 빌드 + .dockerignore 최적화 |
| scipy 빌드 실패 (slim 이미지) | 🟡 빌드 에러 | `python:3.11` (non-slim) 또는 빌드 의존성 추가 |
| ONNX CPU 추론 속도 | ⚪ 느릴 수 있음 | 로컬 테스트 후 확인, 필요 시 워커 수 조정 |
| hyperkalemia FP 55% | ⚪ 오탐 | 알려진 한계 — 모델 재훈련 시 개선 |
| ECG RAG 인덱스 부재 | ⚪ 유사사례 참고 불가 | Bedrock 소견서에 RAG 부분만 빈 결과, 기능 자체는 정상 (**수정#6**) |

### 4.6 analyzer.py 처리 방안

**옵션 A: 유지 (보조용)** ← 권장
- ML 추론 불가 시 폴백으로 사용
- Pre-processed JSON 입력도 여전히 처리 가능
- 두 방식 공존 → 유연성 확보

**옵션 B: 제거**
- 코드 간소화
- ML 전용으로 전환
- 하위 호환 포기

---

## Part 5: 영향 분석

### 5.1 변경 리소스

| 리소스 | 유형 | 변경 |
|--------|------|------|
| `v3/shared/schemas.py` | Schema | PatientInfo 필드 4개 추가 |
| `v3/services/ecg-svc/main.py` | API | ML 분기 + /simulate 제거 + 조건부 static |
| `v3/services/ecg-svc/config.py` | Config | model_path=/models/ecg_resnet.onnx |
| `v3/services/ecg-svc/requirements.txt` | Deps | +numpy,scipy,onnxruntime / -mangum,pandas |
| `v3/services/ecg-svc/Dockerfile` | Build | 의존성 추가 |
| `v3/k8s/base/ecg-svc.yaml` | K8s | 리소스 상향 + /models subPath 마운트 |
| `v3/services/ecg-svc/thresholds.py` | **신규** | 임계값 SSOT (수정#4) |
| `v3/services/ecg-svc/inference.py` | **신규** | ONNX 추론 엔진 |
| `v3/services/ecg-svc/signal_processing.py` | **신규** | 신호 처리 |
| `v3/services/ecg-svc/model_loader.py` | **신규** | 모델 로딩 (단순화) |
| `v3/models/ecg-svc/ecg_resnet.onnx` | **신규** | ONNX 모델 파일 |
| `tests/v3/ecg-svc/static/index.html` | **신규** | 테스트 대시보드 UI |

### 5.2 소비자 영향

| 소비자 | 호출 방식 | 영향 |
|--------|----------|------|
| central-orchestrator | POST /predict | ✅ 하위 호환 (signal_path 없으면 기존 동작) |
| report-svc | findings 수신 | ✅ Finding 스키마 동일 |
| chest-svc | patient_info 공유 | ✅ Optional 필드만 추가 |
| blood-svc | patient_info 공유 | ✅ Optional 필드만 추가 |
| rag-svc | 직접 관계 없음 | ✅ 영향 없음 |
| PostgreSQL | modal_results JSON | ✅ JSON 필드 자동 확장 |

---

## 부록 A: 소스 파일 경로 매핑

| Lambda 소스 | 처리 | v3 타겟 |
|------------|------|---------|
| `app/inference.py` | 이식 + 상수 분리 | `v3/services/ecg-svc/inference.py` + `thresholds.py` |
| `app/signal_processing.py` | 그대로 복사 | `v3/services/ecg-svc/signal_processing.py` |
| `app/model_loader.py` | **단순화 재작성** | `v3/services/ecg-svc/model_loader.py` |
| `app/schemas.py` (PatientInfo) | 머지 | `v3/shared/schemas.py` |
| `app/main.py` (predict 로직) | 머지 (/simulate 제거) | `v3/services/ecg-svc/main.py` |
| `app/main.py` (Mangum) | **제거** | — |
| `app/static/index.html` | 이동 | `tests/v3/ecg-svc/static/index.html` |
| `deploy/k8s/` | 참조만 | `v3/k8s/base/ecg-svc.yaml` (리소스 값 참고) |
| `scripts/upload_signals_to_s3.py` | 참조만 | 신호 데이터 준비 스크립트 |

## 부록 B: 수정사항 추적표

| # | 수정 항목 | 원본 계획 | 수정 후 | 반영 섹션 |
|---|----------|----------|---------|----------|
| 1 | 모델 경로 | /mnt/efs/models, /app/models | `/models` (subPath: ecg-svc) | 1.8, 4.3.6, 4.3.10 |
| 2 | model_loader.py | S3 폴백 4단계 | 로컬 파일만, S3 제거 | 1.4, 4.3.4 |
| 3 | /simulate | 포함 가능 | **제거** (설계 위반, pandas 제거) | 1.6, 3.1, 4.3.5 |
| 4 | 임계값 | inference.py 하드코딩 | `thresholds.py` SSOT 분리 | 4.2, 4.3.1, 5.1 |
| 5 | 테스트 UI | services/ecg-svc/static/ | `tests/v3/ecg-svc/static/` | 4.2, 4.3.5, 5.1 |
| 6 | RAG 인덱스 | 언급 없음 | 필요 (후속 작업) | 4.4, 4.5 |
| 7 | Mangum | 언급만 | 제거 대상 명시 | 1.7, 4.3.5, 4.3.8 |
