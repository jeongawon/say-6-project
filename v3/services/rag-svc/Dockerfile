# ── rag-svc Docker 이미지 ────────────────────────────────────
# RAG (Retrieval-Augmented Generation) 서비스
# FAISS 벡터DB + 의학 문헌 검색으로 LLM 응답 품질 향상
# 빌드: docker build -f services/rag-svc/Dockerfile -t rag-svc .
# ──────────────────────────────────────────────────────────────

# 베이스 이미지 — Python 3.11 경량 이미지
FROM python:3.11-slim

WORKDIR /app

# 시스템 의존성 설치 — build-essential은 FAISS 등 C 확장 모듈 빌드에 필요
# apt 캐시 삭제로 이미지 크기 최소화
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# ── Docker 캐시 최적화 전략 ──────────────────────────────────
# requirements.txt를 먼저 복사하여 의존성 레이어를 캐시
# 소스코드만 변경 시 pip install 단계를 재실행하지 않아 빌드 속도 향상
COPY services/rag-svc/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# FastEmbed 모델 프리캐시 — 런타임에 인터넷 접근 불필요
# bge-small-en-v1.5 양자화 ONNX 모델 (~67MB) 다운로드
RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5')"

# 공유 스키마 복사 — 서비스 간 공통 데이터 모델 (빌드 컨텍스트에서)
COPY shared/ /app/shared/

# 서비스 소스코드 복사
COPY services/rag-svc/ /app/

# 모델 디렉토리 생성 — K8s PVC 마운트 포인트 (FAISS 인덱스/임베딩 모델)
RUN mkdir -p /models

# 서비스 포트 — 모든 마이크로서비스가 내부적으로 8000번 포트 사용
EXPOSE 8000

# K8s 리소스 힌트 (실제 제한은 K8s manifest에서 적용)
# readinessProbe initialDelaySeconds: 15 — FAISS 인덱스 + 임베딩 모델 로딩 시간 고려
# CPU: 500m, Memory: 1Gi — 벡터 검색 연산에 리소스 필요

# ── 서버 실행 ────────────────────────────────────────────────
# uvicorn ASGI 서버로 FastAPI 앱 실행
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
