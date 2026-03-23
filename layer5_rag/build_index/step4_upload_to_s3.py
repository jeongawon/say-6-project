"""
Step 4: FAISS 인덱스 + 메타데이터를 작업 버킷 S3에 업로드.

입력: build_output/faiss_index.bin, build_output/metadata.jsonl
출력: s3://work-bucket/rag/faiss_index.bin, s3://work-bucket/rag/metadata.jsonl
"""
import boto3
import json
import os

WORK_BUCKET = "pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an"
RAG_PREFIX = "rag/"
REGION = "ap-northeast-2"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "build_output")


def upload_to_s3(local_dir: str = None):
    if local_dir is None:
        local_dir = OUTPUT_DIR

    s3 = boto3.client("s3", region_name=REGION)

    files = [
        ("faiss_index.bin", f"{RAG_PREFIX}faiss_index.bin"),
        ("metadata.jsonl", f"{RAG_PREFIX}metadata.jsonl"),
    ]

    for local_name, s3_key in files:
        local_path = os.path.join(local_dir, local_name)
        if not os.path.exists(local_path):
            print(f"  건너뜀 (파일 없음): {local_path}")
            continue
        size_mb = os.path.getsize(local_path) / 1024 / 1024
        print(f"업로드: {local_name} ({size_mb:.1f} MB) → s3://{WORK_BUCKET}/{s3_key}")
        s3.upload_file(local_path, WORK_BUCKET, s3_key)
        print(f"  완료")

    # 인덱스 설정 정보 저장
    config = {
        "embedding_model": "BAAI/bge-small-en-v1.5",
        "dimension": 384,
        "index_type": "IVFFlat",
        "source_bucket": "say1-pre-project-7",
        "source_key": "mimic-iv-note/2.2/note/radiology.csv",
        "includes_findings": True,
        "includes_indication": True,
        "built_date": "2026-03-22",
    }
    s3.put_object(
        Bucket=WORK_BUCKET,
        Key=f"{RAG_PREFIX}config.json",
        Body=json.dumps(config, indent=2),
        ContentType="application/json",
    )
    print(f"설정 저장: s3://{WORK_BUCKET}/{RAG_PREFIX}config.json")


if __name__ == "__main__":
    upload_to_s3()
