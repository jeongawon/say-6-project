"""
central-orchestrator — FastAPI 진입점.

LLM 기반 순차 검사 오케스트레이터.
환자 도착 → Bedrock에 다음 검사 질의 → 모달 호출 → 결과 누적 → 반복 → 종합 소견서.

K8s 12-Factor:
- pydantic-settings 기반 env 설정 (config.py)
- /healthz (liveness) + /readyz (readiness)
- FastAPI lifespan 으로 DB + Redis 연결 관리
"""

import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any, Optional

import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import settings          # 환경 변수 설정 (pydantic-settings)
from db import close_pool, create_pool  # DB 연결 풀 생성/종료
from orchestrator import run_sequential_exam  # 핵심 순차 검사 루프

# ── 로깅 설정 ─────────────────────────────────────────────────────────
# settings.log_level 환경 변수로 로그 레벨을 동적으로 제어
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("orchestrator.main")


# ── 애플리케이션 상태 (lifespan 중 설정) ──────────────────────────────
# DB 커넥션 풀과 Redis 클라이언트를 앱 전역에서 공유하기 위한 상태 객체
class AppState:
    db_pool = None          # asyncpg 커넥션 풀 (PostgreSQL)
    redis_client = None     # redis.asyncio 클라이언트 (세션 캐시)
    ready: bool = False     # Readiness 프로브에서 사용하는 플래그


app_state = AppState()


# ── Lifespan: DB + Redis 초기화/정리 ──────────────────────────────────
# FastAPI의 lifespan 컨텍스트 매니저를 사용하여
# 서버 시작 시 DB/Redis 연결, 종료 시 정리를 수행합니다.
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: DB + Redis 연결. Shutdown: 연결 정리."""
    logger.info("Starting central-orchestrator...")

    # ── PostgreSQL 커넥션 풀 생성 ──
    # asyncpg 기반 비동기 커넥션 풀. 테이블 자동 생성 포함.
    try:
        app_state.db_pool = await create_pool()
        logger.info("PostgreSQL connection pool established.")
    except Exception as e:
        logger.error("Failed to connect to PostgreSQL: %s", e)
        raise

    # ── Redis 연결 ──
    # 세션 캐시 및 실시간 상태 관리용.
    # decode_responses=True로 설정하여 bytes 대신 str로 반환.
    try:
        app_state.redis_client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=5,
            retry_on_timeout=True,
        )
        await app_state.redis_client.ping()  # 연결 확인
        logger.info("Redis connection established.")
    except Exception as e:
        logger.error("Failed to connect to Redis: %s", e)
        raise

    app_state.ready = True  # Readiness 프로브 활성화
    logger.info("central-orchestrator ready.")

    yield  # ← 이 시점부터 요청을 처리합니다

    # ── Shutdown: 연결 정리 ──
    logger.info("Shutting down central-orchestrator...")
    app_state.ready = False

    if app_state.redis_client:
        await app_state.redis_client.close()
        logger.info("Redis connection closed.")

    if app_state.db_pool:
        await close_pool(app_state.db_pool)

    logger.info("central-orchestrator shutdown complete.")


# ── FastAPI 앱 인스턴스 생성 ──────────────────────────────────────────
# lifespan 파라미터로 DB/Redis 생명주기를 관리합니다.
app = FastAPI(
    title="central-orchestrator",
    description="LLM-driven sequential medical examination orchestrator",
    version="3.0.0",
    lifespan=lifespan,
)


# ── 테스트 UI (시스템 통합 테스트 페이지) ────────────────────────────
# static/ 폴더는 tests/v3/central-orchestrator/static/ 에서 관리
# docker-compose 볼륨 마운트로 /app/static에 연결됨
_static_dir = os.path.join(os.path.dirname(__file__), "static")


@app.get("/", response_class=HTMLResponse)
def test_ui():
    """GET / → 테스트 UI (static/ 있으면) 또는 API 상태 페이지"""
    html_path = os.path.join(_static_dir, "index.html")
    if os.path.exists(html_path):
        with open(html_path) as f:
            return f.read()
    return "<h1>central-orchestrator</h1><p>API running. Test UI available via docker-compose.</p>"


# ── ECG testdata 경로 제공 (테스트 UI에서 ecg-svc signal_path 구성용) ──
# ecg-svc가 /models/testdata/ 에서 .npy 파일을 읽음 (PV 마운트 기준)
# 로컬 테스트 시에는 절대 경로로 폴백
_ecg_testdata_candidates = [
    "/models/testdata",  # K8s — ecg-svc의 /models subPath 내 testdata
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "tests", "v3", "ecg-svc", "testdata"),
]
_ecg_testdata_dir = next((p for p in _ecg_testdata_candidates if os.path.isdir(os.path.realpath(p))),
                         "/models/testdata")


@app.get("/ecg-testdata-path")
def ecg_testdata_path():
    """테스트 UI에서 ECG signal_path 구성에 사용할 경로 반환 (ecg-svc 기준)."""
    return {"path": os.path.realpath(_ecg_testdata_dir)}


# ── 테스트 데이터 static 서빙 ──────────────────────────────────────
_testdata_dir = os.path.join(_static_dir, "testdata")
if os.path.isdir(_testdata_dir):
    app.mount("/testdata", StaticFiles(directory=_testdata_dir), name="testdata")


# ── 정적 파일 서빙 (반드시 라우트 정의 후 마지막에) ──────────────────
# docker-compose에서 tests/v3/central-orchestrator/static/ → /app/static 볼륨 마운트 시 활성화
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir, follow_symlink=True), name="static")


# ── 요청/응답 모델 ───────────────────────────────────────────────────

# 환자 기본 정보 스키마
class PatientInfo(BaseModel):
    age: int                        # 나이
    sex: str                        # 성별 (M/F)
    chief_complaint: str            # 주호소 (예: "흉통 및 호흡곤란")
    history: list[str] = []         # 병력 (예: ["고혈압", "당뇨"])


# POST /examine 요청 스키마
class ExamRequest(BaseModel):
    patient_id: str                 # 환자 고유 식별자
    patient_info: PatientInfo       # 환자 기본 정보
    data: dict = {}                 # 모달별 입력 데이터 (키: 모달명, 값: 해당 모달 데이터)


# POST /examine 응답 스키마
class ExamResponse(BaseModel):
    status: str                     # 처리 상태 ("success" / "error")
    patient_id: str                 # 환자 ID
    session_id: Optional[int] = None  # 세션 ID (DB 자동 생성)
    exams_performed: list[str]      # 수행된 검사 목록 (예: ["chest", "ecg"])
    modal_reports: list[dict]       # 각 모달 검사 결과 리스트
    exam_decisions: list[dict] = [] # Bedrock의 검사 결정 이력
    final_report: str               # 종합 소견서
    diagnosis: str                  # 최종 진단
    metadata: dict = {}             # 메타 정보 (소요 시간, 검사 수 등)


# ── 헬스체크 엔드포인트 ──────────────────────────────────────────────
# K8s liveness/readiness 프로브 용도

@app.get("/healthz", tags=["health"])
async def healthz():
    """Liveness 프로브 — 프로세스 생존 여부만 확인. 항상 200 반환."""
    return {"status": "alive"}


@app.get("/readyz", tags=["health"])
async def readyz():
    """Readiness 프로브 — DB + Redis 모두 연결된 경우에만 200 반환."""
    checks = {"db": False, "redis": False}

    # DB 연결 확인: SELECT 1로 간단한 쿼리 실행
    if app_state.db_pool:
        try:
            async with app_state.db_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            checks["db"] = True
        except Exception as e:
            logger.warning("Readiness DB check failed: %s", e)

    # Redis 연결 확인: PING 명령
    if app_state.redis_client:
        try:
            await app_state.redis_client.ping()
            checks["redis"] = True
        except Exception as e:
            logger.warning("Readiness Redis check failed: %s", e)

    all_ready = all(checks.values())

    # 하나라도 실패하면 503 반환 → K8s가 트래픽을 보내지 않음
    if not all_ready:
        raise HTTPException(status_code=503, detail={"status": "not_ready", "checks": checks})

    return {"status": "ready", "checks": checks}


# ── 핵심 엔드포인트: 순차 검사 실행 ──────────────────────────────────

@app.post("/examine", response_model=ExamResponse, tags=["examination"])
async def examine(req: ExamRequest):
    """
    LLM 기반 순차 검사 실행 엔드포인트.

    처리 흐름:
    1. Bedrock이 환자 정보 + 누적 결과를 보고 다음 검사를 결정
    2. 해당 모달 서비스(chest/ecg/blood-svc)를 호출하여 예측 수행
    3. 결과를 누적하고 다시 Bedrock에게 질의 (반복)
    4. Bedrock이 DONE을 반환하거나 최대 반복 횟수 도달 시 종료
    5. report-svc를 통해 종합 소견서 생성
    """
    # 서비스가 아직 준비되지 않은 경우 503 반환
    if not app_state.ready:
        raise HTTPException(status_code=503, detail="Service not ready")

    logger.info(
        "Exam request: patient_id=%s, chief_complaint=%s",
        req.patient_id,
        req.patient_info.chief_complaint,
    )

    try:
        # orchestrator.py의 핵심 순차 루프 실행
        result = await run_sequential_exam(
            patient_id=req.patient_id,
            patient_info=req.patient_info.model_dump(),  # Pydantic → dict 변환
            data=req.data,
            db_pool=app_state.db_pool,
            redis_client=app_state.redis_client,
        )

        return ExamResponse(**result)

    except Exception as e:
        logger.exception("Examination failed for patient %s: %s", req.patient_id, e)
        raise HTTPException(
            status_code=500,
            detail=f"Examination failed: {e}",
        )
