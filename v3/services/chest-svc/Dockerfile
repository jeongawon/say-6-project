# ── chest-svc Docker 이미지 ──────────────────────────────────
# 흉부 X-Ray 6-Layer 파이프라인 서비스
# ONNX Runtime으로 3개 모델 추론 (UNet 폐 분할 + DenseNet 질병 분류 + YOLO 이상 탐지)
# 빌드: docker build -t chest-svc .
# ──────────────────────────────────────────────────────────────

# 베이스 이미지 — Python 3.11 경량 이미지 (slim으로 이미지 크기 최소화)
# Build context: v3/ (docker build -f services/chest-svc/Dockerfile .)
FROM python:3.11-slim

# 시스템 의존성 설치 — libgomp1은 ONNX Runtime의 OpenMP 병렬 처리에 필요
# apt 캐시 삭제로 이미지 크기 최소화
RUN apt-get update && \
    apt-get install -y --no-install-recommends libgomp1 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Docker 캐시 최적화 전략 ──────────────────────────────────
# requirements.txt를 먼저 복사하여 의존성 레이어를 캐시
# 소스코드만 변경 시 pip install 단계를 재실행하지 않아 빌드 속도 향상
COPY services/chest-svc/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 공유 스키마 복사 — 서비스 간 공통 데이터 모델 (Pydantic 스키마 등)
COPY shared/ /app/shared/

# 서비스 소스코드 복사
COPY services/chest-svc/ /app/

# ── 환경변수 설정 ────────────────────────────────────────────
# MODEL_DIR: ONNX 모델 파일 경로 (K8s에서는 PVC로 마운트)
ENV MODEL_DIR=/app/models
# LOG_LEVEL: 로깅 수준 (DEBUG/INFO/WARNING/ERROR)
ENV LOG_LEVEL=INFO

# 서비스 포트 — 모든 마이크로서비스가 내부적으로 8000번 포트 사용
EXPOSE 8000

# ── 서버 실행 ────────────────────────────────────────────────
# uvicorn ASGI 서버로 FastAPI 앱 실행
# workers=1: CPU 1코어 Pod 기준 단일 워커 (K8s HPA로 수평 스케일링)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
