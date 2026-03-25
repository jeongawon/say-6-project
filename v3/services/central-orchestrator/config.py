"""
central-orchestrator 설정 -- 2-tier ConfigMap 전략
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
공통 설정 (common-config):  BEDROCK_REGION, BEDROCK_MODEL_ID, RAG_URL, REPORT_URL, DATABASE_URL, REDIS_URL, LOG_LEVEL
서비스 설정 (dr-ai-config): 서비스 고유 환경변수

기본값 없는 필드 = 환경변수 필수 (ConfigMap에서 주입)
기본값 있는 필드 = 서비스 고유 설정 (환경변수로 오버라이드 가능)
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    중앙 오케스트레이터 설정 클래스.

    모든 필드는 환경 변수로 오버라이드 가능합니다.
    기본값 없는 필드는 반드시 ConfigMap에서 주입되어야 합니다.
    """

    # ── 공통 설정 (common-config에서 주입, 기본값 없음 = 필수) ──
    database_url: str            # 기본값 없음 -- common-config에서 주입
    redis_url: str               # 기본값 없음 -- common-config에서 주입
    bedrock_region: str          # 기본값 없음 -- common-config에서 주입
    bedrock_model_id: str        # 기본값 없음 -- common-config에서 주입
    rag_url: str                 # 기본값 없음 -- common-config에서 주입
    report_url: str              # 기본값 없음 -- common-config에서 주입
    log_level: str = "INFO"      # 공통이지만 서비스별 오버라이드 가능

    # ── 서비스 고유 설정 (기본값 있음) ──
    # 모달 서비스 URL (K8s Service DNS)
    chest_url: str = "http://chest-svc:8000/predict"    # 흉부 X-Ray 분석
    ecg_url: str = "http://ecg-svc:8000/predict"        # ECG 분석
    blood_url: str = "http://blood-svc:8000/predict"    # 혈액 검사 분석

    # 순차 검사 루프의 최대 반복 횟수 (무한 루프 방지)
    max_exam_iterations: int = 5

    # pydantic-settings 설정: env_prefix 없음, 대소문자 무관
    model_config = {"env_prefix": "", "case_sensitive": False}


# 모듈 레벨 싱글턴 -- 앱 전체에서 이 인스턴스를 import하여 사용
settings = Settings()
