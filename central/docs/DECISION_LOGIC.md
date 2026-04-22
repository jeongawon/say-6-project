# Fusion Decision Logic

## 개요

Fusion Decision Engine은 멀티모달 결과를 분석하고 다음 단계를 결정하는 중앙 의사결정 시스템입니다.

## 결정 흐름

```
입력: 환자 정보 + 현재까지의 모달 결과
  │
  ▼
┌─────────────────────────────────┐
│ 1. 초기 모달 선택                │
│    (Chief Complaint 기반)        │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│ 2. 고위험 패턴 감지              │
│    → NEED_REASONING              │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│ 3. 신뢰도 체크                   │
│    (< 0.60) → CALL_NEXT_MODALITY │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│ 4. 결과 기반 추가 검사 제안      │
│    → CALL_NEXT_MODALITY          │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│ 5. 복잡도 평가                   │
│    → NEED_REASONING              │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│ 6. 리포트 생성                   │
│    → GENERATE_REPORT             │
└─────────────────────────────────┘
```

## 결정 타입

### 1. CALL_NEXT_MODALITY
추가 모달 호출이 필요한 경우

**조건**:
- 초기 요청 (결과 없음)
- 신뢰도가 낮은 결과 존재 (< 0.60)
- 현재 결과가 추가 검사를 시사
- 최대 반복 횟수 미달 (< 3)

**응답 형식**:
```json
{
  "decision": "CALL_NEXT_MODALITY",
  "next_modalities": ["ECG", "LAB"],
  "rationale": "Low confidence detected, requesting additional modalities",
  "risk_level": "medium"
}
```

### 2. NEED_REASONING
LLM 기반 임상 추론이 필요한 경우

**조건**:
- 고위험 패턴 감지
- 복잡한 케이스 (여러 모달에서 이상 소견)
- 상충되는 결과

**응답 형식**:
```json
{
  "decision": "NEED_REASONING",
  "rationale": "High-risk pattern detected requiring clinical reasoning",
  "risk_level": "high"
}
```

### 3. GENERATE_REPORT
최종 리포트 생성 준비 완료

**조건**:
- 충분한 정보 수집 완료
- 고신뢰도 결과
- 최대 반복 횟수 도달

**응답 형식**:
```json
{
  "decision": "GENERATE_REPORT",
  "rationale": "Sufficient information gathered for report generation",
  "risk_level": "low"
}
```

## Chief Complaint 기반 초기 모달 선택

```python
CHIEF_COMPLAINT_MODALITY_MAP = {
    'chest pain': ['CXR', 'ECG'],
    'shortness of breath': ['CXR', 'ECG'],
    'dyspnea': ['CXR', 'ECG'],
    'abdominal pain': ['LAB', 'CXR'],
    'fever': ['LAB', 'CXR'],
    'trauma': ['CXR', 'LAB'],
    'altered mental status': ['LAB', 'ECG'],
    'syncope': ['ECG', 'LAB'],
    'headache': ['LAB'],
    'weakness': ['LAB', 'ECG']
}
```

**기본값**: Chief complaint가 매칭되지 않으면 `['CXR', 'LAB']`

## 고위험 패턴

다음 조합이 감지되면 즉시 `NEED_REASONING`:

### 패턴 1: 폐렴 + 감염 지표
```python
{
    'CXR': ['pneumonia', 'infiltrate', 'consolidation'],
    'LAB': ['elevated wbc', 'leukocytosis']
}
```

### 패턴 2: 심부전 + 심전도 이상
```python
{
    'CXR': ['cardiomegaly', 'pulmonary edema'],
    'ECG': ['st elevation', 'st depression']
}
```

### 패턴 3: STEMI + 심근 손상
```python
{
    'ECG': ['st elevation', 'stemi'],
    'LAB': ['elevated troponin']
}
```

### 패턴 4: 기흉 + 부정맥
```python
{
    'CXR': ['pneumothorax'],
    'ECG': ['arrhythmia']
}
```

## 신뢰도 임계값

```python
HIGH_CONFIDENCE = 0.85
LOW_CONFIDENCE = 0.60
```

- **< 0.60**: 추가 모달 호출 고려
- **0.60 - 0.85**: 정상 처리
- **> 0.85**: 고신뢰도

## 결과 기반 추가 검사 제안

### CXR 결과 기반

| CXR Finding | 추가 검사 |
|-------------|----------|
| Cardiac abnormality (cardiomegaly, heart) | ECG |
| Infection (pneumonia, infiltrate) | LAB |

### ECG 결과 기반

| ECG Finding | 추가 검사 |
|-------------|----------|
| Ischemia (st elevation, infarction) | LAB, CXR |

### LAB 결과 기반

| LAB Finding | 추가 검사 |
|-------------|----------|
| Cardiac markers (elevated troponin) | ECG |

## 복잡도 평가

다음 조건을 만족하면 복잡한 케이스로 판단:

1. 2개 이상의 모달 결과 존재
2. 하나 이상의 이상 소견 (abnormal, elevated, positive, detected)

→ `NEED_REASONING` 결정

## 위험도 평가

### High Risk
다음 키워드 포함 시:
- stemi, st elevation
- pneumothorax
- massive, severe, critical
- acute, emergency

### Medium Risk
다음 키워드 포함 시:
- pneumonia, infiltrate
- cardiomegaly
- arrhythmia
- elevated, abnormal

### Low Risk
- 위 키워드 없음
- Normal 소견

## 반복 제한

```python
MAX_ITERATIONS = 3
```

3회 반복 후에는 현재 정보로 리포트 생성.

## 의사결정 예시

### 예시 1: Chest Pain 환자

**입력**:
```json
{
  "chief_complaint": "chest pain",
  "modalities_completed": [],
  "inference_results": []
}
```

**결정**:
```json
{
  "decision": "CALL_NEXT_MODALITY",
  "next_modalities": ["CXR", "ECG"],
  "rationale": "Initial modality selection based on chief complaint: chest pain"
}
```

### 예시 2: CXR + LAB 고위험 패턴

**입력**:
```json
{
  "modalities_completed": ["CXR", "LAB"],
  "inference_results": [
    {
      "modality": "CXR",
      "finding": "Right lower lobe pneumonia",
      "confidence": 0.88
    },
    {
      "modality": "LAB",
      "finding": "Leukocytosis with elevated WBC",
      "confidence": 0.89
    }
  ]
}
```

**결정**:
```json
{
  "decision": "NEED_REASONING",
  "rationale": "High-risk pattern detected requiring clinical reasoning",
  "risk_level": "high"
}
```

### 예시 3: 낮은 신뢰도

**입력**:
```json
{
  "modalities_completed": ["CXR"],
  "inference_results": [
    {
      "modality": "CXR",
      "finding": "Possible infiltrate",
      "confidence": 0.55
    }
  ],
  "iteration": 1
}
```

**결정**:
```json
{
  "decision": "CALL_NEXT_MODALITY",
  "next_modalities": ["LAB"],
  "rationale": "Low confidence detected, requesting additional modalities: LAB"
}
```

## 커스터마이징

### 새로운 고위험 패턴 추가

`decision_engine.py`의 `HIGH_RISK_PATTERNS`에 추가:

```python
HIGH_RISK_PATTERNS = [
    # 기존 패턴들...
    {
        'ECG': ['ventricular tachycardia', 'v-tach'],
        'LAB': ['hyperkalemia', 'elevated potassium']
    }
]
```

### Chief Complaint 매핑 추가

```python
CHIEF_COMPLAINT_MODALITY_MAP = {
    # 기존 매핑들...
    'back pain': ['CXR', 'LAB'],
    'nausea': ['LAB']
}
```

### 신뢰도 임계값 조정

```python
HIGH_CONFIDENCE = 0.90  # 더 엄격하게
LOW_CONFIDENCE = 0.50   # 더 관대하게
```

## 향후 개선 방향

### 1. ML 기반 결정
- 하드코딩 규칙 → 학습된 모델
- 과거 케이스 데이터로 학습
- 최적 워크플로우 자동 발견

### 2. 강화학습
- 보상: 진단 정확도, 검사 비용, 시간
- 동적 정책 학습
- 환자별 맞춤 워크플로우

### 3. 실시간 학습
- 의료진 피드백 수집
- 온라인 학습으로 규칙 업데이트
- A/B 테스트로 새로운 규칙 검증

### 4. 설명 가능성
- 결정 근거 시각화
- 규칙 추적 가능성
- 의료진 신뢰도 향상
