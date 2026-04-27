# ── Backend Dockerfile ─────────────────────────────────────
# AWS ECS / ECR 배포용 (linux/amd64)
FROM python:3.11-slim

# 빌드 도구 설치 후 캐시 제거
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성 먼저 설치 (레이어 캐시 최적화)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 앱 소스 복사
COPY app/ ./app/

# 모델 파일 복사 (빌드 시 포함)
COPY final_models.pkl .

EXPOSE 8000

# 헬스체크 (ECS Task 상태 확인용)
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
