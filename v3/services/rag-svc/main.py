"""
rag-svc — FAISS + SentenceTransformer 유사 케이스 검색 마이크로서비스.
K8s 12-Factor: pydantic-settings, lifespan, /healthz, /readyz.

[서비스 역할]
- 3개 모달(chest, ecg, blood)이 공통으로 사용하는 RAG 검색 서비스
- FAISS 벡터 인덱스 + SentenceTransformer 임베딩으로 유사 케이스 검색
- central-orchestrator에서 호출하여, 검색 결과를 report-svc 프롬프트에 삽입
"""
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

# shared schemas (Docker에서 /app/shared로 마운트)
# 로컬 개발 시에는 심볼릭 링크 또는 sys.path 수정 필요
sys.path.insert(0, "/app/shared")
from schemas import RAGRequest, RAGResponse  # noqa: E402

from config import settings  # noqa: E402
from rag_service import RAGService  # noqa: E402

# 로깅 설정 — 타임스탬프 + 서비스명 + 레벨 + 메시지 포맷
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("rag-svc")

# 전역 서비스 인스턴스 — lifespan에서 load() 호출 후 사용 가능
rag_service = RAGService()


# ------------------------------------------------------------------
# Lifespan — startup/shutdown
# FastAPI의 lifespan 패턴: 서버 시작 시 FAISS 인덱스와 임베더를 미리 로드
# ------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """startup: FAISS 인덱스 + SentenceTransformer 로딩."""
    logger.info("rag-svc 시작 — FAISS 인덱스 + 임베더 로딩 중...")
    logger.info("model_dir=%s, embedder=%s", settings.model_dir, settings.embedder_model)
    try:
        # FAISS 인덱스 파일 + 메타데이터 + SentenceTransformer 모델 로드
        rag_service.load()
        logger.info("rag-svc 준비 완료")
    except Exception:
        # 초기화 실패해도 서버는 기동 — readyz에서 503 반환
        logger.exception("rag-svc 초기화 실패")
    yield
    logger.info("rag-svc 종료")


# FastAPI 앱 인스턴스 생성
app = FastAPI(
    title="rag-svc",
    version="1.0.0",
    description="FAISS + bge-small-en-v1.5 유사 케이스 검색 서비스",
    lifespan=lifespan,
)


# ------------------------------------------------------------------
# Health / Readiness probes
# K8s에서 파드 상태를 확인하는 엔드포인트
# ------------------------------------------------------------------
@app.get("/healthz")
def healthz():
    """Liveness probe — 프로세스 살아있으면 OK."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    """Readiness probe — FAISS 인덱스 + 임베더 로딩 완료 확인."""
    if not rag_service.ready:
        raise HTTPException(status_code=503, detail="FAISS index or embedder not loaded")
    # index_size: 현재 인덱스에 저장된 벡터 수 반환
    return {"status": "ready", "index_size": rag_service.index.ntotal if rag_service.index else 0}


# ------------------------------------------------------------------
# API — 유사 케이스 검색 엔드포인트
# ------------------------------------------------------------------
@app.post("/search", response_model=RAGResponse)
def search(req: RAGRequest):
    """
    유사 케이스 검색.

    - query: 검색 쿼리 텍스트 (소견, 진단명 등)
    - modal: 모달 유형 (chest, ecg, blood)
    - top_k: 반환할 결과 수 (기본 5)

    central-orchestrator가 각 모달 분석 후 이 엔드포인트를 호출하여
    유사 케이스를 검색하고, 결과를 report-svc에 전달합니다.
    """
    if not rag_service.ready:
        raise HTTPException(status_code=503, detail="Service not ready")

    # RAGService.search()로 FAISS 검색 수행
    result = rag_service.search(
        query=req.query,
        modal=req.modal,
        top_k=req.top_k,
    )
    return RAGResponse(results=result["results"])
