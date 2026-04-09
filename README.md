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

### PTB-XL 정규화 (cross-dataset 일반화)

PTB-XL은 독일 베를린 병원에서 수집한 별도 ECG 데이터셋(21,799명)입니다.  
MIMIC 학습 데이터 통계 대신 PTB-XL 통계를 사용하는 이유:

```
MIMIC 통계로 정규화  →  학습 데이터에 과적합
                    →  다른 병원/장비 ECG 입력 시 성능 저하

PTB-XL 통계로 정규화 →  외부 데이터셋 기준으로 스케일 통일
                    →  실제 병원 장비 ECG에도 일반화 가능
```

ECG-MIMIC 논문에서 동일하게 채택한 방식입니다.

```python
# 채널별 평균 (12리드: I, II, V1~V6, III, aVR, aVL, aVF)
mean = [-0.00185, -0.00130,  0.00017, -0.00091,
        -0.00149, -0.00175, -0.00077, -0.00207,
         0.00054,  0.00156, -0.00114, -0.00036]

# 채널별 표준편차
std  = [0.164, 0.165, 0.234, 0.338,
        0.334, 0.306, 0.273, 0.276,
        0.171, 0.140, 0.146, 0.147]

signal = (signal - mean) / std   # Z-score 정규화
signal = clip(signal, -5, 5)     # ±5σ 극단값 제거
```

> 평균이 거의 0에 가까운 것은 ECG 신호 특성상 기저선이 0mV 근처이기 때문

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

| Tier | 기준 | Threshold | 의미 |
|------|------|-----------|------|
| Tier 1 | 사망률 ≥ 10% | **0.30** | 30% 이상이면 의심 → 놓치지 않는 것 최우선 |
| Tier 2 | 사망률 5~10% | **0.40** | 어느 정도 확신할 때 |
| Tier 3 | 사망률 2~5% | **0.45** | 확실할 때만 |

> 초기에 val set PR curve 기반 최적값(0.001~0.06)을 사용했으나, 실서비스에서 confidence 2~3%에도  
> alert가 발생하는 오탐 문제가 확인되어 임상적으로 의미 있는 고정값(0.30/0.40/0.45)으로 전환.

---

## 서비스 아키텍처 (ecg-svc)

```
POST /predict
      │
      ▼
Layer 1: ECGPreprocessor
  - S3/로컬 WFDB (.hea + .dat) 로딩
  - NaN 보간 + ±3mV 클리핑
  - 500Hz → 100Hz 리샘플링
  - 12채널 정렬 + PTB-XL 정규화
  - ECG Vitals 측정 (정규화 전 원본 신호에서 HR·리듬 계산)
  → (1, 12, 1000), (1, 2), vitals
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
  - ECG Vitals 보정 (Afib 계열 감지 시 irregular_rhythm 강제 true)
  → findings, summary, risk_level, ecg_vitals
      │
      ▼
PredictResponse (JSON)
```

### ECG Vitals 측정

정규화 전 원본 신호(100Hz)에서 Pan-Tompkins 간이 R-peak 검출로 심박수와 리듬 측정.  
모델 추론과 독립적으로 동작하며, 모델 findings와 교차 검증하여 신뢰도를 높임.

| 수치 | 측정 방법 | 보정 |
|------|----------|------|
| heart_rate | Lead II R-R 간격 평균 → 60/RR | — |
| bradycardia | HR < 50 bpm | — |
| tachycardia | HR > 100 bpm | — |
| irregular_rhythm | RR 변동계수 > 0.15 | Afib/전도이상 감지 시 true 강제 |

> Bedrock Agent는 ecg_vitals + findings를 종합하여 다음 모달(혈액검사, 흉부 X-ray) 호출 판단.  
> 라우팅 결정은 ECG 모달이 아닌 중앙 오케스트레이터가 전담.

### API

| 엔드포인트 | 설명 |
|-----------|------|
| `POST /predict` | ECG 분석 |
| `GET /health` | 헬스체크 |
| `GET /ready` | 모델 로드 완료 여부 (readiness probe) |
| `GET /docs` | Swagger UI |

### Request / Response

```json
// Request
{
  "patient_id": "TEST-001",
  "patient_info": {"age": 72, "sex": "F", "chief_complaint": "흉통"},
  "data": {"record_path": "s3://say2-6team/mimic/ecg/waveforms/files/p1000/p10000032/s40689238/40689238"},
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
  "ecg_vitals": {
    "heart_rate": 90.6,
    "bradycardia": false,
    "tachycardia": false,
    "irregular_rhythm": true
  },
  "all_probs": {
    "afib_flutter": 0.8708, "heart_failure": 0.4543, "hypertension": 0.3976,
    "dm2": 0.1106, "copd": 0.0243, "hypothyroidism": 0.0408, "...": "..."
  },
  "metadata": {
    "patient_id": "TEST-001",
    "latency_ms": 550.3,
    "model": "ecg_s6.onnx",
    "num_detected": 2
  }
}
```

### all_probs — 24개 전체 질환 확률

`findings`는 threshold를 넘은 질환만 포함하지만, `all_probs`는 24개 전체 질환의 모델 출력 확률을 포함합니다.

**Bedrock Agent 라우팅에 핵심적인 필드:**

```
ECG 결과: findings=[], all_probs={dm2: 0.11, hypertension: 0.40, ...}

Bedrock Agent 판단:
  - dm2: 0.11 → threshold(0.45) 미달이지만 0이 아님
    → 환자 나이 65세 + 고혈압 소견 → 혈액검사(HbA1c)로 확인
  - hypertension: 0.40 → threshold(0.45) 미달이지만 경계값
    → 혈압 측정 권고
```

ECG가 확신하지 못하는 질환도 Bedrock Agent가 다른 모달로 보완 판단할 수 있는 근거를 제공합니다.

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

## 벤치마크 (108건 MIMIC-IV ECG, 골든셋 레이블 대조)

MIMIC-IV 퇴원요약 200명 중 ECG 파형 데이터가 존재하는 108명 대상.

### Tier별 성능

| Tier | PPV | Recall | F1 |
|------|-----|--------|-----|
| Tier 1 (사망률≥10%) | 60.9% | 29.2% | 39.4% |
| Tier 2 (사망률5~10%) | 62.1% | 38.3% | 47.4% |
| Tier 3 (사망률2~5%) | 52.5% | 42.1% | 46.7% |
| **전체** | **58.7%** | **37.8%** | **46.0%** |

### 질환별 하이라이트

| 질환 | F1 | 비고 |
|------|-----|------|
| afib_flutter | 71.4% | ECG 특이 패턴, 최고 성능 |
| afib_detail | 70.6% | |
| acute_mi | 66.7% | Recall 100% |
| hypertension | 58.7% | FP 29건 (비특이 ST 변화 오인) |
| dm2, copd, hypothyroidism | 0% | ECG 파형에 특이 신호 없음 → 혈액검사 모달 위임 |

### 한계 및 원인

1. **Metabolic 질환 탐지 불가** — dm2, copd, hypothyroidism 등은 ICD 코드 기반 레이블이지만 ECG 파형에 특이 소견이 없어 모델이 학습 불가. 혈액검사 모달로 위임 설계.
2. **Hypertension FP 과다** — 비특이 ST-T 변화를 고혈압으로 오인. threshold 상향 또는 인구통계 보정 필요.
3. **만성 질환 Recall 부족** — chronic_kidney FN 16건, chronic_ihd FN 16건. ECG 변화가 서서히 진행되어 threshold 미달.

### 108건 전체 검증 결과

| 검증 항목 | 결과 |
|---|---|
| all_probs 24개 완전 출력 | 108/108 (100%) |
| 확률 범위 (0~1) | 0.0001 ~ 0.9295 (정상) |
| findings ↔ all_probs 일치 | 불일치 0건 |
| threshold 초과 ↔ findings 일치 | 누락 0건 |
| Afib 감지 + irregular=false 모순 | 0건 (보정 완료) |
| HR 비현실적 (< 25 or > 220) | 0건 |
| risk_level ↔ findings 불일치 | 0건 |

---

## 모달 평가 — 멀티모달 시스템 내 ECG의 역할과 근거

### 학습 품질

| 구분 | 판단 | 근거 |
|---|---|---|
| ECG 특이 질환 (afib, MI, 전도장애) | 잘 학습됨 | AUROC 0.85~0.90, F1 66~71% |
| 만성 심혈관 (heart_failure, chronic_ihd) | 보통 | AUROC 0.84~0.89, Recall 33~50% |
| 비심혈관 대사질환 (dm2, copd, 갑상선) | 학습 불가 | F1 0% — ECG 파형에 특이 신호 없음 |

> AUROC가 높은데 F1이 낮은 이유: AUROC는 "순위를 매기는 능력", F1은 "실제 분류 정확도".  
> 모델이 질환자를 비질환자보다 높은 확률로 출력하지만(AUROC 높음), threshold를 넘을 만큼 확신 있게 출력하지 못함(F1 낮음).

### 설계 차별화와 근거

| 차별화 | 근거 |
|---|---|
| **인구통계 결합 (나이+성별)** | Afib 유병률이 나이에 따라 7배 차이 (50대 2% → 80대 15%). 같은 파형도 context에 따라 의미가 다름 |
| **긴급도 가중 Loss** | MIMIC-IV 실제 사망 데이터 기반. 심정지 60.1%, 패혈증 28.1% vs 고혈압 4.0% — 치명 질환 우선 학습 |
| **ED 첫 ECG만 사용** | 논문은 800K 전체(반복 촬영 포함) → data leakage 위험. 본 모델은 158K ED 첫 ECG로 실사용 시나리오 최적화 |

### ECG가 못 보는 질환 → 다른 모달 위임 구조

| ECG 미감지 질환 | 원인 | 담당 모달 | 라우팅 근거 |
|---|---|---|---|
| dm2 (당뇨) | ECG 파형에 혈당 반영 안 됨 | 혈액검사 (HbA1c) | all_probs로 확률 전달 |
| copd | 폐질환은 ECG 간접 소견만 | 흉부 X-ray + 폐기능검사 | all_probs로 확률 전달 |
| hypothyroidism | 서맥·QT연장 가능하나 비특이적 | 혈액검사 (TSH) | ecg_vitals.bradycardia + all_probs |

> **핵심**: ECG 모달은 `findings`(확진 수준) + `ecg_vitals`(파형 측정) + `all_probs`(24개 전체 확률)을 모두 반환.  
> Bedrock Agent는 이 세 가지를 종합하여:
> 1. `findings` → 확진된 질환 기반 즉시 조치
> 2. `ecg_vitals` → HR/리듬 이상 기반 간접 라우팅
> 3. `all_probs` → threshold 미달이지만 0이 아닌 질환 → 다른 모달로 보완 확인

### Bedrock Agent 라우팅 예시

```
환자 A: 65세 남성
  ECG findings: [heart_failure(47%)]
  ecg_vitals: HR=42, bradycardia=true
  all_probs: dm2=0.11, hypothyroidism=0.15

  → Bedrock 판단:
    1. heart_failure 확인 → BNP 혈액검사 호출
    2. bradycardia + hypothyroidism=0.15 → TSH 혈액검사 호출
    3. dm2=0.11 + 고령 → HbA1c 혈액검사 호출
    4. 심부전 → CXR 모달 호출 (폐부종 확인)
```

---

## 배포

### EC2 배포 (현재)

| 항목 | 값 |
|------|-----|
| Instance | t3.large (i-008fbaebbadbc0dee) |
| IP | 13.124.117.190:8000 |
| AMI | Amazon Linux 2023 |
| 컨테이너 | Docker (ECR: ecg-modal:latest) |
| IAM Role | say-2-ec2-s3-api-role |

```bash
# ECR 빌드 & 푸시 (Mac ARM64 → x86_64 크로스빌드)
docker buildx build --platform linux/amd64 -t ecg-modal:latest ./ecg-svc --load
bash deploy.sh

# EC2 배포
ssh ec2-user@13.124.117.190
sudo docker pull <ECR_URI>
sudo docker run -d --name ecg-svc -p 8000:8000 ...
```

### 로컬 실행

```bash
cd ecg-svc
pip install -r requirements.txt
python main.py
# → http://localhost:8000
```

### Streamlit 데모

```bash
pip install streamlit plotly
streamlit run streamlit_demo.py
# → http://localhost:8501
```

### 환경 변수

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
│   └── preprocessor.py          # WFDB 전처리 + ECG Vitals 측정
├── layer2_inference/
│   └── mamba_s6.py              # ONNX 추론 엔진
└── layer3_clinical_logic/
    └── engine.py                # 임상 해석 + Vitals 보정

streamlit_demo.py                # EMR 스타일 데모 UI (12리드 파형 + AI 분석)
test_golden.py                   # 200명 골든셋 벤치마크
train_ecg_s6.py                  # S6 모델 학습
export_onnx.py                   # PyTorch → ONNX 변환
```
