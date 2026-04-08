# 🫀 ECG 모달 — MIMIC-IV 기반 24개 질환 다중 분류

> 멀티모달 임상 의사결정 지원 시스템의 심전도(ECG) 분석 컴포넌트  
> 응급실 첫 ECG 파형 하나로 24개 질환을 동시 예측

---

## 전체 시스템 내 위치

```
Bedrock Agent (중앙 오케스트레이터)
      │
      ├── ECG 모달   ← 현재 레포
      ├── CXR 모달
      └── 혈액검사 모달
```

Bedrock Agent가 ECG 결과를 보고 다음 모달(혈액검사, 흉부 X-ray) 호출 여부를 판단합니다.  
ECG 모달은 파형 분석 결과만 반환하며, 다음 단계 결정은 중앙 오케스트레이터가 담당합니다.

---

## 데이터셋

| 항목 | 값 |
|------|-----|
| 원본 | MIMIC-IV ECG (800,035건, 161,352명) |
| 사용 범위 | 응급실 첫 ECG만 (ecg_no_within_stay == 0) |
| 최종 데이터 | 158,440건, 83,740명 |
| ECG 형태 | 12-리드 × 10초 × 500Hz |
| Cross-validation | 20-fold stratified |

### 데이터 분할

| 구분 | Fold | 건수 |
|------|------|------|
| Train | 0~15 | 125,841건 |
| Val | 16~17 | 16,103건 |
| Test | 18~19 | 15,514건 |

---

## 24개 타겟 라벨

### 1차 타겟 — ECG 직접 감지 심혈관 질환 (14개)

| 질환 | ICD-10 | 건수 | 비율 |
|------|--------|------|------|
| 고혈압 | I10 | 55,498 | 35.0% |
| 만성 허혈성 심질환 | I25 | 28,709 | 18.1% |
| 심부전 | I50 | 23,344 | 14.7% |
| 심방세동/조동 | I48 | 22,826 | 14.4% |
| 급성 심근경색 | I21 | 5,239 | 3.3% |
| 발작성 빈맥 | I47 | 3,054 | 1.9% |
| 방실차단/좌각차단 | I44 | 2,690 | 1.7% |
| 폐색전증 | I26 | 2,011 | 1.3% |
| 기타 전도장애 | I45 | 1,854 | 1.2% |
| 협심증 | I20 | 1,474 | 0.9% |
| 심낭질환 | I31 | 1,224 | 0.8% |
| 심정지 | I46 | 813 | 0.5% |

### 2차 타겟 — ECG 간접 단서 비심혈관 질환 (10개)

| 질환 | ICD-10 | 건수 | 비율 |
|------|--------|------|------|
| 만성 신장질환 | N18 | 22,122 | 14.0% |
| 제2형 당뇨병 | E119 | 21,581 | 13.6% |
| 급성 신부전 | N17 | 19,376 | 12.2% |
| 갑상선기능저하증 | E039 | 13,567 | 8.6% |
| COPD | J44 | 12,503 | 7.9% |
| 호흡부전 | J96 | 7,408 | 4.7% |
| 고칼륨혈증 | E875 | 5,902 | 3.7% |
| 저칼륨혈증 | E876 | 4,335 | 2.7% |
| 패혈증 | R65 | 4,167 | 2.6% |
| 칼슘 대사 이상 | E835 | 1,741 | 1.1% |

> **핵심 발견**: 패혈증(28.1%), 호흡부전(27.5%), 급성 신부전(12.6%) 등 비심혈관 질환의  
> 30일 사망률이 심방세동(8.8%)보다 3배 이상 높음 → ECG로 비심혈관 고위험 질환 조기 감지

---

## 신호 전처리 파이프라인

```
.hea + .dat 파형 파일
    │
    ▼
wfdb 로딩 → (5000, 12) float32
    │
    ▼
NaN 선형 보간 + ±3mV 클리핑
    │
    ▼
resampy 리샘플링: 500Hz → 100Hz → (1000, 12)
    │
    ▼
12채널 고정 순서 정렬 (I, II, V1~V6, III, aVR, aVL, aVF)
    │
    ▼
PTB-XL 채널별 Z-score 정규화 + ±5σ 클리핑
    │
    ▼
모델 입력: (batch, 12, 1000)
```

### PTB-XL 정규화 통계 (cross-dataset 일반화)

| 채널 | mean | std |
|------|------|-----|
| I | -0.00185 | 0.164 |
| II | -0.00130 | 0.165 |
| V1 | 0.00017 | 0.234 |
| V2~V6 | ... | ... |

> 밴드패스 필터, 노치 필터, 베이스라인 보정 미적용 — 모델이 학습으로 대체 (ECG-MIMIC 논문과 동일)

---

## 인구통계 결합 (논문 대비 차별화 ①)

ECG-MIMIC 논문은 ECG 신호만 입력. 본 모델은 나이/성별을 추가 입력으로 결합.

**근거**: 같은 ECG 파형도 환자에 따라 임상적 의미가 다름
- 심방세동 유병률: 50대 2% → 80대 15% (나이에 따라 7배 차이)
- 급성 심근경색: 남성이 여성보다 2배 높음
- 고칼륨혈증: 고령 + 신부전 환자에서 집중

### 인코딩

| 피처 | 원본 | 변환 |
|------|------|------|
| 나이 | 18~101세 | `(age - 18) / (101 - 18)` → 0~1 |
| 성별 | M / F / 미상 | 1.0 / 0.0 / 0.5 |

### 모델 결합 구조

```
ECG 신호 (batch, 12, 1000)          나이/성별 (batch, 2)
        │                                    │
   CNN stem (다운샘플)                   FC (2→32)
        │                                    │
   MambaBlock × 6                       GELU
        │                                    │
  AdaptiveAvgPool                      임베딩 (32)
        │                                    │
  ECG 임베딩 (512)                           │
        └──────────── concat ────────────────┘
                          │
                     (544차원)
                          │
                  LayerNorm → Dropout
                          │
                  FC (544→128) → GELU
                          │
                  FC (128→24)
                          │
                  24개 질환 logit
```

---

## 모델 아키텍처: S6 (Mamba)

S4 대비 핵심 차이: **Selective Scan** — 입력에 따라 상태 선택 파라미터(B, C, Δt)를 동적으로 생성

```
S4:  B, C, Δt → 고정 파라미터
S6:  B, C, Δt → 입력 x에서 동적 생성 (관련 없는 정보 무시, 중요한 시점 집중)
```

### 구조

| 구성 | 세부 |
|------|------|
| CNN stem | Conv1d(12→128, k=7, stride=2) → Conv1d(128→256, k=5, stride=2) → Conv1d(256→512, k=3, stride=2) |
| 시퀀스 길이 | 1000 → 500 → 250 → 125 |
| MambaBlock | 6개 (MambaLayer + FFN) |
| d_model | 512 |
| d_state | 64 |
| 총 파라미터 | ~9M |

---

## 긴급도 가중 Loss (논문 대비 차별화 ②)

### 핵심 아이디어

```
ECG-MIMIC 논문:  Loss = BCE(pred, target)           ← 모든 질환 동등
본 모델:          Loss = Σ weight[i] × BCE(pred[i], target[i])   ← 30일 사망률 기반
```

### 30일 사망률 기반 3단계 가중치

| Tier | 기준 | 가중치 | 질환 예시 |
|------|------|--------|---------|
| Tier 1 | 사망률 ≥ 10% | **3.0** | 심정지(60.1%), 패혈증(28.1%), 호흡부전(27.5%), 급성MI(12.7%) |
| Tier 2 | 사망률 5~10% | **2.0** | 심방세동(8.8%), 심부전(8.6%), COPD(8.0%) |
| Tier 3 | 사망률 2~5% | **1.5** | 고혈압(4.0%), 당뇨(4.7%), 협심증(2.7%) |

### 가중치 벡터 (라벨 순서)

```python
URGENCY_WEIGHTS = [
    2.0,  # afib_flutter        (8.8%)
    2.0,  # heart_failure       (8.6%)
    1.5,  # hypertension        (4.0%)
    2.0,  # chronic_ihd         (6.4%)
    3.0,  # acute_mi            (12.7%)
    3.0,  # paroxysmal_tachy    (11.6%)
    2.0,  # av_block_lbbb       (6.5%)
    2.0,  # other_conduction    (6.0%)
    3.0,  # pulmonary_embolism  (11.7%)
    3.0,  # cardiac_arrest      (60.1%)
    1.5,  # angina              (2.7%)
    3.0,  # pericardial_disease (10.6%)
    2.0,  # afib_detail         (9.2%)
    2.0,  # hf_detail           (8.9%)
    1.5,  # dm2                 (4.7%)
    3.0,  # acute_kidney_failure(12.6%)
    2.0,  # hypothyroidism      (6.3%)
    2.0,  # copd                (8.0%)
    2.0,  # chronic_kidney      (7.6%)
    3.0,  # hyperkalemia        (12.6%)
    2.0,  # hypokalemia         (7.8%)
    3.0,  # respiratory_failure (27.5%)
    3.0,  # sepsis              (28.1%)
    3.0,  # calcium_disorder    (12.1%)
]
```

### 옵티마이저

```
AdamW  lr=1e-4, weight_decay=1e-4
OneCycleLR  max_lr=1e-4, warmup 10%, cosine decay
Gradient clipping: max_norm=1.0
Batch size: 64
```

---

## 학습 결과 (S6, 20 에포크)

| 지표 | 값 |
|------|-----|
| Macro AUROC | **0.814** |
| Tier 1 (놓치면 사망) | **0.809** |
| Tier 2 (긴급) | **0.844** |
| Tier 3 (중요) | **0.721** |

### 질환별 AUROC

| 질환 | AUROC |
|------|-------|
| 심방세동/조동 | 0.903 ✅ |
| 심부전 | 0.897 ✅ |
| 방실차단/좌각차단 | 0.898 ✅ |
| 패혈증 | 0.869 ✅ |
| 급성 심근경색 | 0.846 ✅ |
| 기타 전도장애 | 0.848 ✅ |
| 호흡부전 | 0.834 ✅ |
| 고칼륨혈증 | 0.820 ✅ |
| 발작성 빈맥 | 0.817 ✅ |
| 만성 신장질환 | 0.840 ✅ |
| 심정지 | 0.831 ✅ |
| 폐색전증 | 0.722 ⚠️ |
| 갑상선기능저하증 | 0.722 ⚠️ |
| 고혈압 | 0.699 ⚠️ (ECG 특이 소견 적음) |
| 제2형 당뇨병 | 0.672 ⚠️ (ECG로 감지 어려움) |

---

## 분류 임계값 (Threshold) 설계

모델 출력 확률이 threshold 이상이면 해당 질환 detected로 판정.

| Tier | Threshold 전략 | 의미 |
|------|---------------|------|
| Tier 1 | val set PR curve 기반 (recall ≥ 0.90 목표) | 놓치지 않는 것 최우선 |
| Tier 2 | 0.40 | 어느 정도 확신할 때 |
| Tier 3 | 0.45 | 확실할 때만 |

### Tier 1 — val set 기반 실제 threshold 값

Tier 1은 희귀 질환 특성상 모델 출력 확률이 전반적으로 낮아 (0.001~0.06 범위),  
val set PR curve에서 recall ≥ 0.90을 만족하는 최적 threshold를 탐색하여 적용.

| 질환 | Threshold | val Recall | val Precision | AUROC | 양성 샘플 |
|------|-----------|-----------|--------------|-------|---------|
| cardiac_arrest | 0.001 | 0.923 ✅ | 0.010 | 0.831 | 78 |
| acute_mi | 0.010 | 0.901 ✅ | 0.066 | 0.859 | 548 |
| pulmonary_embolism | 0.005 | 0.928 ✅ | 0.015 | 0.693 | 207 |
| paroxysmal_tachycardia | 0.008 | 0.908 ✅ | 0.036 | 0.818 | 325 |
| hyperkalemia | 0.012 | 0.905 ✅ | 0.068 | 0.823 | 629 |
| respiratory_failure | 0.014 | 0.903 ✅ | 0.089 | 0.817 | 731 |
| sepsis | 0.011 | 0.906 ✅ | 0.063 | 0.856 | 405 |
| pericardial_disease | 0.002 | 0.886 ⚠️ | 0.012 | 0.822 | 114 |
| av_block_lbbb | 0.021 | 0.806 ✅ | 0.106 | 0.923 | 283 |
| calcium_disorder | 0.004 | 0.895 ⚠️ | 0.017 | 0.705 | 190 |
| acute_kidney_failure | 0.057 | 0.899 ⚠️ | 0.192 | 0.788 | 1,902 |

> Precision이 낮은 것은 오검출을 감수하더라도 **놓치지 않는 것을 최우선**으로 설계했기 때문.  
> Bedrock Agent는 Tier 1 findings의 confidence가 낮을 경우 "의심 수준"으로 처리.

---

## 서비스 아키텍처 (ecg-svc)

```
POST /predict
      │
      ▼
Layer 1: ECGPreprocessor
  - S3/로컬 .npy 로드
  - NaN 보간 + 리샘플링
  - PTB-XL 정규화
  → (1, 12, 1000), (1, 2)
      │
      ▼
Layer 2: ECGInferenceEngine
  - ONNX Runtime (ecg_s6.onnx)
  - S3 모델 자동 다운로드 + 캐시
  → 24개 질환 확률 dict
      │
      ▼
Layer 3: ClinicalEngine
  - Threshold 적용 → detected 판정
  - severity / recommendation 매핑
  - risk_level 산출
  → findings (detected만), summary, risk_level
      │
      ▼
PredictResponse (JSON)
```

### API

| 엔드포인트 | 설명 |
|-----------|------|
| `POST /predict` | ECG 분석 |
| `GET /health` | 헬스체크 |
| `GET /ready` | 모델 로드 완료 여부 (readiness probe) |

### Request / Response

```json
// Request
{
  "patient_id": "TEST-001",
  "patient_info": {"age": 72, "sex": "F", "chief_complaint": "흉통"},
  "data": {"signal_path": "s3://say2-6team/mimic/ecg/signals/40689238.npy"},
  "context": {}
}

// Response
{
  "status": "ok",
  "modal": "ecg",
  "findings": [
    {
      "name": "afib_flutter",
      "confidence": 0.87,
      "severity": "moderate",
      "detail": "심방세동/조동 (신뢰도 87.0%)",
      "recommendation": "심박수 조절 및 항응고 요법 검토"
    }
  ],
  "summary": "[주의] 심방세동/조동, 심부전 이상 소견 감지",
  "risk_level": "urgent",
  "metadata": {
    "patient_id": "TEST-001",
    "latency_ms": 85.3,
    "model": "ecg_s6.onnx",
    "num_detected": 2
  }
}
```

---

## 논문 대비 기여점 요약

| 항목 | ECG-MIMIC 논문 | 본 모델 |
|------|:-------------:|:-------:|
| 데이터 범위 | 전체 800K 혼합 | **ED 첫 ECG 158K** |
| 타겟 라벨 | 빈도 기반 자동 | **24개 임상 기반 수동 선정** |
| 모델 입력 | ECG 신호만 | **ECG + 나이 + 성별** |
| Loss | BCE 동일 가중치 | **30일 사망률 기반 가중 BCE** |
| 가중치 근거 | 없음 | **MIMIC-IV 실제 사망 데이터** |
| 평가 | macro AUROC | **Tier별 AUROC + Recall** |
| 관점 | 범용 스크리닝 | **응급실 의사결정 최적화** |
| 핵심 가치 | "얼마나 정확한가" | **"놓치지 않는가"** |

---

## 배포

### 로컬 실행

```bash
cd ecg-svc
pip install -r requirements.txt
python main.py
# → http://localhost:8000
```

### EKS 배포

```bash
bash deploy.sh
```

### 환경 변수 (.env)

```
S3_BUCKET=say2-6team
S3_MODEL_KEY=mimic/ecg/ecg_s6.onnx
S3_DATA_KEY=mimic/ecg/ecg_s6.onnx.data
MODEL_DIR=./models
HOST=0.0.0.0
PORT=8000
```

---

## 프로젝트 구조

```
ecg-svc/
├── config.py                    # 환경 설정
├── thresholds.py                # 질환별 임계값 (Tier 기반)
├── pipeline.py                  # Layer 1→2→3 오케스트레이션
├── main.py                      # FastAPI 진입점
├── requirements.txt
├── Dockerfile
├── shared/
│   ├── labels.py                # 24개 질환 메타데이터
│   └── schemas.py               # Pydantic 스키마
├── layer1_preprocessing/
│   └── preprocessor.py          # 신호 전처리
├── layer2_inference/
│   └── mamba_s6.py              # ONNX 추론 엔진
└── layer3_clinical_logic/
    └── engine.py                # 임상 해석 엔진

k8s/
├── deployment.yaml
└── ingress.yaml

train_ecg_s6.py                  # S6 모델 학습
export_onnx.py                   # PyTorch → ONNX 변환
```
