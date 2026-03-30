# ECG ML Integration Design Document

> **Summary**: Lambda ECG ONNX ResNet 13-class ML 추론을 v3 K8s ecg-svc에 통합 — Option C Pragmatic
>
> **Project**: DR-AI v3
> **Version**: v3
> **Author**: 프로젝트 6팀
> **Date**: 2026-03-30
> **Status**: Draft
> **Planning Doc**: [ecg-ml-integration.plan.md](../../01-plan/features/ecg-ml-integration.plan.md)

---

## Context Anchor

| Key | Value |
|-----|-------|
| **WHY** | 규칙 기반 ECG 분석은 raw signal 처리 불가, 팀원의 ML 모델은 Lambda에 갇혀 v3와 통합 안 됨 |
| **WHO** | 의료진 (ECG 판독 자동화), 개발팀 (v3 통합 파이프라인 완성) |
| **RISK** | ONNX 모델 파일 확보(S3 접근), Docker 이미지 사이즈 증가(~800MB), hyperkalemia FP 55% |
| **SUCCESS** | /predict에 signal_path 전달 시 ONNX 13-class 추론 성공, 기존 JSON 입력 하위 호환 유지, K8s Pod 정상 Running |
| **SCOPE** | Phase 1~12 (스키마→로직이식→인프라→검증), RAG 인덱스는 후속 작업 |

---

## 1. Overview

### 1.1 Design Goals

- ONNX ResNet 13-class ML 추론을 ecg-svc /predict에 통합
- chest-svc와 동일한 패턴 (lifespan 프리로드, thresholds.py SSOT, PV 마운트)
- 기존 규칙 기반 분석을 폴백으로 유지 (signal_path 유무로 분기)
- central-orchestrator 수정 없이 하위 호환

### 1.2 Design Principles

- **chest-svc 패턴 일관성**: 동일 프로젝트 내 ONNX 서비스 패턴 통일
- **단순성**: S3 폴백 제거, K8s 볼륨 마운트만 사용
- **SSOT**: 임계값은 thresholds.py 단일 소스
- **하위 호환**: 기존 JSON 입력 → 규칙 기반 폴백

---

## 2. Architecture — Option C: Pragmatic Balance

### 2.0 Architecture Comparison

| Criteria | Option A: Minimal | Option B: Clean | **Option C: Pragmatic** |
|----------|:-:|:-:|:-:|
| **신규 파일** | 2 | 6 | **4** |
| **수정 파일** | 3 | 4 | **4** |
| **복잡도** | Low | High | **Medium** |
| **유지보수** | Low | High | **High** |
| **구현 시간** | ~90분 | ~180분 | **~140분** |
| **chest-svc 패턴** | ❌ | ⚪ 과도 | **✅ 동일** |

**Selected**: Option C — **Rationale**: Plan/분석서에서 합의된 구조, chest-svc와 패턴 일관성 유지, 적정 수준의 분리

### 2.1 Component Diagram

```
central-orchestrator
    │ POST /predict (PredictRequest)
    ▼
┌─────────────────────────────────────────────────────────┐
│  ecg-svc (K8s Pod)                                      │
│                                                          │
│  [lifespan]                                              │
│    └─ model_loader.load_model(settings.model_path)       │
│       └─ ONNX 세션 캐싱 → _ready = True → readyz 200    │
│                                                          │
│  [POST /predict]                                         │
│    ├─ signal_path 있음?                                  │
│    │   ├─ YES ──────────────────────────────────────┐    │
│    │   │  load_signal(.npy from S3 or local)        │    │
│    │   │  normalize (per-lead z-score)              │    │
│    │   │  ONNX inference → 13 probabilities         │    │
│    │   │  thresholds.py 판정                        │    │
│    │   │  emergency bypass (STEMI,VFib,AVBlock,HK)  │    │
│    │   │  signal_processing: HR/QTc                 │    │
│    │   │  → findings + metadata                     │    │
│    │   └────────────────────────────────────────────┘    │
│    │   └─ NO ──→ analyzer.analyze_ecg(JSON) → findings   │
│    │                                                     │
│    ├─ Bedrock 한국어 소견서 생성 (유지)                   │
│    └─ PredictResponse                                    │
└─────────────────────────────────────────────────────────┘
    │
    ▼
/models/ecg_resnet.onnx (PV 마운트, readOnly)
```

### 2.2 Data Flow

```
[ML Path]
signal_path(.npy) → S3/local load → numpy(12,5000)
    → per-lead z-score normalize
    → ONNX model.run() → logits(13)
    → sigmoid → probabilities(13)
    → thresholds.py 판정 + emergency bypass
    → Finding[] + risk_level

[Rule Path (폴백)]
JSON{heart_rate, leads, ...} → analyzer.analyze_ecg()
    → 8모듈 규칙 분석 → Finding[]

[공통]
Finding[] → Bedrock generate_ecg_report() → report(str)
    → PredictResponse
```

### 2.3 Dependencies

| Component | Depends On | Purpose |
|-----------|-----------|---------|
| inference.py | thresholds.py, model_loader.py | 추론 엔진 |
| inference.py | signal_processing.py | HR/QTc 계산 |
| main.py | inference.py, analyzer.py | ML/규칙 분기 |
| main.py | model_loader.py | lifespan 프리로드 |
| main.py | report/ecg_report_generator.py | Bedrock 소견서 |
| model_loader.py | onnxruntime | ONNX 세션 |

---

## 3. Data Model

### 3.1 PatientInfo 확장 (shared/schemas.py)

```python
class PatientInfo(BaseModel):
    age: int
    sex: str                          # "M" | "F"
    chief_complaint: str
    history: list[str] = []
    # ── 신규: 활력징후 (전부 Optional — 하위 호환) ──
    temperature: Optional[float] = None       # ℃
    blood_pressure: Optional[str] = None      # "150/90"
    spo2: Optional[float] = None              # %
    respiratory_rate: Optional[int] = None    # /min
```

### 3.2 ECG data 입력 포맷

```python
# ML Path (signal_path 포함)
data = {
    "signal_path": "s3://say2-6team/mimic/ecg/signals/40001152.npy",
    "leads": 12
}

# Rule Path (기존 호환)
data = {
    "heart_rate": 78,
    "rhythm_regular": True,
    "p_wave_present": True,
    "pr_interval": 160,
    "qrs_duration": 90,
    "qt_interval": 400,
    "leads": { "I": {"r_amp": 0.8, "s_amp": -0.2, "st_dev": 0.0}, ... }
}
```

### 3.3 ML 추론 출력 → Finding 매핑

```python
# ONNX output: 13 probabilities
# → thresholds.py 판정 → Finding[]

Finding(
    name="ST분절 상승 심근경색 (STEMI)",   # LABEL_KO[label]
    detected=True,                         # prob >= threshold (+ margin 조건)
    confidence=0.87,                       # sigmoid 확률값
    detail="임계값 0.25 기준 감지됨",
    severity="critical",                   # RISK_MAP[label]
    recommendation="즉각적인 심장 카테터실 활성화 권고",
)
```

---

## 4. API Specification

### 4.1 Endpoint List

| Method | Path | Description | Auth | 변경 |
|--------|------|-------------|------|------|
| GET | /healthz | Liveness probe | None | 변경 없음 |
| GET | /readyz | Readiness probe | None | **모델 상태 포함 응답** |
| POST | /predict | ECG 분석 | None | **ML 분기 추가** |
| GET | / | 테스트 UI | None | **신규 (조건부)** |

### 4.2 POST /predict — ML 분기 상세

**Request (ML Path):**
```json
{
    "patient_id": "test-001",
    "patient_info": {
        "age": 65, "sex": "M", "chief_complaint": "흉통",
        "temperature": 37.5, "blood_pressure": "130/85",
        "spo2": 98.0, "respiratory_rate": 16
    },
    "data": {
        "signal_path": "s3://say2-6team/test-samples/stemi.npy",
        "leads": 12
    },
    "context": {}
}
```

**Response (ML Path):**
```json
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
        }
    ],
    "summary": "12-lead ECG ML 분석: 1개 소견 감지 — STEMI (87%)",
    "report": "...(Bedrock 한국어 소견서)...",
    "risk_level": "critical",
    "pertinent_negatives": ["NSTEMI 음성", "심방세동 음성"],
    "suggested_next_actions": [
        {"action": "혈액검사", "reason": "Troponin 확인", "urgency": "urgent"}
    ],
    "metadata": {
        "service": "ecg-svc",
        "version": "3.0.0",
        "inference_time_ms": 120,
        "analysis_type": "ml-model",
        "hr": 78,
        "qtc": 412,
        "leads": 12,
        "sampling_rate": 500,
        "duration_sec": 10
    }
}
```

### 4.3 GET /readyz — 모델 로드 연동

```
서버 시작 → lifespan에서 ONNX 로드 중 → readyz 503 {"status": "loading"}
ONNX 로드 완료 → _ready = True → readyz 200 {"status": "ready", "ml_model": "loaded"}
ONNX 파일 없음 → warning + _ready = True → readyz 200 {"status": "ready", "ml_model": "unavailable"}
  → 규칙 기반으로 폴백 동작, 운영 시 ml_model 필드로 ML 미활성 즉시 파악 가능
```

---

## 5. File Structure (통합 후)

```
v3/services/ecg-svc/
├── main.py                      # [수정] lifespan 프리로드 + ML/규칙 분기 + 조건부 static
├── config.py                    # [수정] model_path, signal_bucket 추가
├── thresholds.py                # [신규] 임계값 SSOT (13 질환)
├── inference.py                 # [신규] ONNX 13-class 추론 엔진
├── signal_processing.py         # [신규] HR/QTc 계산 (scipy)
├── model_loader.py              # [신규] 단순 ONNX 로더 (로컬만)
├── analyzer.py                  # [유지] 규칙 기반 8모듈 (폴백)
├── Dockerfile                   # [수정] scipy, onnxruntime, numpy 추가
├── requirements.txt             # [수정] 의존성 추가
├── README.md                    # [수정]
└── report/
    ├── __init__.py              # [유지]
    └── ecg_report_generator.py  # [유지] Bedrock LLM 한국어 소견서

v3/models/ecg-svc/
└── ecg_resnet.onnx              # [확보 완료] 33MB ONNX ResNet

v3/shared/
└── schemas.py                   # [수정] PatientInfo 활력징후 4필드

v3/k8s/base/
└── ecg-svc.yaml                 # [수정] 리소스 상향 + /models 마운트

tests/v3/ecg-svc/
├── testdata/                    # [확보 완료]
│   ├── stemi.npy
│   ├── afib.npy
│   ├── normal.npy
│   └── hf.npy
└── static/
    └── index.html               # [후속] 테스트 대시보드 UI
```

---

## 6. Module Design

### 6.1 thresholds.py (신규)

```python
"""ECG 임계값 SSOT — 임계값 수정 시 이 파일만 변경."""

LABEL_NAMES: list[str] = [
    "stemi", "vfib_vtach", "avblock_3rd", "pe", "nstemi",
    "afib", "svt", "heart_failure", "sepsis", "hyperkalemia",
    "hypokalemia", "lbbb", "arrhythmia",
]

LABEL_THRESHOLDS: dict[str, float] = {
    "stemi": 0.250, "vfib_vtach": 0.170, "avblock_3rd": 0.470,
    "pe": 0.505, "nstemi": 0.340, "afib": 0.345, "svt": 0.345,
    "heart_failure": 0.835, "sepsis": 0.530, "hyperkalemia": 0.471,
    "hypokalemia": 0.815, "lbbb": 0.350, "arrhythmia": 0.720,
}

EMERGENCY_LABELS: set[str] = {"stemi", "vfib_vtach", "avblock_3rd", "hyperkalemia"}
DETECTION_MARGIN: float = 0.10

RISK_MAP: dict[str, str] = {
    "stemi": "critical", "vfib_vtach": "critical", "avblock_3rd": "critical",
    "nstemi": "urgent", "pe": "urgent", "svt": "urgent",
    "hyperkalemia": "urgent", "afib": "urgent",
    "heart_failure": "routine", "sepsis": "routine",
    "hypokalemia": "routine", "lbbb": "routine", "arrhythmia": "routine",
}

LABEL_KO: dict[str, str] = {
    "stemi": "ST분절 상승 심근경색", "vfib_vtach": "심실세동/심실빈맥",
    "avblock_3rd": "3도 방실차단", "pe": "폐색전증",
    "nstemi": "비ST상승 심근경색", "afib": "심방세동",
    "svt": "상심실성 빈맥", "heart_failure": "심부전",
    "sepsis": "패혈증", "hyperkalemia": "고칼륨혈증",
    "hypokalemia": "저칼륨혈증", "lbbb": "좌각차단",
    "arrhythmia": "부정맥",
}

ECG_CONFIRMED: dict[str, bool] = {
    "stemi": True, "vfib_vtach": True, "avblock_3rd": True,
    "afib": True, "svt": True, "lbbb": True, "arrhythmia": True,
    "pe": False, "nstemi": False, "heart_failure": False,
    "sepsis": False, "hyperkalemia": False, "hypokalemia": False,
}
```

### 6.2 model_loader.py (신규 — 단순화)

```python
"""ONNX 모델 로더 — K8s 볼륨 마운트 전용, S3 폴백 없음."""
import os
import onnxruntime as ort

_session: ort.InferenceSession | None = None

def load_model(model_path: str) -> ort.InferenceSession:
    global _session
    if _session is not None:
        return _session
    if not os.path.exists(model_path):
        raise FileNotFoundError(
            f"Model not found: {model_path}. 모델 볼륨이 마운트되었는지 확인하세요."
        )
    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    _session = ort.InferenceSession(model_path, providers=providers)
    return _session

def get_session() -> ort.InferenceSession | None:
    """캐시된 세션 반환. 모델 미로드 시 None 반환 (규칙 기반 폴백 허용)."""
    return _session
```

### 6.3 signal_processing.py (신규 — Lambda에서 그대로 복사)

```python
"""ECG 신호 처리 — HR, QTc 계산."""
import numpy as np
from scipy.signal import find_peaks

def compute_hr(signal_array: np.ndarray, fs: int = 500) -> int:
    """Lead II R-peak 기반 심박수 계산."""
    lead_ii = signal_array[1]  # index 1 = Lead II
    peaks, _ = find_peaks(lead_ii, distance=150, height=0.3)
    if len(peaks) < 2:
        return 75  # 기본값
    rr_intervals = np.diff(peaks) / fs
    hr = int(60 / np.mean(rr_intervals))
    return max(30, min(hr, 300))  # 비정상 범위 클리핑

def compute_qtc(hr: int) -> int:
    """Bazett 공식 QTc 보정."""
    if hr <= 0:
        return 400
    qt_ms = 400  # 근사 baseline
    rr_sec = 60 / hr
    qtc = int(qt_ms / (rr_sec ** 0.5))
    return qtc
```

### 6.4 inference.py (신규 — Lambda에서 이식 + K8s 적응)

```python
"""ONNX 13-class ECG 추론 엔진."""
import time, logging
import numpy as np
import boto3
from io import BytesIO

from model_loader import get_session
from signal_processing import compute_hr, compute_qtc
from thresholds import (
    LABEL_NAMES, LABEL_THRESHOLDS, EMERGENCY_LABELS,
    DETECTION_MARGIN, RISK_MAP, LABEL_KO, ECG_CONFIRMED,
)

# shared schemas
import sys; sys.path.insert(0, "/app/shared")
from schemas import Finding

logger = logging.getLogger("ecg-svc")

def load_signal(signal_path: str) -> np.ndarray:
    """S3 또는 로컬에서 .npy 신호 로드 → (12, 5000) 반환."""
    if signal_path.startswith("s3://"):
        parts = signal_path.replace("s3://", "").split("/", 1)
        bucket, key = parts[0], parts[1]
        s3 = boto3.client("s3")
        buf = BytesIO()
        s3.download_fileobj(bucket, key, buf)
        buf.seek(0)
        signal = np.load(buf)
    else:
        signal = np.load(signal_path)

    # shape 정규화
    if signal.shape == (5000, 12):
        signal = signal.T
    signal = np.nan_to_num(signal, nan=0.0)
    return signal.astype(np.float32)

def run_inference(
    signal: np.ndarray,
    patient_info=None,
    context: dict | None = None,
) -> tuple[list[Finding], str, list[str], list[dict], dict]:
    """ONNX 추론 실행 → (findings, metadata)."""
    start = time.time()
    session = get_session()

    # 정규화 (per-lead z-score)
    mean = signal.mean(axis=1, keepdims=True)
    std = signal.std(axis=1, keepdims=True)
    std[std < 1e-6] = 1.0
    normalized = (signal - mean) / std

    # ONNX 추론
    input_name = session.get_inputs()[0].name
    input_data = normalized.reshape(1, 12, 5000).astype(np.float32)
    logits = session.run(None, {input_name: input_data})[0][0]

    # sigmoid
    probs = 1 / (1 + np.exp(-logits))

    # HR/QTc
    hr = compute_hr(signal)
    qtc = compute_qtc(hr)

    # findings 생성
    findings: list[Finding] = []
    for i, label in enumerate(LABEL_NAMES):
        prob = float(probs[i])
        threshold = LABEL_THRESHOLDS[label]
        is_emergency = label in EMERGENCY_LABELS
        margin = prob - threshold

        if is_emergency:
            detected = prob >= threshold
        else:
            detected = margin >= DETECTION_MARGIN

        findings.append(Finding(
            name=f"{LABEL_KO[label]} ({label.upper()})",
            detected=detected,
            confidence=round(prob, 3),
            detail=f"임계값 {threshold} 기준 {'감지됨' if detected else '미감지'} (확률: {prob:.3f})",
            severity=RISK_MAP.get(label, "routine") if detected else None,
            recommendation=_get_recommendation(label) if detected else None,
        ))

    # risk level
    risk_level = _classify_risk(findings)

    # pertinent negatives
    chief = ""
    if patient_info and hasattr(patient_info, "chief_complaint"):
        chief = patient_info.chief_complaint
    pertinent_negatives = _build_pertinent_negatives(findings, chief)

    # suggested next actions
    suggested_next_actions = _suggest_next_actions(findings)

    elapsed_ms = int((time.time() - start) * 1000)
    metadata = {
        "hr": hr, "qtc": qtc,
        "leads": 12, "sampling_rate": 500, "duration_sec": 10,
        "inference_time_ms": elapsed_ms,
    }
    return findings, risk_level, pertinent_negatives, suggested_next_actions, metadata

def _classify_risk(findings: list[Finding]) -> str:
    for f in findings:
        if f.detected and f.severity == "critical":
            return "critical"
    for f in findings:
        if f.detected and f.severity == "urgent":
            return "urgent"
    return "routine"

def _build_pertinent_negatives(findings: list[Finding], chief: str) -> list[str]:
    negatives = []
    chief_lower = chief.lower() if chief else ""
    check_labels = set()
    if any(k in chief_lower for k in ["흉통", "chest", "가슴"]):
        check_labels = {"stemi", "nstemi", "pe"}
    elif any(k in chief_lower for k in ["두근", "palpitation", "심장"]):
        check_labels = {"afib", "svt", "vfib_vtach"}
    for f in findings:
        label = f.name.split("(")[-1].rstrip(")").lower()
        if label in check_labels and not f.detected:
            negatives.append(f"{LABEL_KO.get(label, label)} 음성")
    return negatives

def _suggest_next_actions(findings: list[Finding]) -> list[dict]:
    actions = []
    detected_names = {f.name for f in findings if f.detected}
    for f in findings:
        if not f.detected:
            continue
        label = f.name.split("(")[-1].rstrip(")").lower()
        if label in ("stemi", "nstemi"):
            actions.append({"action": "혈액검사", "reason": "Troponin 확인", "urgency": "urgent"})
        if label == "pe":
            actions.append({"action": "CT Angiography", "reason": "폐색전증 확인", "urgency": "urgent"})
        if label in ("hyperkalemia", "hypokalemia"):
            actions.append({"action": "혈액검사", "reason": "전해질 패널 확인", "urgency": "urgent"})
    return actions

def _get_recommendation(label: str) -> str:
    recs = {
        "stemi": "즉각적인 심장 카테터실 활성화 권고",
        "vfib_vtach": "제세동기 준비 및 ACLS 프로토콜 시작",
        "avblock_3rd": "임시 심박조율기 준비",
        "pe": "CT Angiography 및 항응고 치료 검토",
        "nstemi": "심장내과 응급 협진 권고",
        "afib": "Rate/Rhythm control 평가",
        "svt": "미주신경 자극 또는 Adenosine 고려",
        "hyperkalemia": "긴급 전해질 교정 필요",
    }
    return recs.get(label, "전문의 상담 권고")
```

### 6.5 main.py (수정)

**변경 핵심 포인트:**

```python
# ── 추가 import ──
import os
from model_loader import load_model, get_session
from inference import run_inference, load_signal
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.staticfiles import StaticFiles

# ── lifespan 수정 ──
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ready
    logger.info("Starting %s (port=%s)", settings.service_name, settings.port)

    # ONNX 모델 프리로드 (model_path 설정이 있을 때만)
    if settings.model_path:
        try:
            load_model(settings.model_path)
            logger.info("ONNX model loaded: %s", settings.model_path)
        except FileNotFoundError:
            logger.warning("ONNX model not found at %s — ML inference disabled, rule-based only",
                          settings.model_path)

    _ready = True
    yield
    _ready = False

# ── readyz 수정 — ML 모델 상태 포함 ──
@app.get("/readyz")
def readyz():
    if not _ready:
        return JSONResponse({"status": "loading"}, status_code=503)
    return {
        "status": "ready",
        "ml_model": "loaded" if get_session() is not None else "unavailable",
    }

# ── predict 수정 ──
@app.post("/predict", response_model=PredictResponse)
async def predict(req: PredictRequest):
    if not _ready:
        raise HTTPException(status_code=503, detail="Service not ready")
    start = time.time()

    try:
        ecg_data = req.data

        # ML Path: signal_path가 있고 ONNX 모델이 로드되어 있으면
        if "signal_path" in ecg_data and get_session() is not None:
            signal = load_signal(ecg_data["signal_path"])
            findings, risk_level, pertinent_negs, next_actions, ml_meta = run_inference(
                signal, req.patient_info, req.context
            )
            analysis_type = "ml-model"
        else:
            # Rule Path: 기존 규칙 기반 폴백
            findings = analyze_ecg(req.data, req.patient_info)
            risk_level = "routine"
            pertinent_negs = []
            next_actions = []
            ml_meta = {}
            analysis_type = "rule-based"

        # 요약
        detected = [f for f in findings if f.detected]
        if detected:
            parts = [f"{f.name} ({f.confidence:.0%})" for f in detected]
            summary = f"ECG {analysis_type} 분석: {len(detected)}개 소견 — " + ", ".join(parts)
        else:
            summary = "Normal ECG — no significant abnormalities detected."

        # Bedrock 소견서 (동일)
        report = await generate_ecg_report(
            patient_info=req.patient_info,
            findings=findings,
            bedrock_region=settings.bedrock_region,
            bedrock_model_id=settings.bedrock_model_id,
            context=req.context if req.context else None,
        )

        elapsed_ms = int((time.time() - start) * 1000)

        return PredictResponse(
            status="success",
            modal="ecg",
            findings=findings,
            summary=summary,
            report=report,
            risk_level=risk_level,
            pertinent_negatives=pertinent_negs,
            suggested_next_actions=next_actions,
            metadata={
                "service": settings.service_name,
                "version": "3.0.0",
                "inference_time_ms": elapsed_ms,
                "analysis_type": analysis_type,
                **ml_meta,
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Prediction failed for patient %s", req.patient_id)
        raise HTTPException(status_code=500, detail=str(exc))

# ── 테스트 UI (조건부) ──
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

### 6.6 config.py (수정)

```python
class Settings(BaseSettings):
    # 기존 유지
    bedrock_region: str
    bedrock_model_id: str
    rag_url: str
    log_level: str = "INFO"
    service_name: str = "ecg-svc"
    port: int = 8000
    http_timeout: float = 30.0

    # ── 신규: ML 모델 설정 ──
    model_path: str = "/models/ecg_resnet.onnx"
    signal_bucket: str = "say2-6team"

    model_config = {"case_sensitive": False}
```

### 6.7 requirements.txt (수정)

```
fastapi==0.115.0
uvicorn==0.30.0
pydantic==2.9.0
pydantic-settings==2.5.0
httpx==0.27.0
boto3==1.35.0
numpy==1.26.4
scipy==1.13.0
onnxruntime==1.18.0
```

### 6.8 K8s ecg-svc.yaml (수정)

```yaml
# 변경 포인트만 표시
containers:
  - name: ecg-svc
    resources:
      requests:
        cpu: 500m          # 250m → 500m (ONNX 추론)
        memory: 512Mi      # 유지
      limits:
        cpu: 1000m         # 500m → 1000m
        memory: 1Gi        # 유지
    volumeMounts:
      - name: models
        mountPath: /models
        subPath: ecg-svc
        readOnly: true
volumes:
  - name: models
    persistentVolumeClaim:
      claimName: models-pvc    # local: storage.yaml, EKS: storageclass.yaml
```

---

## 7. Error Handling

| 상황 | 코드 | 처리 |
|------|------|------|
| 모델 파일 없음 (시작 시) | startup | warning 로그, ML 비활성, 규칙 기반만 |
| signal_path 로드 실패 | 500 | 에러 반환 + 로그 |
| ONNX 추론 실패 | 500 | 에러 반환 + 로그 |
| Bedrock 호출 실패 | — | 템플릿 폴백 (기존 동작) |
| signal_path 없음 + 규칙 데이터 없음 | 400 | validation error |

---

## 8. Test Plan

### 8.1 Test Cases

| # | 케이스 | 입력 | 기대 결과 |
|---|--------|------|----------|
| T-1 | ML STEMI 감지 | signal_path=stemi.npy | findings에 STEMI detected=true, risk_level=critical |
| T-2 | ML Normal | signal_path=normal.npy | 주요 질환 detected=false, risk_level=routine |
| T-3 | ML AFib 감지 | signal_path=afib.npy | AFib detected=true |
| T-4 | Rule 폴백 | JSON 데이터 (signal_path 없음) | 규칙 기반 분석 정상 |
| T-5 | readyz 503 | 모델 로드 전 | 503 {"status": "loading"} |
| T-6 | readyz 200 + ML | 모델 로드 후 | 200 {"status": "ready", "ml_model": "loaded"} |
| T-7 | readyz 200 - ML | 모델 파일 없음 | 200 {"status": "ready", "ml_model": "unavailable"} + 규칙 폴백 |

---

## 9. Implementation Guide

### 9.1 Implementation Order

1. [ ] shared/schemas.py — PatientInfo 활력징후 4필드 추가
2. [ ] thresholds.py — 임계값 SSOT 파일 생성
3. [ ] model_loader.py — 단순 ONNX 로더
4. [ ] signal_processing.py — HR/QTc (그대로 복사)
5. [ ] inference.py — ONNX 추론 엔진
6. [ ] config.py — model_path, signal_bucket 추가
7. [ ] main.py — lifespan + ML 분기 + 조건부 static
8. [ ] requirements.txt — 의존성 추가
9. [ ] Dockerfile — 빌드 수정
10. [ ] K8s manifest — 리소스 + 볼륨
11. [ ] 로컬 검증 — Docker build + /predict 테스트

### 9.2 Session Guide

#### Module Map

| Module | Scope Key | Description | Files |
|--------|-----------|-------------|-------|
| 스키마 + 임계값 | `module-1` | schemas.py 확장 + thresholds.py SSOT | 2 |
| ML 코어 | `module-2` | model_loader + signal_processing + inference | 3 |
| 서비스 통합 | `module-3` | main.py + config.py 수정 | 2 |
| 인프라 | `module-4` | requirements + Dockerfile + K8s manifest | 3 |
| 검증 | `module-5` | Docker build + 로컬 K8s 테스트 | - |

#### Recommended Session Plan

| Session | Scope | 작업 | 예상 |
|---------|-------|------|------|
| Session 1 | module-1,2 | 스키마 + 임계값 + ML 코어 3파일 | 40분 |
| Session 2 | module-3,4 | 서비스 통합 + 인프라 수정 | 30분 |
| Session 3 | module-5 | Docker 빌드 + 로컬 검증 | 30분 |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-30 | 초안 — Option C Pragmatic, 수정사항 7건+lifespan 반영, 모델/테스트 파일 확보 완료 | 프로젝트 6팀 |
