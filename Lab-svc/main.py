"""
Lab 서비스 FastAPI 진입점

엔드포인트:
  POST /predict  — 혈액검사 해석 요청
  GET  /health   — 헬스체크 (ALB / k8s probe)
  GET  /ready    — readiness probe
"""

import logging
import sys

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from config import HOST, PORT, LOG_LEVEL
from shared.schemas import PredictRequest, PredictResponse
from pipeline import LabPipeline

# ------------------------------------------------------------------
# 로깅 설정
# ------------------------------------------------------------------
logging.basicConfig(
    level=LOG_LEVEL.upper(),
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("lab-svc")

# ------------------------------------------------------------------
# 파이프라인 싱글톤
# ------------------------------------------------------------------
pipeline = LabPipeline()

# ------------------------------------------------------------------
# FastAPI 앱
# ------------------------------------------------------------------
app = FastAPI(
    title="Lab 혈액검사 해석 서비스",
    description="Rule Engine 기반 12개 혈액검사 수치 해석 서비스",
    version="1.0.0",
)


# ------------------------------------------------------------------
# 엔드포인트
# ------------------------------------------------------------------
@app.post("/predict", response_model=PredictResponse)
async def predict(req: PredictRequest) -> PredictResponse:
    """혈액검사 수치 해석 및 리포트 반환"""
    if not pipeline.ready:
        raise HTTPException(status_code=503, detail="서비스가 준비되지 않았습니다.")

    response = pipeline.predict(req)

    if response.status == "error":
        raise HTTPException(status_code=500, detail="내부 서버 오류")

    return response


@app.get("/health")
async def health():
    """ALB 헬스체크 — 항상 200"""
    return {"status": "healthy"}


@app.get("/ready")
async def ready():
    """Readiness probe"""
    if not pipeline.ready:
        return JSONResponse(status_code=503, content={"status": "not_ready"})
    return {"status": "ready"}


# ------------------------------------------------------------------
# 전역 예외 핸들러
# ------------------------------------------------------------------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("처리되지 않은 예외: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "내부 서버 오류"},
    )


# ------------------------------------------------------------------
# 직접 실행
# ------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=HOST,
        port=PORT,
        log_level=LOG_LEVEL.lower(),
        reload=False,
    )
