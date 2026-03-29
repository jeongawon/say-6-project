"""
WFDB -> .npy 변환 스크립트

로컬 저장 모드 (기본):
    python scripts/upload_signals_to_s3.py \
        --csv ecg_balanced_dataset.csv \
        --wfdb_base ~/ecg_waveforms \
        --out_dir ~/ecg_signals_npy \
        --skip_existing

S3 직접 업로드 모드:
    python scripts/upload_signals_to_s3.py \
        --csv ecg_balanced_dataset.csv \
        --wfdb_base ~/ecg_waveforms \
        --bucket say2-6team

로컬 저장 후 수동 업로드:
    aws s3 cp ~/ecg_signals_npy/ s3://say2-6team/mimic/ecg/signals/ --recursive
"""

import argparse
import os
from io import BytesIO

import boto3
import numpy as np
import pandas as pd
import wfdb

SAMPLE_RATE  = 500
DURATION_SEC = 10
EXPECTED_LEN = SAMPLE_RATE * DURATION_SEC  # 5000
N_LEADS      = 12
S3_PREFIX    = "mimic/ecg/signals"


def load_wfdb_signal(file_name: str, wfdb_base: str) -> np.ndarray:
    """
    file_name: mimic-iv-ecg-.../files/p1603/p16036071/s49042046/49042046
    wfdb_base: ~/ecg_waveforms
    """
    # file_name에서 'files/' 이후 경로만 추출
    # 예: mimic-iv-ecg-.../files/p1607/p16076716/s48527964/48527964
    #  → ~/ecg_waveforms/files/p1607/p16076716/s48527964/48527964
    rel = file_name.split('/files/', 1)[-1]
    record_path = os.path.join(wfdb_base, 'files', rel)
    record = wfdb.rdrecord(record_path)
    signal = record.p_signal.astype(np.float32)  # (samples, leads)

    if signal.shape[1] != N_LEADS:
        raise ValueError(f"leads mismatch: {signal.shape[1]}")

    n = signal.shape[0]
    if n < EXPECTED_LEN:
        signal = np.vstack([signal, np.zeros((EXPECTED_LEN - n, N_LEADS), dtype=np.float32)])
    elif n > EXPECTED_LEN:
        signal = signal[:EXPECTED_LEN]

    signal = signal.T  # (12, 5000)

    if np.isnan(signal).any():
        signal = np.nan_to_num(signal, nan=0.0)

    return signal


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv",       required=True, help="ecg_balanced_dataset.csv")
    parser.add_argument("--wfdb_base", required=True, help="WFDB files root dir")
    parser.add_argument("--out_dir",   default="~/ecg_signals_npy",
                        help="local output dir (used when --bucket not set)")
    parser.add_argument("--bucket",    default=None,
                        help="S3 bucket (if set, upload to S3 directly)")
    parser.add_argument("--skip_existing", action="store_true")
    args = parser.parse_args()

    out_dir = os.path.expanduser(args.out_dir)
    use_s3  = args.bucket is not None

    df = pd.read_csv(args.csv)
    print(f"total rows: {len(df)}", flush=True)

    existing = set()
    if args.skip_existing:
        if use_s3:
            s3c = boto3.client("s3")
            paginator = s3c.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=args.bucket, Prefix=S3_PREFIX + "/"):
                for obj in page.get("Contents", []):
                    existing.add(obj["Key"].split("/")[-1].replace(".npy", ""))
        else:
            if os.path.isdir(out_dir):
                existing = {f.replace(".npy", "") for f in os.listdir(out_dir) if f.endswith(".npy")}
        print(f"skip existing: {len(existing)}", flush=True)

    if use_s3:
        s3c = boto3.client("s3")
    else:
        os.makedirs(out_dir, exist_ok=True)

    ok, fail = 0, 0
    for i, (_, row) in enumerate(df.iterrows()):
        study_id = str(row["study_id"])
        if study_id in existing:
            continue
        try:
            signal = load_wfdb_signal(row["file_name"], args.wfdb_base)
            if use_s3:
                key = f"{S3_PREFIX}/{study_id}.npy"
                buf = BytesIO()
                np.save(buf, signal)
                buf.seek(0)
                s3c.put_object(Bucket=args.bucket, Key=key, Body=buf.getvalue())
            else:
                np.save(os.path.join(out_dir, f"{study_id}.npy"), signal)
            ok += 1
        except Exception:
            fail += 1

        if (i + 1) % 1000 == 0:
            print(f"[{i+1}/{len(df)}] ok={ok} fail={fail}", flush=True)

    print(f"\ndone: ok={ok} fail={fail}", flush=True)
    if not use_s3:
        print(f"saved to: {out_dir}", flush=True)
        print(f"upload cmd: aws s3 cp {out_dir}/ s3://say2-6team/{S3_PREFIX}/ --recursive", flush=True)


if __name__ == "__main__":
    main()
