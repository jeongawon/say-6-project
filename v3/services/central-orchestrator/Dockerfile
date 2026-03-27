# ── central-orchestrator Docker 이미지 ───────────────────────
# 중앙 오케스트레이터 서비스 (API Gateway + 서비스 조율)
# 클라이언트 요청을 받아 chest/ecg/blood 서비스에 분배하고 결과를 종합
# asyncpg로 PostgreSQL 비동기 접속
# 빌드: docker build -f services/central-orchestrator/Dockerfile -t central-orchestrator .
# ──────────────────────────────────────────────────────────────

# 베이스 이미지 — Python 3.11 경량 이미지
FROM python:3.11-slim

# 시스템 의존성 설치 — libpq-dev는 asyncpg(PostgreSQL 비동기 드라이버)에 필요
# apt 캐시 삭제로 이미지 크기 최소화
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Docker 캐시 최적화 전략 ──────────────────────────────────
# requirements.txt를 먼저 복사하여 의존성 레이어를 캐시
# 소스코드만 변경 시 pip install 단계를 재실행하지 않아 빌드 속도 향상
COPY services/central-orchestrator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 공유 스키마 복사 — 서비스 간 공통 데이터 모델 (Pydantic 스키마 등)
COPY shared/ /app/shared/
# PYTHONPATH 설정 — shared 모듈을 import 할 수 있도록 경로 추가
ENV PYTHONPATH="/app:/app/shared"

# 서비스 소스코드 복사
COPY services/central-orchestrator/ /app/

# 서비스 포트 — 오케스트레이터의 메인 진입점 (호스트 8000번으로 매핑)
EXPOSE 8000

# K8s 리소스 힌트 (실제 제한은 K8s manifest에서 적용)
# CPU: 250m, Memory: 512Mi
# readinessProbe: /readyz 엔드포인트, 5초 후 시작
# Resource hints (enforced by K8s resource limits)

# ── 서버 실행 ────────────────────────────────────────────────
# uvicorn ASGI 서버로 FastAPI 앱 실행
# log-level=info: 운영 환경 기본 로그 수준
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
