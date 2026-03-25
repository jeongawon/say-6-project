"""
ecg-svc — 12-lead ECG analysis microservice (K8s 12-Factor).
12-리드 심전도 분석 마이크로서비스.

Endpoints:
  GET  /healthz  — liveness probe (생존 확인)
  GET  /readyz   — readiness probe (준비 상태 확인)
  POST /predict  — ECG analysis (ECG 분석 요청)

central-orchestrator에서 호출되며, 분석 결과와 소견서를 반환합니다.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

# shared 스키마 경로 설정 (Docker 컨테이너 내 /app/shared 참조)
import sys
sys.path.insert(0, "/app/shared")
from schemas import PredictRequest, PredictResponse, Finding, PatientInfo

from fastapi import FastAPI, HTTPException
from config import settings                           # 환경변수 설정 로드
from analyzer import analyze_ecg                       # ECG 분석 엔진
from report.ecg_report_generator import generate_ecg_report  # 소견서 생성기

# ── Logging (로깅 설정) ──────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(settings.service_name)


# ── Readiness state (서비스 준비 상태 플래그) ─────────────────────────
_ready = False


# ── Lifespan (서비스 생명주기 관리) ──────────────────────────────────
# 서비스 시작 시 초기화, 종료 시 정리 작업을 수행합니다.
# TODO: ML 모델 도입 시 여기서 모델 로딩을 수행하세요.
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ready
    logger.info("Starting %s (port=%s)", settings.service_name, settings.port)
    # 현재는 규칙 기반이므로 별도 모델 로딩 없음
    _ready = True
    logger.info("%s is ready", settings.service_name)
    yield
    # 종료 처리
    _ready = False
    logger.info("%s shut down", settings.service_name)


# FastAPI 애플리케이션 인스턴스 생성
app = FastAPI(
    title="ecg-svc",
    version="3.0.0",
    lifespan=lifespan,
)


# ── Health probes (K8s 헬스체크 엔드포인트) ──────────────────────────
@app.get("/healthz")
def healthz():
    """Liveness probe — 서비스가 살아있는지 확인 (항상 200 반환)"""
    return {"status": "alive"}


@app.get("/readyz")
def readyz():
    """Readiness probe — 서비스가 요청을 받을 준비가 됐는지 확인"""
    if not _ready:
        raise HTTPException(status_code=503, detail="not ready")
    return {"status": "ready"}


# ── Predict (ECG 분석 엔드포인트) ────────────────────────────────────
@app.post("/predict", response_model=PredictResponse)
async def predict(req: PredictRequest):
    """
    ECG 분석 메인 엔드포인트.

    처리 흐름:
      1) analyzer.py의 규칙 기반 분석 실행 → findings 목록 생성
      2) 이상 소견 요약(summary) 문자열 구성
      3) Bedrock(LLM)을 호출하여 한국어 소견서 생성 (실패 시 템플릿 폴백)
      4) PredictResponse 반환
    """
    if not _ready:
        raise HTTPException(status_code=503, detail="Service not ready")

    start = time.time()

    try:
        # 1단계: 규칙 기반 ECG 분석 — 8개 모듈(심박수, 리듬, PR, QRS 등) 실행
        findings = analyze_ecg(req.data, req.patient_info)

        # 2단계: 이상 소견 요약 문자열 생성
        detected = [f for f in findings if f.detected]
        if detected:
            summary_parts = [
                f"{f.name.replace('_', ' ')} ({f.confidence:.0%})"
                for f in detected
            ]
            summary = "ECG findings: " + ", ".join(summary_parts)
        else:
            summary = "Normal ECG — no significant abnormalities detected."

        # 3단계: 소견서 생성 (Bedrock LLM 호출, 실패 시 템플릿으로 대체)
        report = await generate_ecg_report(
            patient_info=req.patient_info,
            findings=findings,
            bedrock_region=settings.bedrock_region,
            bedrock_model_id=settings.bedrock_model_id,
            context=req.context if req.context else None,  # 이전 모달리티(CXR 등) 결과
        )

        elapsed_ms = int((time.time() - start) * 1000)
        logger.info(
            "patient=%s findings=%d detected=%d time=%dms",
            req.patient_id, len(findings), len(detected), elapsed_ms,
        )

        # 4단계: 응답 반환
        return PredictResponse(
            status="success",
            modal="ecg",                # 모달리티 식별자
            findings=findings,          # 개별 분석 결과 목록
            summary=summary,            # 요약 문자열
            report=report,              # 한국어 소견서 전문
            metadata={
                "service": settings.service_name,
                "version": "3.0.0",
                "inference_time_ms": elapsed_ms,
                "analysis_type": "rule-based",  # 향후 "ml-model"로 변경
            },
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Prediction failed for patient %s", req.patient_id)
        raise HTTPException(status_code=500, detail=str(exc))
