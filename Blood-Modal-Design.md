# 혈액 모달 설계 문서

## 1. 시스템 내 역할

각 모달은 자기 역할만 수행하고, 다음 검사 판단은 전적으로 중앙(Bedrock Agent)이 담당한다.
모달 출력에 `recommended_next` 같은 판단 정보는 포함하지 않는다.

```
혈액 모달 출력 (사실만 전달)
  → Bedrock Agent 판단 (임상적 해석 + 다음 모달 결정)
  → ECG / CXR 모달 추가 호출 (필요 시)
```

---

## 2. 진단 그룹 구성 (8개)

응급실에서 빈번하고 놓치면 안 되는 질환 기준으로 구성.

| 그룹 | 주요 질환 | 주 모달 | 보조 모달 |
|------|----------|--------|---------|
| Sepsis_Group | 패혈증, 패혈성 쇼크 | 혈액 | ECG(빈맥), CXR(폐렴) |
| Cardio_Group | 심근경색, 심방세동, 심부전 | ECG | 혈액(troponin), CXR(폐부종) |
| Kidney_Group | 급성신부전, 고혈압 위기 | 혈액 | ECG(고칼륨 패턴) |
| Pancreatitis_Group | 급성 췌장염 | 혈액 | CXR(중증도 판단) |
| Chemo_Group | 항암 합병증, 호중구감소증 | 혈액 | ECG(심독성), CXR(폐독성) |
| Stroke_Group | 허혈성/출혈성 뇌졸중 | 혈액(감별) | ECG(심방세동 원인) |
| Respiratory_Group | 호흡부전, COPD, 폐렴 | CXR | 혈액(감별), ECG(우심부하) |
| GI_Bleeding_Group | 위장관 출혈, 위궤양 | 혈액 | ECG(출혈성 쇼크 빈맥) |

### ICD 코드 매핑

```python
GROUP_ICD = {
    'Sepsis_Group':       {9: ['99591','99592','78552'], 10: ['A40','A41','R6520','R6521']},
    'Cardio_Group':       {9: ['410','427','428'],       10: ['I21','I22','I48','I50']},
    'Kidney_Group':       {9: ['584','585','401'],       10: ['N17','N18','I10']},
    'Pancreatitis_Group': {9: ['577'],                   10: ['K85']},
    'Chemo_Group':        {9: ['V581'],                  10: ['Z511']},
    'Stroke_Group':       {9: ['433','434','436'],       10: ['I63','I61','I64']},
    'Respiratory_Group':  {9: ['518','486','491','493'], 10: ['J96','J18','J44','J45']},
    'GI_Bleeding_Group':  {9: ['578','531','532'],       10: ['K92','K25','K26']},
}
```

---

## 3. 데이터 추출 전략

### 3-1. 라벨링 기준 — 입원 전 첫 혈액검사

Steinbach et al. (2024) 논문 방법론 기반.
치료 개입 이전 수치를 사용해야 모델이 "치료 효과"가 아닌 "질환 자체"를 학습한다.

```
입원 전 마지막 검사값 사용
  admittime 이전 charttime 중 가장 최근 값
  (입원 직전 상태 = 치료 개입 전 상태)
```

```python
# 입원 전 검사만 필터링
pre_admit_labs = lab_with_admit[
    lab_with_admit['charttime'] < lab_with_admit['admittime']
]

# 환자별 항목별 마지막 값 (입원 직전)
first_pre_admit = (
    pre_admit_labs
    .sort_values('charttime')
    .groupby(['hadm_id', 'itemid'])
    .last()
    .reset_index()
)
```

### 3-2. 데이터 제외 기준 (Steinbach et al. 방법론)

| 제외 기준 | 이유 |
|----------|------|
| ICU 내부에서 채취된 검사 | 치료 개입 후 수치 혼재 |
| 후속 에피소드 CBC | 첫 번째 에피소드만 유효 |
| Surgical ICU 환자 | 수술 후 SIRS와 패혈증 혼동 방지 |
| SIRS 진단만 있고 패혈증 코드 없는 케이스 | 라벨 오염 방지 |
| 결측값 포함 CBC | 불완전한 데이터 |

```python
# Surgical ICU 제외 (Medical ICU만 사용)
VALID_ICU_TYPES = ['MICU', 'MICU/SICU']

# 첫 번째 ICU 에피소드만 사용
first_icu = icustays.sort_values('intime').groupby('hadm_id').first()

# SIRS-only 제외
SIRS_ONLY_ICD9 = ['99590']
```

### 3-3. ICD-9/ICD-10 혼재 처리

MIMIC-IV는 2008~2019년 데이터로 2015년 10월 ICD-9 → ICD-10 전환이 포함됨.
`diagnoses_icd` 테이블의 `icd_version` 컬럼으로 구분하여 양쪽 모두 처리.

```python
matched = diagnoses[
    diagnoses.apply(
        lambda r: any(
            str(r['icd_code']).startswith(c)
            for c in icd_map.get(int(r['icd_version']), [])
        ), axis=1
    )
]
```

---

## 4. 입력 피처 구성

### 4-1. Core Features (모델 학습 피처)

응급실에서 거의 모든 환자에게 기본으로 시행되는 CBC + 기본 생화학 검사.
결측률이 낮아 모델 학습에 직접 사용.

| MIMIC itemid | 피처명 | 검사 | 임상적 의미 |
|-------------|--------|------|------------|
| 51301 | wbc | CBC | 백혈구 — 감염/염증 |
| 51222 | hemoglobin | CBC | 헤모글로빈 — 빈혈/출혈 |
| 51265 | platelet | CBC | 혈소판 — 응고/패혈증 |
| 50912 | creatinine | 생화학 | 신장 기능 |
| 51006 | bun | 생화학 | 신장/GI출혈 감별 |
| 50983 | sodium | 생화학 | 전해질 |
| 50971 | potassium | 생화학 | 전해질/심장 |
| 50931 | glucose | 생화학 | 혈당/DKA |
| 50861 | ast | 생화학 | 간/췌장 |
| 50862 | albumin | 생화학 | 영양/중증도 |

공통 메타데이터:
- `age` — 나이 (patients.csv)
- `sex` — 성별 (patients.csv)

### 4-2. Extended Features (abnormal_flags 후처리용)

그룹 확정 시 보조 수치. 결측이 많아 모델 학습 피처에서 제외.
inference 단계에서 있으면 abnormal_flags에 추가.

| 피처 | 관련 그룹 | 임상적 의미 |
|------|----------|------------|
| amylase | Pancreatitis | 췌장염 진단 핵심 (3배 이상 상승) |
| lipase | Pancreatitis | 췌장염 진단 핵심 |
| calcium | Pancreatitis | 저칼슘혈증 합병증 |
| inr / pt | Stroke, GI_Bleeding | 응고 상태, 항응고 치료 여부 |
| troponin | Cardio | 심근경색 확정 |
| bnp | Cardio | 심부전 확정 |
| lactate | Sepsis | 패혈성 쇼크 확정 (≥2 mmol/L) |
| crp | Sepsis | 염증 마커 |

---

## 5. 모델 구조

### 5-1. 앙상블 구성

```python
from xgboost import XGBClassifier
from lightgbm import LGBMClassifier
from catboost import CatBoostClassifier
from sklearn.ensemble import VotingClassifier

ensemble = VotingClassifier(
    estimators=[
        ('xgb', XGBClassifier()),
        ('lgbm', LGBMClassifier()),
        ('cat', CatBoostClassifier()),
    ],
    voting='soft'  # 소프트 보팅 → 확률 분포 출력
)
```

### 5-2. 데이터 불균형 처리

현재 그룹별 환자 수 불균형이 심함 (Sepsis 52.9% vs Chemo 1.2%).
Stratified K-Fold는 비율 유지만 하고 불균형 자체를 해결하지 않음.

```python
from imblearn.ensemble import BalancedRandomForestClassifier
from imblearn.over_sampling import SMOTE

# 소수 클래스 SMOTE 증강
sm = SMOTE(
    sampling_strategy={
        'Pancreatitis_Group': 500,
        'Chemo_Group': 300,
        'Stroke_Group': 400,      # 데이터 확인 후 조정
        'GI_Bleeding_Group': 400,
    },
    random_state=42
)
X_res, y_res = sm.fit_resample(X_train, y_train)
```

### 5-3. 평가 지표

accuracy 대신 per-class AUROC + macro F1 사용.
불균형 데이터에서 accuracy는 의미 없음.

```python
from sklearn.metrics import classification_report, roc_auc_score

# Per-class AUROC
for i, cls in enumerate(le.classes_):
    auc = roc_auc_score((y_test == i).astype(int), proba[:, i])
    print(f"{cls}: AUROC = {auc:.3f}")

# Macro F1
print(classification_report(y_test, y_pred, target_names=le.classes_))
```

---

## 6. 임상 정상 범위 기준표

### 6-1. MIMIC-IV 기반 추출 (권장)

교과서 기준(건강한 성인 평균)이 아닌 MIMIC-IV 실제 데이터 기반 기준 사용.
학습 데이터와 기준표 출처를 일치시켜 abnormal_flags 신뢰도 확보.

```sql
-- 방법 1: d_labitems 테이블에서 직접 추출
SELECT itemid, label, ref_range_lower, ref_range_upper
FROM d_labitems
WHERE itemid IN (51301,51222,51265,50912,51006,50983,50971,50931,50861,50862);

-- 방법 2: 정상 환자(ICU 입원 없는) 분포에서 통계 추출
WITH normal_patients AS (
    SELECT DISTINCT hadm_id FROM admissions
    WHERE hadm_id NOT IN (SELECT hadm_id FROM icustays)
)
SELECT
    d.label, l.itemid,
    ROUND(PERCENTILE_CONT(0.025) WITHIN GROUP (ORDER BY l.valuenum), 2) AS ref_lower,
    ROUND(PERCENTILE_CONT(0.975) WITHIN GROUP (ORDER BY l.valuenum), 2) AS ref_upper
FROM labevents l
JOIN normal_patients n ON l.hadm_id = n.hadm_id
JOIN d_labitems d ON l.itemid = d.itemid
WHERE l.itemid IN (51301,51222,51265,50912,51006,50983,50971,50931,50861,50862)
  AND l.valuenum IS NOT NULL
GROUP BY d.label, l.itemid;
```

적용 우선순위:
1. `d_labitems.ref_range_lower/upper` 사용
2. NULL이면 정상 환자 percentile 방식으로 보완
3. 그래도 없으면 교과서 기준 fallback

### 6-2. 현재 하드코딩 기준표 (fallback)

```python
CLINICAL_THRESHOLDS = {
    # MIMIC-IV 실제 데이터 기반 (ICU 비입원 환자 2.5~97.5 percentile)
    'albumin':    {'low': 2.1,   'high': 4.6,   'critical_low': 1.5},
    'ast':        {'low': None,  'high': 342.0,  'critical_high': 500.0},
    'bun':        {'low': None,  'high': 80.0,   'critical_high': 120.0},
    'creatinine': {'low': None,  'high': 6.1,    'critical_high': 10.0},
    'glucose':    {'low': 71.0,  'high': 270.0,  'critical_low': 50.0,  'critical_high': 400.0},
    'hemoglobin': {'low': 7.0,   'high': 14.8,   'critical_low': 5.0},
    'platelet':   {'low': 23.0,  'high': 540.0,  'critical_low': 10.0},
    'potassium':  {'low': 3.2,   'high': 5.4,    'critical_low': 2.5,   'critical_high': 6.5},
    'sodium':     {'low': 129.0, 'high': 145.0,  'critical_low': 120.0, 'critical_high': 160.0},
    'wbc':        {'low': 1.2,   'high': 20.0,   'critical_high': 30.0},
}
```

---

## 7. 후처리 레이어 (abnormal_flags) -> 배포 시 inference.py에 들어가는 것

ML 모델 예측과 별개로, 입력 수치를 정상 범위 기준표와 단순 비교.
모델 재학습 없이 inference 단계에서 추가 가능.

```python
def flag_abnormals(patient_data: dict) -> dict:
    flags = {}
    for feat, val in patient_data.items():
        if feat not in CLINICAL_THRESHOLDS or val is None:
            continue
        t = CLINICAL_THRESHOLDS[feat]
        status = 'NORMAL'
        if t.get('critical_low') and val < t['critical_low']:
            status = 'CRITICAL_LOW'
        elif t.get('critical_high') and val > t['critical_high']:
            status = 'CRITICAL_HIGH'
        elif t.get('low') and val < t['low']:
            status = 'LOW'
        elif t.get('high') and val > t['high']:
            status = 'HIGH'
        if status != 'NORMAL':
            flags[feat] = {'value': val, 'status': status}
    return flags
```

---

## 8. 최종 출력 스펙

```python
def predict_diagnosis(patient_data: dict) -> dict:
    X = np.array([[patient_data[f] for f in FEATURE_ORDER]])

    # 1. ML 모델 추론
    proba = ensemble.predict_proba(X)[0]
    pred_idx = np.argmax(proba)

    # 2. 후처리: 이상 수치 플래그
    abnormal_flags = flag_abnormals(patient_data)

    return {
        'predicted_group': le.classes_[pred_idx],
        'probabilities': dict(zip(le.classes_, proba.tolist())),
        'abnormal_flags': abnormal_flags
    }
```

출력 예시:
```json
{
  "predicted_group": "Sepsis_Group",
  "probabilities": {
    "Sepsis_Group":       0.72,
    "Cardio_Group":       0.18,
    "Kidney_Group":       0.05,
    "Pancreatitis_Group": 0.02,
    "Chemo_Group":        0.01,
    "Stroke_Group":       0.01,
    "Respiratory_Group":  0.01,
    "GI_Bleeding_Group":  0.00
  },
  "abnormal_flags": {
    "wbc":        {"value": 18.5, "status": "HIGH"},
    "potassium":  {"value": 6.1,  "status": "CRITICAL_HIGH"},
    "creatinine": {"value": 2.8,  "status": "HIGH"},
    "albumin":    {"value": 2.1,  "status": "LOW"}
  }
}
```

---

## 9. Bedrock Agent 연동 방식

혈액 모달은 사실만 전달. 임상적 판단은 Agent가 수행.

```
혈액 모달 출력:
  Sepsis 72%, Cardio 18%
  potassium CRITICAL_HIGH, creatinine HIGH

Bedrock Agent 추론:
  "칼륨 위험 수준 + 심혈관 가능성 18%
   → 심정지 위험 배제 위해 ECG 호출"

ECG 결과 수신 후:
  "심방세동 확인 + 폐부종 의심
   → CXR 호출"

CXR 결과 수신 후:
  "폐부종 78% 확인
   → 최종: 패혈증 + 심방세동 + 고칼륨혈증
   → 긴급 조치 권고"
```



## 11. 고혈압 처리 전략

### 그룹 분류에서 고혈압 제외 이유

고혈압(ICD I10)은 응급실 입원 환자의 40~50%가 보유한 동반 질환이다.
주 진단이 아닌 배경 질환이므로 독립 그룹으로 분류하면 데이터 불균형이 심해진다.

```
기존 (I10 포함): Kidney_Group 22,291명 (49.9%) ← 절반이 고혈압 환자
수정 (I10 제외): Kidney_Group = 실제 신부전 환자만
```

### 고혈압 환자 분류 원칙

```
고혈압 단독          → 제외 (주 진단 불명확)
고혈압 + 심근경색    → Cardio_Group
고혈압 + 신부전      → Kidney_Group
고혈압 + 패혈증      → Sepsis_Group
```

첫 번째 매칭 그룹으로 라벨을 부여하므로, 고혈압 동반 환자는 주 진단 그룹으로 자동 분류된다.

### 고혈압 정보는 abnormal_flags로 전달

고혈압 자체는 그룹 분류에 사용하지 않지만, 고혈압으로 인한 수치 이상은 후처리 레이어에서 자동으로 감지된다.

```json
{
  "predicted_group": "Cardio_Group",
  "abnormal_flags": {
    "potassium":  {"value": 6.1, "status": "CRITICAL_HIGH"},
    "creatinine": {"value": 2.8, "status": "HIGH"},
    "sodium":     {"value": 148, "status": "HIGH"}
  }
}
```

Bedrock Agent가 이를 받아 고혈압성 장기 손상을 임상 판단에 반영:

```
"Cardio_Group + potassium CRITICAL_HIGH + creatinine HIGH
 → 심근경색 + 고혈압성 신장 손상 동반
 → 신장내과 협진 + 전해질 모니터링 권고"
```

그룹 라벨 = 주 진단, abnormal_flags = 동반 질환 영향 수치로 역할이 분리된다.

---

## 12. 데이터 전처리 파이프라인

### 전처리 흐름

```
labevents (3,581만 행)
    ↓ hadm_id NaN 제거 (외래 환자 제외)
    ↓ admissions와 조인 (입원 시간 붙이기)
    ↓ admittime 이전 검사만 필터 (입원 전 검사)
    ↓ 환자별 항목별 마지막 값 추출
    ↓ 피벗 (환자 1행 = 10개 수치 컬럼)
    ↓ 진단 코드로 그룹 라벨 붙이기
final_df (33,896명 × 11컬럼)
```

### 외래 환자 제외 이유

`hadm_id`(입원 ID)가 NaN인 행은 외래 검사로, 입원과 연결되지 않는다.
진단 코드(`diagnoses_icd`)는 `hadm_id` 기준으로 연결되므로 외래 환자는 그룹 라벨을 붙일 수 없다.
또한 이 시스템의 목적이 응급 입원 환자의 질환 그룹 예측이므로 외래 환자는 학습 노이즈가 된다.

### 입원 전 검사 기준

Steinbach et al. (2024) 방법론 기반. 치료 개입 이전 수치를 사용해야 모델이 질환 자체를 학습한다.

```python
# 입원 전 검사만 필터 (admittime 이전)
pre_admit = lab[lab['charttime'] < lab['admittime']].copy()

# 환자별 항목별 입원 직전 가장 최근 값
last_pre = (
    pre_admit
    .sort_values('charttime')
    .groupby(['hadm_id', 'feature'])['valuenum']
    .last()
    .reset_index()
)
```

### MIMIC-IV itemid → 피처명 매핑

```python
ITEM_NAME = {
    51301: 'wbc',        # 백혈구
    51222: 'hemoglobin', # 헤모글로빈
    51265: 'platelet',   # 혈소판
    50912: 'creatinine', # 크레아티닌
    51006: 'bun',        # 요소질소
    50983: 'sodium',     # 나트륨
    50971: 'potassium',  # 칼륨
    50931: 'glucose',    # 혈당
    50861: 'ast',        # 간수치
    50862: 'albumin',    # 알부민
}
```

### 결측률 (입원 전 검사 기준)

```
wbc          1.2%  ← 기본 CBC
hemoglobin   1.3%
platelet     1.4%
creatinine   1.8%
bun          1.3%
sodium       3.5%
potassium    3.6%
glucose      3.8%
ast         54.5%  ← 선택적 검사 (간 의심 시에만)
albumin     59.7%  ← 선택적 검사 (영양 평가 시에만)
```

ast, albumin은 결측이 많아 모델 학습 시 median imputation 적용.

### 최종 데이터셋

```
총 환자: 33,896명
컬럼: hadm_id + 10개 수치 + group (11컬럼)

그룹별 분포:
Cardio_Group        14,457명  (42.7%)
Kidney_Group         7,435명  (21.9%)
Respiratory_Group    6,210명  (18.3%)
Sepsis_Group         3,199명  ( 9.4%)
Stroke_Group           968명  ( 2.9%)
Pancreatitis_Group     966명  ( 2.9%)
GI_Bleeding_Group      661명  ( 1.9%)
```

---

## 13. 전처리 전체 코드

```python
import pandas as pd
import time

base = 's3://say1-pre-project-2/mimic-iv/'

# Step 1: labevents 필터링 (10개 itemid)
TARGET_ITEMS = [51301,51222,51265,50912,51006,50983,50971,50931,50861,50862]

chunks = []
for chunk in pd.read_csv(
    base + 'hosp/labevents.csv.gz',
    usecols=['hadm_id', 'itemid', 'charttime', 'valuenum'],
    parse_dates=['charttime'],
    chunksize=500_000
):
    chunks.append(chunk[chunk['itemid'].isin(TARGET_ITEMS)])

labevents = pd.concat(chunks)
labevents.to_parquet('/tmp/labevents_filtered.parquet', index=False)

# Step 2: admissions, diagnoses 로드
admissions = pd.read_csv(base + 'hosp/admissions.csv.gz',
                         usecols=['hadm_id', 'admittime'], parse_dates=['admittime'])
diagnoses  = pd.read_csv(base + 'hosp/diagnoses_icd.csv.gz',
TARGET_ITEMS = [
    51301, 51222, 51265, 50912, 51006, 50983, 50971, 50931, 50861, 50862,  # 기본 10개
]

# Step 3: 외래 환자 제거 + 입원 전 검사 필터
labevents = labevents.dropna(subset=['hadm_id'])
labevents['hadm_id'] = labevents['hadm_id'].astype(int)
lab = labevents.merge(admissions, on='hadm_id', how='inner')
pre_admit = lab[lab['charttime'] < lab['admittime']].copy()

# Step 4: itemid → 피처명 매핑 + 피벗
ITEM_NAME = {
    51301:'wbc', 51222:'hemoglobin', 51265:'platelet',
    50912:'creatinine', 51006:'bun', 50983:'sodium',
    50971:'potassium', 50931:'glucose', 50861:'ast', 50862:'albumin'
}
pre_admit['feature'] = pre_admit['itemid'].map(ITEM_NAME)
last_pre = (pre_admit.sort_values('charttime')
            .groupby(['hadm_id','feature'])['valuenum'].last().reset_index())
lab_pivot = last_pre.pivot_table(index='hadm_id', columns='feature', values='valuenum').reset_index()

# Step 5: 진단 그룹 라벨
GROUP_ICD = {
    'Sepsis_Group':       {9:['99591','99592','78552'], 10:['A40','A41','R6520','R6521']},
    'Cardio_Group':       {9:['410','427','428'],       10:['I21','I22','I48','I50']},
    'Kidney_Group':       {9:['584','585'],             10:['N17','N18']},
ITEM_NAME = {
    51301:'wbc', 51222:'hemoglobin', 51265:'platelet',
    50912:'creatinine', 51006:'bun', 50983:'sodium',
    50971:'potassium', 50931:'glucose', 50861:'ast', 50862:'albumin',
}

diag_group = {}
for group, icd_map in GROUP_ICD.items():
    matched = diagnoses[diagnoses.apply(
        lambda r: any(str(r['icd_code']).startswith(c)
                     for c in icd_map.get(int(r['icd_version']),[])), axis=1
    )]['hadm_id'].unique()
    for hid in matched:
        if hid not in diag_group:
            diag_group[hid] = group

lab_pivot['group'] = lab_pivot['hadm_id'].map(diag_group)
final_df = lab_pivot.dropna(subset=['group'])
# 결과: 33,896명 × 11컬럼
```

---

## 14. 학습 전체 코드

```python
from sklearn.preprocessing import LabelEncoder
from sklearn.impute import SimpleImputer
from sklearn.model_selection import train_test_split
from imblearn.over_sampling import SMOTE
from xgboost import XGBClassifier
from lightgbm import LGBMClassifier
from catboost import CatBoostClassifier
from sklearn.ensemble import VotingClassifier
from sklearn.metrics import classification_report, roc_auc_score
import joblib

FEATURE_COLS = ['wbc','hemoglobin','platelet','creatinine','bun',
                'sodium','potassium','glucose','ast','albumin']

# 1. 라벨 인코딩
le = LabelEncoder()
y = le.fit_transform(final_df['group'])
X = final_df[FEATURE_COLS].values

# 2. train/test 분리 (80/20, stratify)
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, stratify=y, random_state=42)

# 3. 결측 imputation (train median)
imputer = SimpleImputer(strategy='median')
FEATURE_COLS = ['wbc','hemoglobin','platelet','creatinine','bun',
                'sodium','potassium','glucose','ast','albumin']

# troponin_t(결측 83.9%), BNP(결측 83.8%) → 학습 피처 제외
# inference 시 값이 있는 환자만 CLINICAL_THRESHOLDS 기반 abnormal_flags에 추가
                'troponin_t','bnp']  # troponin_t, BNP 추가

# 4. SMOTE (train만, 7개 그룹 → 각 11,565명)
sm = SMOTE(random_state=42)
X_train_res, y_train_res = sm.fit_resample(X_train, y_train)

# 5. 앙상블 학습
ensemble = VotingClassifier(
    estimators=[
        ('xgb',  XGBClassifier(n_estimators=200, eval_metric='mlogloss', random_state=42)),
        ('lgbm', LGBMClassifier(n_estimators=200, random_state=42, verbose=-1)),
        ('cat',  CatBoostClassifier(n_estimators=200, random_state=42, verbose=0)),
    ],
    voting='soft'
)
ensemble.fit(X_train_res, y_train_res)

# 6. 평가
y_pred  = ensemble.predict(X_test)
y_proba = ensemble.predict_proba(X_test)
print(classification_report(y_test, y_pred, target_names=le.classes_))
for i, cls in enumerate(le.classes_):
    auc = roc_auc_score((y_test == i).astype(int), y_proba[:, i])
    print(f"  {cls}: AUROC {auc:.3f}")

# 7. 모델 저장
joblib.dump(ensemble, '/tmp/blood_ensemble_model.joblib')
joblib.dump(le,       '/tmp/label_encoder.joblib')
joblib.dump(imputer,  '/tmp/imputer.joblib')
```

---

## 15. 최종 성능 결과

```
Per-class AUROC:
  Pancreatitis_Group  0.880  ✅
  Respiratory_Group   0.814  ✅
  GI_Bleeding_Group   0.800  ✅
  Kidney_Group        0.793  ✅
  Stroke_Group        0.786  ✅
  Sepsis_Group        0.780  ✅
  Cardio_Group        0.645  ⚠️ troponin/BNP 미포함으로 낮음

Accuracy: 0.47 (AUROC 대비 낮은 이유: 확률값 전달 목적이라 F1보다 AUROC가 주요 지표)
```

---

## 16. 최종 성능 결과 분석

### 16-1. 용어 정의

| 지표 | 의미 | 예시 |
|------|------|------|
| Precision (정밀도) | 모델이 "이 그룹"이라고 예측했을 때 실제로 맞는 비율 | Cardio 0.52 → 예측 100건 중 52건만 실제 Cardio |
| Recall (재현율) | 실제 그룹 환자 중 모델이 맞게 잡아낸 비율 | Cardio 0.61 → 실제 Cardio 100명 중 61명 감지 |
| F1-score | Precision과 Recall의 조화 평균 | 둘 다 높아야 F1이 높음 |
| AUROC | 확률 분포 기준 판별력 (0.5=랜덤, 1.0=완벽) | 이 시스템의 주요 지표 |
| Support | 테스트셋 실제 환자 수 | GI_Bleeding 132명 |

### 16-2. Classification Report

```
그룹                Precision  Recall  F1    Support
Cardio_Group          0.52     0.61   0.56    2,892
GI_Bleeding_Group     0.15     0.08   0.11      132
Kidney_Group          0.48     0.43   0.46    1,487
Pancreatitis_Group    0.28     0.24   0.26      193
Respiratory_Group     0.46     0.44   0.45    1,242
Sepsis_Group          0.33     0.28   0.30      640
Stroke_Group          0.20     0.08   0.11      194

Accuracy: 0.47
Macro avg F1: 0.32
```

### 16-3. Per-class AUROC

```
Pancreatitis_Group   0.880  ✅ 우수
Respiratory_Group    0.814  ✅ 양호
GI_Bleeding_Group    0.800  ✅ 양호
Kidney_Group         0.793  ✅ 양호
Stroke_Group         0.786  ✅ 양호
Sepsis_Group         0.780  ✅ 양호
Cardio_Group         0.645  ⚠️ 낮음
```

### 16-4. F1이 낮은 이유

AUROC는 높은데 F1이 낮은 이유:
- AUROC는 확률 분포 기준 (확률값 0.0~1.0 전체 범위 평가)
- F1은 최종 분류 기준 (0 or 1로 결정한 결과 평가)
- 이 모델은 확률값을 Bedrock Agent에 전달하는 용도 → AUROC가 주요 지표

GI_Bleeding, Stroke F1이 특히 낮은 이유:
- 테스트셋 환자 수가 132명, 194명으로 너무 적음
- SMOTE 합성 데이터로 학습했지만 실제 데이터 패턴과 차이 존재
- 혈액 수치만으로 뇌졸중/GI출혈 감별이 임상적으로도 어려움

### 16-5. Cardio_Group AUROC 0.645 원인 및 대응

원인:
- 심근경색/심부전 확정 바이오마커인 troponin, BNP가 학습 피처에 없음
- troponin/BNP 결측률 83~84%로 학습 피처 제외 결정
- WBC, creatinine 등 일반 수치로는 Cardio와 다른 그룹 구분이 어려움

대응 전략:
```
Cardio 0.645 → Bedrock Agent가 ECG 모달 호출해서 확정
  혈액: "Cardio 가능성 있음 (0.645)"
  ECG:  "심방세동 0.87, 심부전 0.72" → 확정
```

혈액 모달이 완벽할 필요 없는 이유:
- 혈액 모달 단독으로 확정하는 게 아님
- Bedrock Agent가 ECG/CXR과 조합해서 최종 판단
- Cardio 0.645도 "심장 가능성 있음"을 Agent에게 전달하는 용도로 충분

### 16-6. 모델 저장 경로

```
s3://say2-6team/mimic/blood/blood_ensemble_model.joblib  ← XGB+LGBM+CatBoost 앙상블
s3://say2-6team/mimic/blood/label_encoder.joblib         ← 그룹명 ↔ 숫자 변환
s3://say2-6team/mimic/blood/imputer.joblib               ← train median 기준표
```

---

## 17. 성능 평가 논의 (회의 자료)

### 17-1. F1 0.32는 낮은가?

낮은 건 맞지만 이 시스템 목적상 허용 가능한 수준이다.

**F1이 낮은 구조적 이유**

7개 그룹 멀티클래스 분류 자체가 어려운 문제다. 혈액 수치만으로 7개 질환을 구분하는 건 임상적으로도 쉽지 않다. 실제 의사도 혈액만 보고 "이 환자는 GI_Bleeding"이라고 확정하지 못한다.

추가로 현재 라벨링 방식의 한계:
```
환자가 Cardio + Sepsis 동시에 있으면 첫 번째 매칭 그룹으로 강제 분류
→ 실제 복합 질환 환자가 노이즈로 작용
→ F1 하락의 주요 원인
```

**AUROC vs F1 — 어떤 지표가 중요한가**

| 지표 | 기준 | 이 시스템에서 중요도 |
|------|------|:------------------:|
| AUROC | 확률 분포 판별력 | ✅ 주요 지표 |
| F1 | 최종 분류 정확도 | 참고 지표 |

이 모델은 확률값(probabilities)을 Bedrock Agent에 전달하는 용도다. Agent가 "Cardio 0.52, Sepsis 0.28" 같은 확률 분포를 받아 판단하므로 AUROC가 더 중요하다.

### 17-2. 앙상블(XGB+LGBM+CatBoost)이 최선인가?

**MIMIC 기반 혈액 분류 논문 동향**

관련 논문들(MIMIC-IV 기반 혈액 수치 분류)에서 가장 많이 사용된 모델:
- XGBoost 단독 — 가장 많이 사용, AUROC 0.87~0.90 (이진 분류 기준)
- LightGBM — XGBoost와 유사 성능
- Random Forest — 해석 가능성 높음

단, 논문들은 대부분 이진 분류(질환 있음/없음)라 7개 그룹 멀티클래스와 직접 비교 어렵다.

**현재 앙상블의 한계**

```
XGB + LGBM + CatBoost Soft Voting
→ 세 모델이 비슷한 특성을 가져 다양성 부족
→ 앙상블 효과가 제한적
```

**개선 가능한 방향**

방향 1 — 멀티라벨 분류로 전환 (ECG 모달과 동일한 방식)
```
현재: 7개 중 하나 선택 (멀티클래스)
개선: 7개 각각 있다/없다 (멀티라벨)
효과: 복합 질환 환자 처리 가능, per-group AUROC로 평가
```

방향 2 — 현재 구조 유지 + 평가 지표 변경
```
F1 대신 per-group AUROC를 주요 지표로 사용
현재 AUROC 0.78~0.88은 충분히 좋은 수준
```

### 17-3. 결론 — 현재 결과로 진행 가능한 이유

1. AUROC 0.78~0.88은 혈액 수치 10개만으로 달성한 결과로 양호
2. 혈액 모달이 "확정"하는 게 아니라 "가능성 전달" 역할
3. Bedrock Agent가 ECG/CXR과 조합해서 최종 판단
4. Cardio AUROC 0.645도 "심장 가능성 있음"을 Agent에 전달하는 용도로 충분
5. troponin/BNP 추가 시 Cardio AUROC 개선 가능 (현재 결측 83%로 제외)

**회의 논의 포인트**
- 멀티라벨 전환 여부 결정
- Cardio_Group 개선을 위한 troponin/BNP 데이터 확보 방안
- F1 vs AUROC 중 팀 내 주요 지표 합의
