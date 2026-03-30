"""
report-svc — Bedrock Claude 종합 소견서 생성 마이크로서비스.
K8s 12-Factor: pydantic-settings, lifespan, /healthz, /readyz.

[서비스 역할]
- 3개 모달(chest, ecg, blood) 분석 결과를 종합하여 최종 진단 보고서 생성
- AWS Bedrock Claude를 사용하여 자연어 서술형 종합 판독문 생성
- RAG 유사 케이스를 참고 근거로 프롬프트에 삽입 가능
- central-orchestrator에서 모든 모달 분석 완료 후 마지막 단계로 호출
"""
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

# shared schemas (Docker에서 /app/shared로 마운트)
# 로컬 개발 시에는 심볼릭 링크 또는 sys.path 수정 필요
sys.path.insert(0, "/app/shared")
from schemas import ReportRequest, ReportResponse  # noqa: E402

from config import settings  # noqa: E402
from report_generator import ReportGenerator  # noqa: E402

# 로깅 설정 — 타임스탬프 + 서비스명 + 레벨 + 메시지 포맷
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("report-svc")

# 전역 서비스 인스턴스 — lifespan에서 초기화
generator: ReportGenerator | None = None
# 서비스 준비 상태 플래그 — readyz 프로브에서 사용
_ready = False


# ------------------------------------------------------------------
# Lifespan — startup/shutdown
# FastAPI의 lifespan 패턴: 서버 시작 시 Bedrock 클라이언트 초기화
# ------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """startup: Bedrock 클라이언트 초기화."""
    global generator, _ready
    logger.info("report-svc 시작 — Bedrock 클라이언트 초기화 중...")
    logger.info(
        "region=%s, model_id=%s",
        settings.bedrock_region,
        settings.bedrock_model_id,
    )
    try:
        # Bedrock 클라이언트(boto3) 초기화 — AWS 자격 증명 필요
        generator = ReportGenerator()
        _ready = True
        logger.info("report-svc 준비 완료")
    except Exception:
        # 초기화 실패해도 서버는 기동 — readyz에서 503 반환
        logger.exception("report-svc 초기화 실패")
    yield
    logger.info("report-svc 종료")


# FastAPI 앱 인스턴스 생성
app = FastAPI(
    title="report-svc",
    version="1.0.0",
    description="Bedrock Claude 종합 소견서 생성 서비스",
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
    """Readiness probe — Bedrock 클라이언트 초기화 완료 확인."""
    if not _ready:
        raise HTTPException(status_code=503, detail="Bedrock client not initialized")
    return {"status": "ready", "model_id": settings.bedrock_model_id}


# ------------------------------------------------------------------
# API — 종합 소견서 생성 엔드포인트
# ------------------------------------------------------------------
@app.post("/generate", response_model=ReportResponse)
def generate(req: ReportRequest):
    """
    종합 소견서 생성.

    - patient_id: 환자 ID
    - patient_info: 환자 정보 (age, sex, chief_complaint, history)
    - modal_reports: 각 모달의 분석 결과 리스트

    central-orchestrator가 3개 모달 분석 완료 후 이 엔드포인트를 호출하여
    Bedrock Claude로 종합 진단 보고서를 생성합니다.
    """
    if not _ready or generator is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    try:
        # ReportGenerator.generate()로 Bedrock 호출 + 보고서 생성
        result = generator.generate(
            patient_id=req.patient_id,
            patient_info=req.patient_info.model_dump(),  # Pydantic 모델 → dict 변환
            modal_reports=req.modal_reports,
        )
        return ReportResponse(
            status="success",
            report=result["report"],       # 종합 판독문 텍스트
            diagnosis=result["diagnosis"],  # 진단 및 감별 진단 텍스트
        )
    except Exception as e:
        logger.exception("소견서 생성 실패: %s", str(e))
        raise HTTPException(status_code=500, detail=f"Report generation failed: {str(e)}")
