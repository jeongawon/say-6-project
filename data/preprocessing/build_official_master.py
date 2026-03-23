"""
공식 CSV 3종으로 Master CSV 완전 재구축
- mimic-cxr-2.0.0-metadata.csv  : dicom_id, ViewPosition (377,110행)
- mimic-cxr-2.0.0-split.csv     : dicom_id → split (377,110행)
- mimic-cxr-2.0.0-chexpert.csv  : study_id → 14개 라벨 (227,827행)
"""

import pandas as pd
import numpy as np
import json
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_DIR = os.path.join(os.path.dirname(BASE_DIR), "mimic-cxr-csv")

# 공식 입력 3종
METADATA_CSV = os.path.join(CSV_DIR, "mimic-cxr-2.0.0-metadata.csv")
SPLIT_CSV = os.path.join(CSV_DIR, "mimic-cxr-2.0.0-split.csv")
CHEXPERT_CSV = os.path.join(CSV_DIR, "mimic-cxr-2.0.0-chexpert.csv")

# 출력
NEW_MASTER = os.path.join(BASE_DIR, "mimic_cxr_official_master.csv")
PA_ONLY_CSV = os.path.join(BASE_DIR, "mimic_cxr_official_pa_only.csv")
P10_TRAIN_READY = os.path.join(BASE_DIR, "p10_train_ready.csv")
POS_WEIGHTS_JSON = os.path.join(BASE_DIR, "pos_weights.json")
REPORT_FILE = os.path.join(BASE_DIR, "preprocessing_report.txt")

LABEL_COLS = [
    "Atelectasis", "Cardiomegaly", "Consolidation", "Edema",
    "Enlarged Cardiomediastinum", "Fracture", "Lung Lesion", "Lung Opacity",
    "No Finding", "Pleural Effusion", "Pleural Other", "Pneumonia",
    "Pneumothorax", "Support Devices"
]

report = []

def log(msg=""):
    print(msg)
    report.append(msg)

def section(title):
    log(f"\n{'='*65}")
    log(f"  {title}")
    log(f"{'='*65}")


# ================================================================
# 1. 공식 CSV 3종 로드
# ================================================================
section("1. 공식 CSV 3종 로드")

metadata = pd.read_csv(METADATA_CSV)
split_df = pd.read_csv(SPLIT_CSV)
chexpert = pd.read_csv(CHEXPERT_CSV)

log(f"metadata.csv   : {len(metadata):,} 행 (이미지 단위)")
log(f"  컬럼: {list(metadata.columns)}")
log(f"split.csv      : {len(split_df):,} 행")
log(f"chexpert.csv   : {len(chexpert):,} 행 (study 단위)")
log(f"  고유 study   : {chexpert['study_id'].nunique():,}")
log(f"  고유 subject : {chexpert['subject_id'].nunique():,}")


# ================================================================
# 2. metadata + split 병합 (dicom_id 기준)
# ================================================================
section("2. metadata + split 병합")

# split_df에서 필요한 것: dicom_id, split
meta_split = metadata.merge(
    split_df[['dicom_id', 'split']],
    on='dicom_id',
    how='inner'
)
log(f"metadata + split JOIN  : {len(meta_split):,} 행")

# image_path 생성: files/pXX/p{subject_id}/s{study_id}/{dicom_id}.jpg
meta_split['pgroup'] = 'p' + (meta_split['subject_id'] // 1000000).astype(str)
meta_split['image_path'] = (
    'files/' + meta_split['pgroup'] +
    '/p' + meta_split['subject_id'].astype(str) +
    '/s' + meta_split['study_id'].astype(str) +
    '/' + meta_split['dicom_id'] + '.jpg'
)
meta_split = meta_split.drop(columns=['pgroup'])

log(f"image_path 예시:")
log(f"  {meta_split['image_path'].iloc[0]}")
log(f"  {meta_split['image_path'].iloc[1]}")


# ================================================================
# 3. chexpert 라벨 JOIN (subject_id + study_id 기준)
# ================================================================
section("3. CheXpert 라벨 JOIN")

master = meta_split.merge(
    chexpert,
    on=['subject_id', 'study_id'],
    how='inner'
)

log(f"최종 JOIN 결과         : {len(master):,} 행")
log(f"  매칭율               : {len(master)/len(meta_split)*100:.1f}%")

unmatched = len(meta_split) - len(master)
log(f"  미매칭 (라벨 없음)   : {unmatched:,} 행")

# 필요한 컬럼만 정리
keep_cols = ['subject_id', 'study_id', 'dicom_id', 'split', 'ViewPosition', 'image_path'] + LABEL_COLS
master = master[keep_cols]

log(f"\n고유 subject_id        : {master['subject_id'].nunique():,}")
log(f"고유 study_id          : {master['study_id'].nunique():,}")
log(f"고유 dicom_id          : {master['dicom_id'].nunique():,}")


# ================================================================
# 4. 기본 통계
# ================================================================
section("4. 기본 통계")

log(f"[ViewPosition 분포]")
for vp, cnt in master['ViewPosition'].value_counts().items():
    log(f"  {str(vp):15s} : {cnt:>8,}")

log(f"\n[split 분포]")
for sp, cnt in master['split'].value_counts().items():
    log(f"  {sp:12s} : {cnt:>8,}")

log(f"\n[14개 라벨 분포 (변환 전)]")
log(f"{'질환':<30s} {'1.0':>8s} {'0.0':>8s} {'-1.0':>8s} {'NaN':>8s}")
log("-" * 62)
for col in LABEL_COLS:
    pos = (master[col] == 1.0).sum()
    neg = (master[col] == 0.0).sum()
    unc = (master[col] == -1.0).sum()
    nan_ = master[col].isna().sum()
    log(f"{col:<30s} {pos:>8,} {neg:>8,} {unc:>8,} {nan_:>8,}")


# ================================================================
# 5. 전체 Master CSV 저장
# ================================================================
section("5. 전체 Master CSV 저장")

master.to_csv(NEW_MASTER, index=False)
log(f"저장: {os.path.basename(NEW_MASTER)}")
log(f"  행 수: {len(master):,}")
log(f"  크기: {os.path.getsize(NEW_MASTER)/1024/1024:.2f} MB")


# ================================================================
# 6. PA Only 필터링
# ================================================================
section("6. PA Only 필터링")

pa_only = master[master['ViewPosition'] == 'PA'].copy()
log(f"PA 필터링: {len(master):,} → {len(pa_only):,}")

pa_only.to_csv(PA_ONLY_CSV, index=False)
log(f"저장: {os.path.basename(PA_ONLY_CSV)}")

log(f"\n[PA split별 행 수]")
for sp, cnt in pa_only['split'].value_counts().items():
    log(f"  {sp:12s} : {cnt:>8,}")


# ================================================================
# 7. 불량 데이터 제거 + U-Ones 라벨 변환
# ================================================================
section("7. 불량 데이터 제거 + U-Ones 라벨 변환")

df = pa_only.copy()
before = len(df)

dup = df.duplicated(subset=['dicom_id'], keep='first').sum()
df = df.drop_duplicates(subset=['dicom_id'], keep='first')
log(f"dicom_id 중복 제거     : {dup:,} 행")

all_nan = df[LABEL_COLS].isna().all(axis=1).sum()
df = df[~df[LABEL_COLS].isna().all(axis=1)]
log(f"라벨 전부 NaN 제거     : {all_nan:,} 행")

bad_path = df['image_path'].isna() | (df['image_path'].astype(str).str.strip() == '')
bad_path_cnt = bad_path.sum()
df = df[~bad_path]
log(f"image_path 결측 제거   : {bad_path_cnt:,} 행")

after = len(df)
log(f"\n정리: {before:,} → {after:,} ({before - after:,} 행 제거)")

# U-Ones 변환 전 분포 저장
label_dist_before = {}
for col in LABEL_COLS:
    label_dist_before[col] = {
        "pos": (df[col] == 1.0).sum(),
        "neg": (df[col] == 0.0).sum(),
        "unc": (df[col] == -1.0).sum(),
        "nan": df[col].isna().sum(),
    }

# U-Ones 변환
for col in LABEL_COLS:
    df[col] = df[col].replace(-1.0, 1.0)
    df[col] = df[col].fillna(0.0)

# 검증
all_valid = True
for col in LABEL_COLS:
    if not set(df[col].unique()).issubset({0.0, 1.0}):
        log(f"  [경고] {col}: 예상외 값")
        all_valid = False
if all_valid:
    log("\nU-Ones 변환 완료, 검증 통과 (모든 라벨 0/1)")

log(f"\n{'질환':<30s} {'변환전 양성%':>12s} {'변환후 양성%':>12s} {'변화':>8s}")
log("-" * 65)
for col in LABEL_COLS:
    bd = label_dist_before[col]
    total_b = bd['pos'] + bd['neg'] + bd['unc'] + bd['nan']
    pct_b = bd['pos'] / total_b * 100 if total_b > 0 else 0
    pct_a = (df[col] == 1.0).sum() / len(df) * 100
    delta = pct_a - pct_b
    log(f"{col:<30s} {pct_b:>11.2f}% {pct_a:>11.2f}% {delta:>+7.2f}%")


# ================================================================
# 8. 클래스 가중치 (pos_weight) — PA only, train split
# ================================================================
section("8. 클래스 가중치 (pos_weight) 계산")

train_df = df[df['split'] == 'train']
log(f"train split 행 수: {len(train_df):,}")

pos_weights = {}
log(f"\n{'질환':<30s} {'양성':>8s} {'음성':>8s} {'양성%':>8s} {'pos_weight':>12s} {'비고':>8s}")
log("-" * 80)

for col in LABEL_COLS:
    pos = (train_df[col] == 1.0).sum()
    neg = (train_df[col] == 0.0).sum()
    pct = pos / len(train_df) * 100 if len(train_df) > 0 else 0

    pw = neg / pos if pos > 0 else 100.0
    note_parts = []
    if pw > 100.0:
        pw = 100.0
        note_parts.append("clip")
    if pct < 2.0:
        note_parts.append("<2%")
    note = " ".join(note_parts)

    pos_weights[col] = round(pw, 4)
    log(f"{col:<30s} {pos:>8,} {neg:>8,} {pct:>7.2f}% {pw:>12.4f} {note:>8s}")

with open(POS_WEIGHTS_JSON, 'w') as f:
    json.dump(pos_weights, f, indent=2, ensure_ascii=False)
log(f"\n저장: {os.path.basename(POS_WEIGHTS_JSON)}")


# ================================================================
# 9. p10 필터링 + 최종 CSV 저장
# ================================================================
section("9. p10 필터링 + 최종 CSV 저장")

before_p10 = len(df)
df_p10 = df[df['image_path'].str.contains('/p10/', na=False)].copy()
log(f"p10 필터링: {before_p10:,} → {len(df_p10):,}")

for col in LABEL_COLS:
    df_p10[col] = df_p10[col].astype(int)

log(f"\n[최종 split별 행 수]")
for sp, cnt in df_p10['split'].value_counts().items():
    log(f"  {sp:12s} : {cnt:>8,}")
log(f"  {'총계':12s} : {len(df_p10):,}")

df_p10.to_csv(P10_TRAIN_READY, index=False)
log(f"\n저장: {os.path.basename(P10_TRAIN_READY)}")
log(f"  크기: {os.path.getsize(P10_TRAIN_READY)/1024/1024:.2f} MB")


# ================================================================
# 최종 요약
# ================================================================
section("최종 요약")
log(f"생성 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
log(f"")
log(f"[데이터 출처 — 전부 공식]")
log(f"  라벨   : mimic-cxr-2.0.0-chexpert.csv  (CheXpert NLP Labeler)")
log(f"  메타   : mimic-cxr-2.0.0-metadata.csv   (ViewPosition, dicom_id)")
log(f"  분할   : mimic-cxr-2.0.0-split.csv      (patient-level split)")
log(f"")
log(f"[커버리지]")
log(f"  S3 버킷 이미지       : ~377,110 장")
log(f"  metadata             : {len(metadata):,} 행")
log(f"  chexpert 라벨        : {len(chexpert):,} studies")
log(f"  JOIN (전체)          : {len(master):,} 이미지 ({len(master)/377110*100:.1f}%)")
log(f"  PA Only              : {len(pa_only):,} 이미지")
log(f"  정리 후 (PA)         : {after:,} 이미지")
log(f"  p10 최종             : {len(df_p10):,} 이미지")
log(f"")
log(f"[출력 파일]")
log(f"  1. mimic_cxr_official_master.csv  — 전체 ({len(master):,}행)")
log(f"  2. mimic_cxr_official_pa_only.csv — PA만 ({len(pa_only):,}행)")
log(f"  3. p10_train_ready.csv            — p10+U-Ones ({len(df_p10):,}행)")
log(f"  4. pos_weights.json               — 클래스 가중치")
log(f"  5. preprocessing_report.txt       — 이 보고서")

with open(REPORT_FILE, 'w', encoding='utf-8') as f:
    f.write("\n".join(report))
print(f"\n보고서 저장: {REPORT_FILE}")
