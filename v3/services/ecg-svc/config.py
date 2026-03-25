"""
ecg-svc 설정 -- 2-tier ConfigMap 전략
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
    service_name: str = "ecg-svc"       # 서비스 이름 (로그, 메타데이터에 사용)
    port: int = 8000                    # uvicorn 서버 포트
    http_timeout: float = 30.0          # 외부 HTTP 호출 타임아웃 (초)

    # TODO: ML 모델 도입 시 아래 설정 추가 예정
    # model_path: str = "/app/models/ecg_model.onnx"  # 모델 파일 경로
    # model_device: str = "cpu"                        # 추론 디바이스 (cpu/cuda)

    model_config = {"case_sensitive": False}  # 환경변수 대소문자 구분 안함


# 싱글턴 설정 객체 -- 앱 전체에서 이 인스턴스를 import하여 사용
settings = Settings()
