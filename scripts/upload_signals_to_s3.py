"""
WFDB 파형 → .npy 변환 후 S3 업로드 (1회성 데이터 준비)

SageMaker에서 실행 (WFDB 파일이 로컬에 있을 때)

실행:
    python scripts/upload_signals_to_s3.py \
        --csv ecg_balanced_dataset.csv \
        --wfdb_base /home/sagemaker-user/mimic_iv_ecg/files \
        --bucket say2-6team

결과:
    s3://say2-6team/mimic/ecg/signals/{study_id}.npy
"""

import argparse
import os
from io import BytesIO

import boto3
import numpy as np
import pandas as pd
import wfdb
from tqdm import tqdm

SAMPLE_RATE  = 500
DURATION_SEC = 10
EXPECTED_LEN = SAMPLE_RATE * DURATION_SEC  # 5000
N_LEADS      = 12
S3_PREFIX    = "mimic/ecg/signals"


def load_wfdb_signal(file_name: str, wfdb_base: str) -> np.ndarray:
    """
    ecg_balanced_dataset의 file_name → (12, 5000) float32

    file_name 예:
      mimic-iv-ecg-diagnostic-electrocardiogram-matched-subset-1.0/files/p1603/p16036071/s49042046/49042046
    wfdb_base 예:
      ~/ecg_waveforms
    → 최종 경로: ~/ecg_waveforms/mimic-iv-ecg-.../files/p1603/.../49042046
    """
    record_path = os.path.join(wfdb_base, file_name)

    record = wfdb.rdrecord(record_path)
    signal = record.p_signal.astype(np.float32)  # (samples, leads)

    if signal.shape[1] != N_LEADS:
        raise ValueError(f"리드 수 불일치: {signal.shape[1]}")

    # 길이 보정
    n = signal.shape[0]
    if n < EXPECTED_LEN:
        signal = np.vstack([signal, np.zeros((EXPECTED_LEN - n, N_LEADS), dtype=np.float32)])
    elif n > EXPECTED_LEN:
        signal = signal[:EXPECTED_LEN]

    signal = signal.T  # (12, 5000)

    if np.isnan(signal).any():
        signal = np.nan_to_num(signal, nan=0.0)

    return signal


def upload(signal: np.ndarray, study_id: str, bucket: str, s3) -> None:
    key = f"{S3_PREFIX}/{study_id}.npy"
    buf = BytesIO()
    np.save(buf, signal)
    buf.seek(0)
    s3.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv",      required=True, help="ecg_balanced_dataset.csv 경로")
    parser.add_argument("--wfdb_base", required=True, help="WFDB files/ 디렉토리 경로")
    parser.add_argument("--bucket",   default="say2-6team")
    parser.add_argument("--skip_existing", action="store_true", help="이미 업로드된 study_id 스킵")
    args = parser.parse_args()

    df = pd.read_csv(args.csv)
    s3 = boto3.client("s3")

    # 기존 업로드 목록 (skip_existing 옵션)
    existing = set()
    if args.skip_existing:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=args.bucket, Prefix=S3_PREFIX + "/"):
            for obj in page.get("Contents", []):
                study_id = obj["Key"].split("/")[-1].replace(".npy", "")
                existing.add(study_id)
        print(f"이미 업로드된 파일: {len(existing)}개 스킵")

    ok, fail = 0, 0
    for _, row in tqdm(df.iterrows(), total=len(df), desc="업로드"):
        study_id = str(row["study_id"])
        if study_id in existing:
            continue
        try:
            signal = load_wfdb_signal(row["file_name"], args.wfdb_base)
            upload(signal, study_id, args.bucket, s3)
            ok += 1
        except Exception as e:
            print(f"[FAIL] study_id={study_id}: {e}")
            fail += 1

    print(f"\n완료: 성공 {ok}개 / 실패 {fail}개")
    print(f"S3 경로: s3://{args.bucket}/{S3_PREFIX}/{{study_id}}.npy")


if __name__ == "__main__":
    main()
