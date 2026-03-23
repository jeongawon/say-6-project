"""Layer 5 RAG 설정"""
import os


class Config:
    REGION = os.environ.get("AWS_REGION", "ap-northeast-2")

    # S3 — 작업 버킷 (FAISS 인덱스 저장)
    S3_BUCKET = os.environ.get(
        "S3_BUCKET",
        "pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an",
    )
    FAISS_INDEX_KEY = os.environ.get("FAISS_INDEX_KEY", "rag/faiss_index.bin")
    METADATA_KEY = os.environ.get("METADATA_KEY", "rag/metadata.jsonl")

    # 원본 데이터 버킷 (읽기 전용)
    SOURCE_BUCKET = "say1-pre-project-7"
    SOURCE_CSV_KEY = "mimic-iv-note/2.2/note/radiology.csv"

    # Embedding — FastEmbed (로컬 ONNX, PyTorch 불필요)
    EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
    EMBEDDING_DIMENSION = 384

    # 검색 설정
    DEFAULT_TOP_K = 3

    # Lambda 설정
    TIMEOUT = 30
    MEMORY = 1024
