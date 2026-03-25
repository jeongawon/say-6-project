# ── ecg-svc Docker 이미지 ────────────────────────────────────
# 심전도(ECG) 분석 서비스
# 12-lead ECG 데이터를 분석하여 부정맥 등 이상 소견 탐지
# 빌드: docker build -t ecg-svc .
# ──────────────────────────────────────────────────────────────

# 베이스 이미지 — Python 3.11 경량 이미지
FROM python:3.11-slim

WORKDIR /app

# ── Docker 캐시 최적화 전략 ──────────────────────────────────
# requirements.txt를 먼저 복사하여 의존성 레이어를 캐시
# 소스코드만 변경 시 pip install 단계를 재실행하지 않아 빌드 속도 향상
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 공유 스키마 복사 — 서비스 간 공통 데이터 모델
COPY ../shared /app/shared

# 서비스 소스코드 복사
COPY . .

# 서비스 포트 — 모든 마이크로서비스가 내부적으로 8000번 포트 사용
EXPOSE 8000

# K8s 리소스 힌트 (실제 제한은 K8s manifest에서 적용)
# CPU: 500m, Memory: 1Gi
# Resource hints (enforced by K8s limits, documented here)

# ── 헬스체크 ─────────────────────────────────────────────────
# 15초 간격으로 /healthz 엔드포인트 호출하여 서비스 상태 확인
# Docker Compose 및 K8s의 readinessProbe 역할
HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"

# ── 서버 실행 ────────────────────────────────────────────────
# uvicorn ASGI 서버로 FastAPI 앱 실행
# workers=1: 단일 워커 (K8s HPA로 수평 스케일링)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
