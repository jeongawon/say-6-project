"""
Step 1: Bucket 7 radiology.csv에서 흉부 X-Ray 판독문 추출 + 섹션 파싱.

S3에서 직접 다운로드 → pandas로 CHEST 필터링 → IMPRESSION 파싱.
다운로드 ~5분 + pandas 처리 ~1-2분 = 총 ~7분.

출력: build_output/reports.jsonl
"""
import boto3
import re
import json
import os
import time
import sys

S3_BUCKET = "say1-pre-project-7"
S3_KEY = "mimic-iv-note/2.2/note/radiology.csv"
REGION = "ap-northeast-2"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "build_output")


class DownloadProgress:
    """S3 다운로드 진행률 콜백."""
    def __init__(self, total_size):
        self.total = total_size
        self.downloaded = 0
        self.start_time = time.time()
        self.last_print = 0

    def __call__(self, bytes_amount):
        self.downloaded += bytes_amount
        now = time.time()
        if now - self.last_print >= 2:  # 2초마다 출력
            self.last_print = now
            pct = self.downloaded / self.total * 100
            elapsed = now - self.start_time
            speed = self.downloaded / elapsed / 1024 / 1024 if elapsed > 0 else 0
            eta = (self.total - self.downloaded) / (self.downloaded / elapsed) if self.downloaded > 0 else 0
            print(f"  다운로드: {pct:.1f}% ({self.downloaded/1024**3:.2f}/{self.total/1024**3:.2f} GB) | {speed:.1f} MB/s | ETA {eta:.0f}s")
            sys.stdout.flush()


def parse_report_sections(report_text: str) -> dict:
    """판독문 free-text에서 각 섹션을 추출."""
    sections = {
        "examination": None,
        "indication": None,
        "comparison": None,
        "findings": None,
        "impression": None,
    }

    patterns = [
        ("examination", r'(?:EXAMINATION|EXAM|TYPE OF EXAMINATION)[:\s]*(.+?)(?=(?:INDICATION|CLINICAL INFORMATION|HISTORY|TECHNIQUE|COMPARISON|FINDINGS|IMPRESSION|$))', re.DOTALL | re.IGNORECASE),
        ("indication", r'(?:INDICATION|CLINICAL INFORMATION|HISTORY|REASON FOR EXAM)[:\s]*(.+?)(?=(?:TECHNIQUE|COMPARISON|FINDINGS|IMPRESSION|$))', re.DOTALL | re.IGNORECASE),
        ("comparison", r'(?:COMPARISON)[:\s]*(.+?)(?=(?:FINDINGS|IMPRESSION|$))', re.DOTALL | re.IGNORECASE),
        ("findings", r'(?:FINDINGS)[:\s]*(.+?)(?=(?:IMPRESSION|CONCLUSION|$))', re.DOTALL | re.IGNORECASE),
        ("impression", r'(?:IMPRESSION|CONCLUSION|SUMMARY)[:\s]*(.+?)$', re.DOTALL | re.IGNORECASE),
    ]

    for section_name, pattern, flags in patterns:
        match = re.search(pattern, report_text, flags)
        if match:
            text = match.group(1).strip()
            text = re.sub(r'\s+', ' ', text)
            if text and len(text) > 3:
                sections[section_name] = text

    return sections


def extract_with_pandas():
    """
    S3 다운로드 → pandas 로컬 처리.
    다운로드 ~5분, 필터링+파싱 ~1-2분.
    """
    import pandas as pd

    s3 = boto3.client("s3", region_name=REGION)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, "reports.jsonl")
    local_csv = os.path.join(OUTPUT_DIR, "radiology.csv")

    # 파일 크기 확인
    head = s3.head_object(Bucket=S3_BUCKET, Key=S3_KEY)
    file_size = head["ContentLength"]
    print(f"radiology.csv 크기: {file_size / 1024**3:.2f} GB")

    # 1) S3에서 다운로드 (진행률 표시)
    start_time = time.time()
    if os.path.exists(local_csv) and os.path.getsize(local_csv) == file_size:
        print(f"이미 다운로드됨: {local_csv}")
    else:
        print("S3에서 다운로드 시작...")
        progress = DownloadProgress(file_size)
        s3.download_file(S3_BUCKET, S3_KEY, local_csv, Callback=progress)
        elapsed = time.time() - start_time
        print(f"다운로드 완료: {elapsed:.0f}초 ({elapsed/60:.1f}분)")

    # 2) pandas로 로드 + 필터링
    print("pandas로 CSV 로딩 중...")
    load_start = time.time()
    df = pd.read_csv(local_csv, dtype=str)
    print(f"  전체 로드: {len(df):,}건 ({time.time()-load_start:.1f}초)")

    # CHEST 관련 키워드 필터
    print("CHEST 관련 필터링 중...")
    text_col = df["text"].fillna("")
    text_upper = text_col.str.upper()
    mask = (
        text_upper.str.contains("CHEST", na=False) |
        text_upper.str.contains("CXR", na=False) |
        text_upper.str.contains("THORAX", na=False) |
        text_upper.str.contains("PA AND LAT", na=False) |
        text_upper.str.contains("PORTABLE", na=False)
    )
    chest_df = df[mask].copy()
    print(f"  CHEST 관련: {len(chest_df):,}건 (전체의 {len(chest_df)/len(df)*100:.1f}%)")

    # 3) 섹션 파싱
    print("IMPRESSION 파싱 중...")
    reports = []
    no_impression = 0

    for i, (_, row) in enumerate(chest_df.iterrows()):
        text = row.get("text", "")
        if not text or pd.isna(text):
            continue

        sections = parse_report_sections(text)
        if not sections["impression"]:
            no_impression += 1
            continue

        # FINDINGS 500단어 제한
        if sections["findings"] and len(sections["findings"].split()) > 500:
            words = sections["findings"].split()[:500]
            sections["findings"] = " ".join(words) + "..."

        record = {
            "note_id": row.get("note_id", ""),
            "subject_id": row.get("subject_id", ""),
            "hadm_id": row.get("hadm_id", ""),
            "charttime": row.get("charttime", ""),
            "examination": sections["examination"],
            "indication": sections["indication"],
            "comparison": sections["comparison"],
            "findings": sections["findings"],
            "impression": sections["impression"],
        }
        reports.append(record)

        if (i + 1) % 20000 == 0:
            pct = (i + 1) / len(chest_df) * 100
            print(f"  파싱 진행: {pct:.1f}% ({i+1:,}/{len(chest_df):,})")

    # 4) JSONL 저장
    with open(output_path, "w", encoding="utf-8") as f:
        for record in reports:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    total_elapsed = time.time() - start_time
    print(f"\n추출 완료: {len(reports):,}건 → {output_path}")
    print(f"  CHEST 관련: {len(chest_df):,}")
    print(f"  IMPRESSION 없음: {no_impression:,}")
    print(f"  IMPRESSION 포함: {len(reports):,}")
    has_findings = sum(1 for r in reports if r["findings"])
    print(f"  FINDINGS 포함: {has_findings:,}")
    print(f"  총 소요: {total_elapsed:.0f}초 ({total_elapsed/60:.1f}분)")

    # 로컬 CSV 삭제 (디스크 절약)
    if os.path.exists(local_csv):
        os.remove(local_csv)
        print(f"  임시 CSV 삭제: {local_csv}")

    return output_path


if __name__ == "__main__":
    extract_with_pandas()
