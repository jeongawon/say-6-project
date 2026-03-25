"""
report-svc 설정 -- 2-tier ConfigMap 전략
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
공통 설정 (common-config):  BEDROCK_REGION, BEDROCK_MODEL_ID, RAG_URL, DATABASE_URL, REDIS_URL, LOG_LEVEL
서비스 설정 (dr-ai-config): 서비스 고유 환경변수

기본값 없는 필드 = 환경변수 필수 (ConfigMap에서 주입)
기본값 있는 필드 = 서비스 고유 설정 (환경변수로 오버라이드 가능)

[팀원E 수정 포인트]
- bedrock_region / bedrock_model_id: common-config에서 관리 (여기서 수정 불필요)
- max_tokens: 보고서 길이에 따라 조정 (긴 보고서 필요 시 증가)
- temperature: 생성 다양성 조절 (의료 보고서는 낮은 값 권장)
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):

    # ── 공통 설정 (common-config에서 주입, 기본값 없음 = 필수) ──
    bedrock_region: str          # 기본값 없음 -- common-config에서 주입
    bedrock_model_id: str        # 기본값 없음 -- common-config에서 주입

    # ── 서비스 고유 설정 (기본값 있음) ──
    # 최대 출력 토큰 수 -- 보고서 길이 제한
    max_tokens: int = 4096

    # 생성 온도 -- 0에 가까울수록 일관된(결정적) 출력
    # 의료 보고서는 일관성이 중요하므로 낮은 값 사용
    temperature: float = 0.2

    # JSON 파싱 실패 시 재시도 온도 -- 0.0으로 설정하여 가장 결정적인 출력 유도
    retry_temperature: float = 0.0

    # ── 서버 ──
    port: int = 8000

    model_config = {}


# 모듈 임포트 시 자동으로 환경변수에서 설정 로드
settings = Settings()
