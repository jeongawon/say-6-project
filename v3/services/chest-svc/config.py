"""
chest-svc 설정 -- 2-tier ConfigMap 전략
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
공통 설정 (common-config):  BEDROCK_REGION, BEDROCK_MODEL_ID, RAG_URL, DATABASE_URL, REDIS_URL, LOG_LEVEL
서비스 설정 (dr-ai-config): 서비스 고유 환경변수

기본값 없는 필드 = 환경변수 필수 (ConfigMap에서 주입)
기본값 있는 필드 = 서비스 고유 설정 (환경변수로 오버라이드 가능)
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):

    # ── 공통 설정 (common-config에서 주입, 기본값 없음 = 필수) ──
    bedrock_region: str          # 기본값 없음 -- common-config에서 주입
    bedrock_model_id: str        # 기본값 없음 -- common-config에서 주입
    rag_url: str                 # 기본값 없음 -- common-config에서 주입
    log_level: str = "INFO"      # 공통이지만 서비스별 오버라이드 가능

    # ── 서비스 고유 설정 (기본값 있음) ──
    # ONNX 모델 경로 — K8s PVC 마운트 경로. 로컬 테스트 시 MODEL_DIR 환경변수로 변경
    # 디렉토리 안에 unet.onnx, densenet.onnx, yolov8.onnx 필요
    model_dir: str = "/app/models"

    # Bedrock 소견서 생성 파라미터 (chest-svc 고유)
    bedrock_max_tokens: int = 1024
    bedrock_temperature: float = 0.2
    bedrock_retry_temperature: float = 0.0

    # uvicorn 바인딩 포트 (Dockerfile CMD에서도 사용)
    port: int = 8000

    # env_prefix="": 환경변수 이름 그대로 매핑 (예: MODEL_DIR -> model_dir)
    # case_sensitive=False: MODEL_DIR, model_dir 둘 다 인식
    model_config = {"env_file": ".env", "env_prefix": "", "case_sensitive": False}


# 모듈 로드 시 싱글턴 인스턴스 생성
settings = Settings()
