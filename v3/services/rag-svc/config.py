"""
rag-svc 설정 -- 2-tier ConfigMap 전략
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
공통 설정 (common-config):  BEDROCK_REGION, BEDROCK_MODEL_ID, RAG_URL, DATABASE_URL, REDIS_URL, LOG_LEVEL
서비스 설정 (dr-ai-config): 서비스 고유 환경변수

기본값 없는 필드 = 환경변수 필수 (ConfigMap에서 주입)
기본값 있는 필드 = 서비스 고유 설정 (환경변수로 오버라이드 가능)

[팀원E 수정 포인트]
- model_dir: K8s PVC 마운트 경로에 맞게 조정
- embedder_model: 다른 임베딩 모델 사용 시 변경
- embedding_dimension: 임베딩 모델에 따라 차원 수 조정
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):

    # ── 공통 설정 (common-config에서 주입) ──
    log_level: str = "INFO"      # 공통이지만 서비스별 오버라이드 가능

    # ── 서비스 고유 설정 (기본값 있음) ──
    # FAISS 인덱스 + 메타데이터 디렉토리
    # K8s 배포 시 PVC 마운트 포인트, 로컬에서는 ./data 등으로 변경
    model_dir: str = "/models/chest"

    # FAISS 인덱스 바이너리 파일명 (model_dir 아래에 위치)
    index_filename: str = "faiss_index.bin"

    # 벡터별 메타데이터 파일명 (JSONL 형식, model_dir 아래에 위치)
    metadata_filename: str = "metadata.jsonl"

    # ── Embedding 모델 설정 ──
    # FastEmbed 모델명 (ONNX Runtime 기반, PyTorch 불필요)
    # Docker: 이미지 빌드 시 프리캐시, 런타임 인터넷 불필요
    embedder_model: str = "BAAI/bge-small-en-v1.5"

    # 임베딩 벡터 차원 수 (embedder_model에 맞춰야 함)
    embedding_dimension: int = 384

    # ── 검색 기본값 ──
    # /search API에서 top_k 미지정 시 사용하는 기본값
    default_top_k: int = 5

    # ── 서버 ──
    port: int = 8000

    model_config = {}


# 모듈 임포트 시 자동으로 환경변수에서 설정 로드
settings = Settings()
