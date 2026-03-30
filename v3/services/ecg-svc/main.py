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
import os
import time
from contextlib import asynccontextmanager

# shared 스키마 경로 설정 (Docker 컨테이너 내 /app/shared 참조)
import sys
sys.path.insert(0, "/app/shared")
from schemas import PredictRequest, PredictResponse, Finding, PatientInfo

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.staticfiles import StaticFiles
from config import settings                           # 환경변수 설정 로드
from analyzer import analyze_ecg                       # ECG 분석 엔진
from report.ecg_report_generator import generate_ecg_report  # 소견서 생성기
from model_loader import load_model, get_session
from inference import run_inference, load_signal

# ── Logging (로깅 설정) ──────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(settings.service_name)


# ── Readiness state (서비스 준비 상태 플래그) ─────────────────────────
_ready = False


# ── Lifespan (서비스 생명주기 관리) ──────────────────────────────────
# 서비스 시작 시 ONNX 모델 프리로드, 실패 시 규칙 기반 폴백으로 동작.
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ready
    logger.info("Starting %s (port=%s)", settings.service_name, settings.port)

    # ONNX 모델 프리로드 (model_path 설정이 있을 때만)
    if settings.model_path:
        try:
            load_model(settings.model_path)
            logger.info("ONNX model loaded: %s", settings.model_path)
        except FileNotFoundError:
            logger.warning("ONNX model not found at %s — ML inference disabled, rule-based only",
                          settings.model_path)

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
    """Readiness probe — 서비스 준비 상태 + ML 모델 상태 반환"""
    if not _ready:
        return JSONResponse({"status": "loading"}, status_code=503)
    return {
        "status": "ready",
        "ml_model": "loaded" if get_session() is not None else "unavailable",
    }


# ── 테스트 데이터 경로 (테스트 UI용) ──────────────────────────────────
_testdata_candidates = [
    "/app/testdata",
    os.path.join(os.path.dirname(__file__), "testdata"),
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "tests", "v3", "ecg-svc", "testdata"),
]
_testdata_dir = next((p for p in _testdata_candidates if os.path.isdir(os.path.realpath(p))), "/app/testdata")


@app.get("/testdata-path")
def testdata_path():
    """테스트 UI에서 사용할 testdata 절대 경로 반환."""
    return {"path": os.path.realpath(_testdata_dir)}


# ── Predict (ECG 분석 엔드포인트) ────────────────────────────────────
@app.post("/predict", response_model=PredictResponse)
async def predict(req: PredictRequest):
    """
    ECG 분석 메인 엔드포인트.

    처리 흐름:
      1) signal_path가 있고 ONNX 모델 로드됨 → ML 추론
         signal_path 없음 또는 모델 미로드 → 규칙 기반 폴백
      2) 이상 소견 요약(summary) 문자열 구성
      3) Bedrock(LLM)을 호출하여 한국어 소견서 생성 (실패 시 템플릿 폴백)
      4) PredictResponse 반환
    """
    if not _ready:
        raise HTTPException(status_code=503, detail="Service not ready")

    start = time.time()

    try:
        ecg_data = req.data

        # ML Path: signal_path가 있고 ONNX 모델이 로드되어 있으면
        if "signal_path" in ecg_data and get_session() is not None:
            signal = load_signal(ecg_data["signal_path"])
            result = run_inference(signal, req.patient_info, req.context)
            findings = result["findings"]
            risk_level = result["risk_level"]
            summary = result["summary"]
            ml_report = result["report"]
            pertinent_negs = result["pertinent_negatives"]
            next_actions = result["suggested_next_actions"]
            ml_meta = result["metadata"]
            analysis_type = "ml-model"

            # Bedrock 소견서 생성 (ML summary를 Bedrock으로 보강)
            report = await generate_ecg_report(
                patient_info=req.patient_info,
                findings=findings,
                bedrock_region=settings.bedrock_region,
                bedrock_model_id=settings.bedrock_model_id,
                context=req.context if req.context else None,
            )
        else:
            # Rule Path: 기존 규칙 기반 폴백
            findings = analyze_ecg(req.data, req.patient_info)
            risk_level = "routine"
            pertinent_negs = []
            next_actions = []
            ml_meta = {}
            analysis_type = "rule-based"

            detected = [f for f in findings if f.detected]
            if detected:
                parts = [f"{f.name} ({f.confidence:.0%})" for f in detected]
                summary = f"ECG rule-based 분석: {len(detected)}개 소견 — " + ", ".join(parts)
            else:
                summary = "Normal ECG — no significant abnormalities detected."

            report = await generate_ecg_report(
                patient_info=req.patient_info,
                findings=findings,
                bedrock_region=settings.bedrock_region,
                bedrock_model_id=settings.bedrock_model_id,
                context=req.context if req.context else None,
            )

        elapsed_ms = int((time.time() - start) * 1000)
        detected_count = len([f for f in findings if f.detected])
        logger.info(
            "patient=%s findings=%d detected=%d time=%dms analysis=%s",
            req.patient_id, len(findings), detected_count, elapsed_ms, analysis_type,
        )

        # 응답 반환
        return PredictResponse(
            status="success",
            modal="ecg",
            findings=findings,
            summary=summary,
            report=report,
            risk_level=risk_level,
            pertinent_negatives=pertinent_negs,
            suggested_next_actions=next_actions,
            metadata={
                "service": settings.service_name,
                "version": "3.0.0",
                "inference_time_ms": elapsed_ms,
                "analysis_type": analysis_type,
                **ml_meta,
            },
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Prediction failed for patient %s", req.patient_id)
        raise HTTPException(status_code=500, detail=str(exc))


# ── 테스트 UI (조건부) ────────────────────────────────────────────────
_static_dir = os.path.join(os.path.dirname(__file__), "static")


@app.get("/", response_class=HTMLResponse)
def test_ui():
    html_path = os.path.join(_static_dir, "index.html")
    if os.path.exists(html_path):
        with open(html_path) as f:
            return f.read()
    return "<h1>ecg-svc</h1><p>API running.</p>"


if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")
