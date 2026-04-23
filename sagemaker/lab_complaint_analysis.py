"""
=============================================================================
MIMIC-IV ED 데이터 기반 — 주호소별 혈액검사 이상 수치 분석
=============================================================================

목적:
  1. 주호소(Chief Complaint)를 7개 Complaint Profile로 매핑
  2. Profile별로 어떤 혈액검사 수치가 이상(정상 범위 이탈)인지 통계 산출
  3. Profile별 우선 확인 검사 순서를 데이터 기반으로 도출
  4. ICD 진단 코드와 대조하여 Sensitivity / Specificity / PPV 검증

사용법:
  SageMaker Notebook에서 셀 단위로 실행하거나 전체 실행

데이터 경로:
  S3 또는 로컬 MIMIC-IV 경로를 BASE_PATH에 설정
=============================================================================
"""

import pandas as pd
import numpy as np
import re
import warnings
from collections import defaultdict

warnings.filterwarnings('ignore')

# ============================================================================
# 0. 설정
# ============================================================================

# MIMIC-IV 데이터 경로
ED_PATH   = 's3://say2-6team/mimic/ed/'              # ED 모듈 (triage, edstays)
HOSP_PATH = 's3://say1-pre-project-2/mimic-iv/hosp/'  # hosp 모듈 (labevents, diagnoses 등)

# 분석 대상 혈액검사 itemid (15개)
TARGET_ITEMS = {
    # Tier 1 — 기본 CBC + 생화학 (결측률 < 10%)
    51301: 'wbc',           # 백혈구
    51222: 'hemoglobin',    # 혈색소
    51265: 'platelet',      # 혈소판
    50912: 'creatinine',    # 크레아티닌
    51006: 'bun',           # 혈중요소질소
    50983: 'sodium',        # 나트륨
    50971: 'potassium',     # 칼륨
    50931: 'glucose',       # 혈당
    # Tier 2 — 선택적 검사 (결측률 50~65%)
    50861: 'ast',           # 간효소
    50862: 'albumin',       # 알부민
    50813: 'lactate',       # 젖산
    50893: 'calcium',       # 칼슘 (Total Calcium)
    # Tier 3 — 고결측 검사 (결측률 > 80%)
    51003: 'troponin_t',    # 트로포닌 T
    50963: 'bnp',           # BNP
    51265: 'platelet',      # (중복 방지용 — 이미 위에 있음)
}

# 중복 제거
TARGET_ITEM_IDS = list(set(TARGET_ITEMS.keys()))

# 임상 정상 범위
NORMAL_RANGES = {
    'wbc':        {'low': 4.5,  'high': 11.0},
    'hemoglobin': {'low': 12.0, 'high': 17.5},
    'platelet':   {'low': 150,  'high': 400},
    'creatinine': {'low': 0.7,  'high': 1.2},
    'bun':        {'low': 7,    'high': 20},
    'sodium':     {'low': 136,  'high': 145},
    'potassium':  {'low': 3.5,  'high': 5.0},
    'glucose':    {'low': 70,   'high': 100},
    'ast':        {'low': 0,    'high': 40},
    'albumin':    {'low': 3.5,  'high': 5.5},
    'lactate':    {'low': 0.5,  'high': 2.0},
    'calcium':    {'low': 8.5,  'high': 10.5},
    'troponin_t': {'low': 0,    'high': 0.014},
    'bnp':        {'low': 0,    'high': 100},
}


# ============================================================================
# 1. 의료 약어 사전 + Complaint Profile 매핑
# ============================================================================

ABBREVIATION_DICT = {
    'cp': 'chest pain', 'sob': 'shortness of breath', 'ams': 'altered mental status',
    'loc': 'loss of consciousness', 'n/v': 'nausea and vomiting', 'ha': 'headache',
    'abd': 'abdominal', 'htn': 'hypertension', 'dm': 'diabetes mellitus',
    'chf': 'congestive heart failure', 'gi': 'gastrointestinal',
    'uri': 'upper respiratory infection', 'uti': 'urinary tract infection',
    'dvt': 'deep vein thrombosis', 'pe': 'pulmonary embolism',
    'mi': 'myocardial infarction', 'cva': 'cerebrovascular accident',
    'tia': 'transient ischemic attack', 'etoh': 'alcohol',
    'sz': 'seizure', 'hx': 'history', 'dx': 'diagnosis',
    'r/o': 'rule out', 'w/': 'with', 'w/o': 'without',
    'brbpr': 'bright red blood per rectum', 'doi': 'date of injury',
    'fb': 'foreign body', 'fx': 'fracture', 'lac': 'laceration',
    'lle': 'left lower extremity', 'rle': 'right lower extremity',
}

# 위험도 순서 (높은 것부터)
PROFILE_PRIORITY = ['CARDIAC', 'SEPSIS', 'RESPIRATORY', 'RENAL', 'GI', 'NEUROLOGICAL', 'GENERAL']

PROFILE_KEYWORDS = {
    'CARDIAC': [
        'chest pain', 'angina', 'palpitation', 'palpitations', 'cardiac',
        'heart', 'myocardial', 'syncope', 'fainting', 'dyspnea on exertion',
        'congestive heart failure', 'arrhythmia', 'tachycardia', 'bradycardia',
        'atrial fibrillation', 'afib', 'stemi', 'nstemi', 'aortic',
    ],
    'SEPSIS': [
        'fever', 'chills', 'infection', 'sepsis', 'septic',
        'rigors', 'febrile', 'bacteremia', 'cellulitis', 'abscess',
        'wound infection', 'pneumonia', 'pyelonephritis',
    ],
    'RESPIRATORY': [
        'shortness of breath', 'dyspnea', 'cough', 'wheezing',
        'respiratory', 'asthma', 'copd', 'pulmonary', 'oxygen',
        'hypoxia', 'hemoptysis', 'pleuritic', 'bronchitis',
    ],
    'RENAL': [
        'flank pain', 'oliguria', 'anuria', 'hematuria', 'renal',
        'kidney', 'dialysis', 'urinary retention', 'edema',
        'swelling legs', 'decreased urine',
    ],
    'GI': [
        'abdominal pain', 'nausea', 'vomiting', 'diarrhea', 'melena',
        'hematemesis', 'rectal bleeding', 'bright red blood per rectum',
        'constipation', 'gastrointestinal', 'epigastric', 'pancreatitis',
        'jaundice', 'liver', 'hepatitis', 'gallbladder', 'biliary',
    ],
    'NEUROLOGICAL': [
        'headache', 'seizure', 'altered mental status', 'confusion',
        'dizziness', 'vertigo', 'weakness', 'numbness', 'tingling',
        'stroke', 'cerebrovascular', 'transient ischemic',
        'loss of consciousness', 'unresponsive', 'facial droop',
    ],
    # GENERAL은 키워드 매칭 없이 기본값
}


def expand_abbreviations(text) -> str:
    """의료 약어를 정식 명칭으로 확장"""
    if not text or not isinstance(text, str):
        return ''
    text_lower = text.lower().strip()
    for abbr, full in ABBREVIATION_DICT.items():
        # 단어 경계 기준 치환 (부분 매칭 방지)
        pattern = r'\b' + re.escape(abbr) + r'\b'
        text_lower = re.sub(pattern, full, text_lower, flags=re.IGNORECASE)
    return text_lower


def map_to_profile(chief_complaint: str) -> str:
    """주호소 텍스트를 7개 Complaint Profile 중 하나로 매핑"""
    expanded = expand_abbreviations(chief_complaint)
    if not expanded:
        return 'GENERAL'

    matched_profiles = []
    for profile in PROFILE_PRIORITY:
        if profile == 'GENERAL':
            continue
        keywords = PROFILE_KEYWORDS.get(profile, [])
        for kw in keywords:
            if kw in expanded:
                matched_profiles.append(profile)
                break

    if not matched_profiles:
        return 'GENERAL'

    # 위험도 순서에서 가장 높은 것 반환
    for p in PROFILE_PRIORITY:
        if p in matched_profiles:
            return p
    return 'GENERAL'


print("✅ 약어 사전 + Profile 매핑 함수 정의 완료")
print(f"   약어 사전: {len(ABBREVIATION_DICT)}개")
print(f"   Profile: {PROFILE_PRIORITY}")


# ============================================================================
# 2. MIMIC-IV 데이터 로드
# ============================================================================

print("\n" + "="*60)
print("Step 1: MIMIC-IV 데이터 로드")
print("="*60)

# 2-1. ED triage (주호소)
print("\n📂 ed/triage.csv 로드 중...")
triage = pd.read_csv(
    ED_PATH + 'mimic_ed_triage_000000000000.csv.gz',
    usecols=['stay_id', 'chiefcomplaint'],
)
print(f"   triage: {len(triage):,}행")

# 2-2. ED stays (ED → 입원 연결)
print("📂 ed/edstays.csv 로드 중...")
edstays = pd.read_csv(
    ED_PATH + 'mimic_ed_edstays_000000000000.csv.gz',
    usecols=['stay_id', 'hadm_id', 'subject_id', 'intime'],
    parse_dates=['intime'],
)
print(f"   edstays: {len(edstays):,}행")

# 2-3. labevents (혈액검사 수치) — 청크 단위 로드
print("📂 hosp/labevents.csv 로드 중 (대용량, 청크 처리)...")
lab_chunks = []
chunk_count = 0
for chunk in pd.read_csv(
    HOSP_PATH + 'labevents.csv.gz',
    usecols=['hadm_id', 'itemid', 'charttime', 'valuenum'],
    parse_dates=['charttime'],
    chunksize=1_000_000,
):
    filtered = chunk[chunk['itemid'].isin(TARGET_ITEM_IDS)]
    if len(filtered) > 0:
        lab_chunks.append(filtered)
    chunk_count += 1
    if chunk_count % 10 == 0:
        print(f"   ... {chunk_count}M 행 처리 완료")

labevents = pd.concat(lab_chunks, ignore_index=True)
print(f"   labevents (필터링 후): {len(labevents):,}행")

# 2-4. diagnoses_icd (진단 코드 — Ground Truth)
print("📂 hosp/diagnoses_icd.csv 로드 중...")
diagnoses = pd.read_csv(
    HOSP_PATH + 'diagnoses_icd.csv.gz',
    usecols=['hadm_id', 'icd_code', 'icd_version', 'seq_num'],
)
print(f"   diagnoses: {len(diagnoses):,}행")

# 2-5. patients (나이, 성별)
print("📂 hosp/patients.csv 로드 중...")
patients = pd.read_csv(
    HOSP_PATH + 'patients.csv.gz',
    usecols=['subject_id', 'gender', 'anchor_age'],
)
print(f"   patients: {len(patients):,}행")

print("\n✅ 데이터 로드 완료!")


# ============================================================================
# 3. 데이터 조인 및 필터링
# ============================================================================

print("\n" + "="*60)
print("Step 2: 데이터 조인 및 필터링")
print("="*60)

# 3-1. triage + edstays 조인 (stay_id 기준)
ed_df = triage.merge(edstays, on='stay_id', how='inner')
print(f"\n   triage + edstays 조인: {len(ed_df):,}행")

# 3-2. ED 경유 입원 환자만 필터링 (hadm_id 존재)
ed_admitted = ed_df.dropna(subset=['hadm_id']).copy()
ed_admitted['hadm_id'] = ed_admitted['hadm_id'].astype(int)
print(f"   ED 경유 입원 환자: {len(ed_admitted):,}행")

# 3-3. 주호소 → Profile 매핑
ed_admitted['complaint_profile'] = ed_admitted['chiefcomplaint'].apply(map_to_profile)
print(f"\n   Profile 분포:")
profile_counts = ed_admitted['complaint_profile'].value_counts()
for profile, count in profile_counts.items():
    pct = count / len(ed_admitted) * 100
    print(f"     {profile:15s}: {count:>7,}명 ({pct:.1f}%)")

# 3-4. labevents 조인 (hadm_id 기준)
labevents_clean = labevents.dropna(subset=['hadm_id', 'valuenum']).copy()
labevents_clean['hadm_id'] = labevents_clean['hadm_id'].astype(int)

# itemid → feature name 매핑
labevents_clean['feature'] = labevents_clean['itemid'].map(TARGET_ITEMS)
labevents_clean = labevents_clean.dropna(subset=['feature'])

# ED 입원 환자의 혈액검사만 필터링
lab_ed = labevents_clean.merge(
    ed_admitted[['hadm_id', 'stay_id', 'complaint_profile', 'intime']],
    on='hadm_id',
    how='inner',
)
print(f"\n   ED 입원 환자 혈액검사: {len(lab_ed):,}행")

# 3-5. ED 도착 후 0~6시간 내 검사만 필터링 (초기 검사)
lab_ed['hours_from_ed'] = (lab_ed['charttime'] - lab_ed['intime']).dt.total_seconds() / 3600
lab_initial = lab_ed[(lab_ed['hours_from_ed'] >= 0) & (lab_ed['hours_from_ed'] <= 6)].copy()
print(f"   ED 도착 후 0~6h 내 검사: {len(lab_initial):,}행")

# 3-6. 환자별 항목별 첫 번째 값 (가장 이른 검사)
lab_first = (
    lab_initial
    .sort_values('charttime')
    .groupby(['hadm_id', 'feature'])
    .first()
    .reset_index()
)
print(f"   환자별 항목별 첫 값: {len(lab_first):,}행")

# 3-7. 피벗 (환자 1행 = 수치 컬럼들)
lab_pivot = lab_first.pivot_table(
    index='hadm_id',
    columns='feature',
    values='valuenum',
).reset_index()

# Profile 정보 붙이기
hadm_profile = ed_admitted[['hadm_id', 'complaint_profile']].drop_duplicates(subset='hadm_id')
analysis_df = lab_pivot.merge(hadm_profile, on='hadm_id', how='inner')

print(f"\n   최종 분석 데이터셋: {len(analysis_df):,}명")
print(f"   컬럼: {list(analysis_df.columns)}")


# ============================================================================
# 4. Profile별 결측률 분석
# ============================================================================

print("\n" + "="*60)
print("Step 3: Profile별 결측률 분석")
print("="*60)

features_to_check = [f for f in NORMAL_RANGES.keys() if f in analysis_df.columns]

print("\n📊 전체 결측률:")
for feat in features_to_check:
    missing_pct = analysis_df[feat].isna().mean() * 100
    tier = "Tier1" if missing_pct < 10 else ("Tier2" if missing_pct < 70 else "Tier3")
    print(f"   {feat:15s}: {missing_pct:5.1f}% 결측  [{tier}]")

print("\n📊 Profile별 측정률 (= 1 - 결측률):")
for profile in PROFILE_PRIORITY:
    subset = analysis_df[analysis_df['complaint_profile'] == profile]
    if len(subset) == 0:
        continue
    print(f"\n  [{profile}] (n={len(subset):,})")
    for feat in features_to_check:
        measured_pct = subset[feat].notna().mean() * 100
        print(f"    {feat:15s}: {measured_pct:5.1f}% 측정됨")


# ============================================================================
# 5. Profile별 이상률 분석 (핵심!)
# ============================================================================

print("\n" + "="*60)
print("Step 4: Profile별 이상률 분석 — 주호소별 어떤 수치가 안 좋은가?")
print("="*60)


def calc_abnormal_rate(series: pd.Series, feat_name: str) -> dict:
    """수치 시리즈에서 정상 범위 이탈 비율 계산"""
    valid = series.dropna()
    if len(valid) == 0:
        return {'n': 0, 'abnormal_pct': 0, 'high_pct': 0, 'low_pct': 0,
                'mean': None, 'median': None}

    ranges = NORMAL_RANGES.get(feat_name, {})
    low_thresh = ranges.get('low', float('-inf'))
    high_thresh = ranges.get('high', float('inf'))

    is_high = valid > high_thresh
    is_low = valid < low_thresh
    is_abnormal = is_high | is_low

    return {
        'n': len(valid),
        'abnormal_pct': round(is_abnormal.mean() * 100, 1),
        'high_pct': round(is_high.mean() * 100, 1),
        'low_pct': round(is_low.mean() * 100, 1),
        'mean': round(valid.mean(), 2),
        'median': round(valid.median(), 2),
    }


# Profile별 이상률 계산
results = {}
for profile in PROFILE_PRIORITY:
    subset = analysis_df[analysis_df['complaint_profile'] == profile]
    if len(subset) == 0:
        continue

    profile_results = {}
    for feat in features_to_check:
        stats = calc_abnormal_rate(subset[feat], feat)
        profile_results[feat] = stats

    results[profile] = {
        'n_patients': len(subset),
        'features': profile_results,
    }

# 결과 출력
for profile in PROFILE_PRIORITY:
    if profile not in results:
        continue
    r = results[profile]
    print(f"\n{'='*60}")
    print(f"  [{profile}] — {r['n_patients']:,}명")
    print(f"{'='*60}")
    print(f"  {'Feature':15s} | {'N':>6s} | {'이상%':>6s} | {'↑높음%':>6s} | {'↓낮음%':>6s} | {'평균':>8s} | {'중앙값':>8s}")
    print(f"  {'-'*15}-+-{'-'*6}-+-{'-'*6}-+-{'-'*6}-+-{'-'*6}-+-{'-'*8}-+-{'-'*8}")

    # 이상률 높은 순으로 정렬
    sorted_feats = sorted(
        r['features'].items(),
        key=lambda x: x[1]['abnormal_pct'],
        reverse=True,
    )
    for feat, stats in sorted_feats:
        if stats['n'] == 0:
            continue
        print(f"  {feat:15s} | {stats['n']:>6,} | {stats['abnormal_pct']:>5.1f}% | "
              f"{stats['high_pct']:>5.1f}% | {stats['low_pct']:>5.1f}% | "
              f"{stats['mean']:>8.2f} | {stats['median']:>8.2f}")


# ============================================================================
# 6. 우선 확인 검사 순서 도출 (이상률 높은 순)
# ============================================================================

print("\n" + "="*60)
print("Step 5: Profile별 우선 확인 검사 순서 (데이터 기반)")
print("="*60)

# 중간보고서 기반 설계 순서 (비교용)
DESIGNED_ORDER = {
    'CARDIAC':       ['troponin_t', 'bnp', 'potassium', 'glucose', 'creatinine'],
    'SEPSIS':        ['lactate', 'wbc', 'platelet', 'creatinine'],
    'GI':            ['ast', 'hemoglobin', 'bun', 'calcium'],  # amylase는 별도 itemid
    'RENAL':         ['creatinine', 'bun', 'potassium', 'sodium', 'calcium'],
    'RESPIRATORY':   ['wbc', 'lactate', 'hemoglobin'],
    'NEUROLOGICAL':  ['glucose', 'sodium', 'calcium', 'potassium', 'wbc'],
    'GENERAL':       ['wbc', 'hemoglobin', 'creatinine', 'glucose'],
}

for profile in PROFILE_PRIORITY:
    if profile not in results:
        continue
    r = results[profile]

    # 이상률 높은 순 정렬 (측정된 항목만)
    data_order = sorted(
        [(feat, stats['abnormal_pct']) for feat, stats in r['features'].items() if stats['n'] > 0],
        key=lambda x: x[1],
        reverse=True,
    )

    designed = DESIGNED_ORDER.get(profile, [])

    print(f"\n  [{profile}]")
    print(f"    데이터 기반 순서 (이상률 높은 순):")
    for i, (feat, pct) in enumerate(data_order[:8], 1):
        marker = " ⭐" if feat in designed else ""
        print(f"      {i}. {feat:15s} — {pct:5.1f}%{marker}")

    print(f"    설계 문서 순서:")
    for i, feat in enumerate(designed, 1):
        # 데이터에서 해당 항목의 이상률 찾기
        data_pct = r['features'].get(feat, {}).get('abnormal_pct', 'N/A')
        print(f"      {i}. {feat:15s} — {data_pct}%")


# ============================================================================
# 7. Indicator 측정률 분석 (Tier 2/3 항목)
# ============================================================================

print("\n" + "="*60)
print("Step 6: Profile별 Indicator 측정률 (Tier 2/3)")
print("="*60)

INDICATOR_FEATURES = {
    'ast':        'has_ast',
    'albumin':    'has_albumin',
    'lactate':    'has_lactate',
    'calcium':    'has_calcium',
    'troponin_t': 'has_troponin_t',
    'bnp':        'has_bnp',
}

print(f"\n  {'Profile':15s}", end="")
for feat in INDICATOR_FEATURES:
    print(f" | {feat:>12s}", end="")
print()
print(f"  {'-'*15}", end="")
for _ in INDICATOR_FEATURES:
    print(f"-+-{'-'*12}", end="")
print()

for profile in PROFILE_PRIORITY:
    subset = analysis_df[analysis_df['complaint_profile'] == profile]
    if len(subset) == 0:
        continue
    print(f"  {profile:15s}", end="")
    for feat in INDICATOR_FEATURES:
        if feat in subset.columns:
            measured_pct = subset[feat].notna().mean() * 100
            print(f" | {measured_pct:>10.1f}%", end="")
        else:
            print(f" | {'N/A':>11s}", end="")
    print()

print("\n  💡 해석:")
print("    - CARDIAC에서 troponin_t 측정률이 높으면 → 의사가 ACS를 의심하여 오더")
print("    - SEPSIS에서 lactate 측정률이 높으면 → 의사가 패혈증을 의심하여 오더")
print("    - 측정률 자체가 '의사의 임상 판단' 신호 (MNAR)")


# ============================================================================
# 8. ICD 진단 코드 대조 검증 (Sensitivity / Specificity / PPV)
# ============================================================================

print("\n" + "="*60)
print("Step 7: ICD 진단 코드 대조 — Rule Engine 검증")
print("="*60)

# Profile → ICD 코드 매핑 (Ground Truth)
PROFILE_ICD = {
    'CARDIAC': {
        9:  ['410', '411', '427', '428', '414'],
        10: ['I21', 'I22', 'I48', 'I50', 'I25', 'I20'],
    },
    'SEPSIS': {
        9:  ['99591', '99592', '78552', '038'],
        10: ['A40', 'A41', 'R6520', 'R6521'],
    },
    'RESPIRATORY': {
        9:  ['518', '486', '491', '493', '480', '481', '482'],
        10: ['J96', 'J18', 'J44', 'J45', 'J13', 'J15', 'J80'],
    },
    'RENAL': {
        9:  ['584', '585', '586'],
        10: ['N17', 'N18', 'N19'],
    },
    'GI': {
        9:  ['577', '578', '531', '532', '570', '571'],
        10: ['K85', 'K92', 'K25', 'K26', 'K70', 'K72'],
    },
    'NEUROLOGICAL': {
        9:  ['433', '434', '436', '345', '780'],
        10: ['I63', 'I61', 'I64', 'G40', 'G41', 'R40'],
    },
}


def has_icd_match(hadm_id: int, icd_map: dict) -> bool:
    """해당 입원에 특정 ICD 코드가 있는지 확인"""
    patient_diag = diagnoses[diagnoses['hadm_id'] == hadm_id]
    for _, row in patient_diag.iterrows():
        version = int(row['icd_version'])
        code = str(row['icd_code'])
        for prefix in icd_map.get(version, []):
            if code.startswith(prefix):
                return True
    return False


# 빠른 검증을 위해 hadm_id별 ICD 코드 미리 인덱싱
print("\n  ICD 코드 인덱싱 중...")
hadm_icd_set = defaultdict(set)
for _, row in diagnoses.iterrows():
    hadm_icd_set[row['hadm_id']].add((int(row['icd_version']), str(row['icd_code'])))


def has_icd_match_fast(hadm_id: int, icd_map: dict) -> bool:
    """빠른 ICD 매칭 (미리 인덱싱된 데이터 사용)"""
    codes = hadm_icd_set.get(hadm_id, set())
    for version, code in codes:
        for prefix in icd_map.get(version, []):
            if code.startswith(prefix):
                return True
    return False


print("  ICD 인덱싱 완료!")

# Profile별 Rule Engine 시뮬레이션 + ICD 대조
print("\n  Profile별 검증 결과:")
print(f"  {'Profile':15s} | {'N':>6s} | {'TP':>5s} | {'FP':>5s} | {'FN':>5s} | {'TN':>5s} | "
      f"{'Sens':>6s} | {'Spec':>6s} | {'PPV':>6s}")
print(f"  {'-'*15}-+-{'-'*6}-+-{'-'*5}-+-{'-'*5}-+-{'-'*5}-+-{'-'*5}-+-"
      f"{'-'*6}-+-{'-'*6}-+-{'-'*6}")

for profile in PROFILE_PRIORITY:
    if profile not in PROFILE_ICD or profile not in results:
        continue

    icd_map = PROFILE_ICD[profile]
    subset = analysis_df[analysis_df['complaint_profile'] == profile]
    if len(subset) == 0:
        continue

    # Rule Engine 시뮬레이션: 해당 Profile의 우선 검사 중 이상 수치가 있으면 "양성"
    designed = DESIGNED_ORDER.get(profile, [])

    tp = fp = fn = tn = 0
    for _, row in subset.iterrows():
        # Rule Engine 판정: 우선 검사 중 하나라도 이상이면 양성
        rule_positive = False
        for feat in designed:
            if feat not in row or pd.isna(row.get(feat)):
                continue
            val = row[feat]
            ranges = NORMAL_RANGES.get(feat, {})
            if val < ranges.get('low', float('-inf')) or val > ranges.get('high', float('inf')):
                rule_positive = True
                break

        # Ground Truth: ICD 코드 매칭
        actual_positive = has_icd_match_fast(row['hadm_id'], icd_map)

        if rule_positive and actual_positive:
            tp += 1
        elif rule_positive and not actual_positive:
            fp += 1
        elif not rule_positive and actual_positive:
            fn += 1
        else:
            tn += 1

    sensitivity = tp / (tp + fn) if (tp + fn) > 0 else 0
    specificity = tn / (tn + fp) if (tn + fp) > 0 else 0
    ppv = tp / (tp + fp) if (tp + fp) > 0 else 0

    # 목표 달성 여부 표시
    sens_mark = "✅" if sensitivity >= 0.70 else "⚠️"
    spec_mark = "✅" if specificity >= 0.60 else "⚠️"
    ppv_mark = "✅" if ppv >= 0.30 else "⚠️"

    print(f"  {profile:15s} | {len(subset):>6,} | {tp:>5} | {fp:>5} | {fn:>5} | {tn:>5} | "
          f"{sensitivity:>5.1%}{sens_mark} | {specificity:>5.1%}{spec_mark} | {ppv:>5.1%}{ppv_mark}")

print(f"\n  목표: Sensitivity ≥ 0.70, Specificity ≥ 0.60, PPV ≥ 0.30")


# ============================================================================
# 9. Critical Flag 발동률 분석
# ============================================================================

print("\n" + "="*60)
print("Step 8: Critical Flag 발동률 분석")
print("="*60)

CRITICAL_RULES = [
    ('potassium',  '>',  6.5, '심정지 위험'),
    ('potassium',  '<',  2.5, '치명적 부정맥 위험'),
    ('sodium',     '<',  120, '경련/뇌부종 위험'),
    ('glucose',    '>',  500, 'DKA/HHS 의심'),
    ('glucose',    '<',  40,  '즉시 포도당 투여'),
    ('lactate',    '>',  4.0, '조직 저관류/쇼크'),
    ('hemoglobin', '<',  7.0, '수혈 고려'),
    ('platelet',   '<',  20,  '자발 출혈 위험'),
]

print(f"\n  {'Flag':25s} | {'전체':>8s} | ", end="")
for p in PROFILE_PRIORITY:
    print(f"{p[:5]:>7s} | ", end="")
print()

for feat, op, val, flag_name in CRITICAL_RULES:
    if feat not in analysis_df.columns:
        continue

    # 전체 발동률
    if op == '>':
        total_fired = (analysis_df[feat] > val).sum()
    else:
        total_fired = (analysis_df[feat] < val).sum()
    total_pct = total_fired / len(analysis_df) * 100

    print(f"  {flag_name:25s} | {total_pct:>6.2f}% | ", end="")

    # Profile별 발동률
    for profile in PROFILE_PRIORITY:
        subset = analysis_df[analysis_df['complaint_profile'] == profile]
        if len(subset) == 0:
            print(f"{'N/A':>6s} | ", end="")
            continue
        if op == '>':
            fired = (subset[feat] > val).sum()
        else:
            fired = (subset[feat] < val).sum()
        pct = fired / len(subset) * 100
        print(f"{pct:>5.2f}% | ", end="")
    print()


# ============================================================================
# 10. 최종 요약 및 임계값 조정 권고
# ============================================================================

print("\n" + "="*60)
print("Step 9: 최종 요약 및 권고")
print("="*60)

print("""
📋 분석 요약
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

이 분석 결과를 기반으로:

1. Profile별 우선 확인 검사 순서를 데이터 기반으로 검증/조정
   → 이상률이 높은 순서가 실제 임상적 우선순위와 일치하는지 확인
   → 불일치 시 설계 문서의 순서를 데이터 기반으로 수정

2. Sensitivity/Specificity/PPV 목표 미달 Profile 확인
   → Sensitivity < 0.70: 규칙 추가 또는 임계값 하향 필요
   → Specificity < 0.60: 임계값 상향 또는 규칙 정밀화 필요
   → PPV < 0.30: 규칙 정밀화 필요

3. Indicator 측정률 기반 MNAR 전략 검증
   → CARDIAC에서 troponin_t 측정률이 높으면 설계 의도 부합
   → SEPSIS에서 lactate 측정률이 높으면 설계 의도 부합

4. Critical Flag 발동률 확인
   → 발동률이 너무 높으면 (>5%) 임계값 상향 검토
   → 발동률이 너무 낮으면 (<0.1%) 임계값 하향 검토

다음 단계:
  → 이 분석 결과를 Lab-svc/thresholds.py에 반영
  → Rule Engine 규칙 세트를 데이터 기반으로 최종 확정
  → Lab-svc 서비스 구현 진행
""")

print("✅ 분석 완료!")

