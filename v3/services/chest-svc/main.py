"""
chest-svc — FastAPI + lifespan (ONNX 3 model loading) + /healthz + /readyz + /predict.

K8s 12-Factor 마이크로서비스:
  - pydantic-settings 기반 환경변수 관리
  - lifespan으로 ONNX 모델 startup/shutdown
  - /healthz (liveness) + /readyz (readiness) 헬스체크
  - 6-stage sequential pipeline (seg -> densenet -> yolo -> clinical -> rag -> report)
"""

# ── 표준 라이브러리 임포트 ────────────────────────────────────
import sys
import logging
from contextlib import asynccontextmanager

# ── 프레임워크 임포트 ─────────────────────────────────────────
import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

# ── 공유 스키마 (Docker 환경에서 /app/shared/ 에 복사됨) ──────
# PredictRequest: 오케스트레이터가 보내는 요청 형식
# PredictResponse: 오케스트레이터에 반환하는 응답 형식
# Finding: 개별 질환 탐지 결과 스키마
sys.path.insert(0, "/app/shared")
from schemas import PredictRequest, PredictResponse, Finding

# ── 내부 모듈 임포트 ──────────────────────────────────────────
from config import settings                            # 환경변수 설정
from pipeline import run_pipeline                      # 6-stage 파이프라인 실행 함수
from report.chest_report_generator import ChestReportGenerator  # Bedrock 소견서 생성기

# ── 로깅 설정 ─────────────────────────────────────────────────
# LOG_LEVEL 환경변수로 로그 레벨 제어 (기본: INFO)
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
logger = logging.getLogger("chest-svc")

# ── 글로벌 상태 ───────────────────────────────────────────────
# ready: 모델 로딩 완료 여부 (readiness probe에서 사용)
# models: ONNX 세션 3개를 저장하는 딕셔너리
# report_generator: Bedrock Claude 소견서 생성기 인스턴스
state = {"ready": False, "models": {}, "report_generator": None}


# ── 모델 로딩 (Pod 시작 시 1회) ──────────────────────────────
# ONNX 모델 3개를 메모리에 올림. 변경 시 model_dir 환경변수 수정
# Pod이 종료될 때 자동으로 메모리 해제됨
@asynccontextmanager
async def lifespan(app: FastAPI):
    """ONNX 모델 3개 startup 로딩, shutdown 정리."""
    import onnxruntime as ort

    logger.info(f"Loading ONNX models from {settings.model_dir} ...")

    # ── ONNX Runtime 세션 옵션 ────────────────────────────────
    # K8s Pod 스펙: CPU 1 core, 메모리 2Gi
    # inter_op: 연산자 간 병렬 스레드 수
    # intra_op: 연산자 내부 병렬 스레드 수
    sess_options = ort.SessionOptions()
    sess_options.inter_op_num_threads = 1
    sess_options.intra_op_num_threads = 2
    sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

    providers = ["CPUExecutionProvider"]

    # ── 모델 1: UNet 세그멘테이션 (~85MB) ─────────────────────
    # 입력: (1, 1, 320, 320) grayscale
    # 출력: 세그멘테이션 마스크 + 촬영 뷰 + 나이/성별 예측
    logger.info("Loading unet.onnx ...")
    state["models"]["unet"] = ort.InferenceSession(
        f"{settings.model_dir}/unet.onnx",
        sess_options=sess_options,
        providers=providers,
    )
    logger.info(f"  unet inputs: {[i.name for i in state['models']['unet'].get_inputs()]}")

    # ── 모델 2: DenseNet-121 14-질환 분류 (~27MB) ─────────────
    # 입력: (1, 3, 224, 224) RGB ImageNet 정규화
    # 출력: 14개 질환 logits -> sigmoid -> 확률
    logger.info("Loading densenet.onnx ...")
    state["models"]["densenet"] = ort.InferenceSession(
        f"{settings.model_dir}/densenet.onnx",
        sess_options=sess_options,
        providers=providers,
    )
    logger.info(f"  densenet inputs: {[i.name for i in state['models']['densenet'].get_inputs()]}")

    # ── 모델 3: YOLOv8 19-클래스 물체 탐지 (~22MB) ────────────
    # 입력: (1, 3, 1024, 1024) RGB letterbox
    # 출력: 바운딩박스 + 클래스 확률 (VinDr-CXR 19 클래스)
    logger.info("Loading yolov8.onnx ...")
    state["models"]["yolo"] = ort.InferenceSession(
        f"{settings.model_dir}/yolov8.onnx",
        sess_options=sess_options,
        providers=providers,
    )
    logger.info(f"  yolo inputs: {[i.name for i in state['models']['yolo'].get_inputs()]}")

    # ── 소견서 생성기 초기화 (Bedrock 클라이언트) ──────────────
    state["report_generator"] = ChestReportGenerator()

    state["ready"] = True
    logger.info("All models loaded. chest-svc is ready.")

    yield

    # ── Shutdown: 리소스 정리 ──────────────────────────────────
    logger.info("Shutting down chest-svc ...")
    state["models"].clear()
    state["ready"] = False


# ── FastAPI 앱 인스턴스 생성 ───────────────────────────────────
app = FastAPI(
    title="chest-svc",
    description="Chest X-ray AI analysis microservice (v3)",
    version="3.0.0",
    lifespan=lifespan,  # Pod 시작/종료 시 모델 로드/해제
)

# ── 테스트 UI (v1 스타일 시각화 페이지) ────────────────────────
@app.get("/", response_class=HTMLResponse)
def test_ui():
    """GET / → v1 스타일 시각화 테스트 페이지"""
    html_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    with open(html_path) as f:
        return f.read()


# ── 헬스체크 엔드포인트 (K8s probe 용) ────────────────────────
@app.get("/healthz")
def liveness():
    """Liveness probe — 프로세스 생존 확인. K8s가 주기적으로 호출."""
    return {"status": "ok"}


@app.get("/readyz")
def readiness():
    """Readiness probe — 모델 로딩 완료 확인. 503이면 트래픽 라우팅 안 됨."""
    if not state["ready"]:
        raise HTTPException(status_code=503, detail="models loading")
    return {"status": "ready", "models": list(state["models"].keys())}


# ── 메인 예측 엔드포인트 ───────────────────────────────────────
# central-orchestrator가 호출하는 핵심 API
# 흉부 X선 이미지를 받아 6-stage 파이프라인을 실행하고 소견서를 반환
@app.post("/predict", response_model=PredictResponse)
async def predict(req: PredictRequest):
    """
    흉부 X선 AI 분석 파이프라인.

    6-stage: segmentation -> densenet -> yolo -> clinical logic -> rag -> report
    """
    # ── 서비스 준비 상태 확인 ──────────────────────────────────
    if not state["ready"]:
        raise HTTPException(status_code=503, detail="Service not ready")

    # ── 요청 데이터 추출 및 검증 ──────────────────────────────
    # data.image_base64: base64 인코딩된 흉부 X선 이미지 (필수)
    image_b64 = req.data.get("image_base64", "")
    if not image_b64:
        raise HTTPException(status_code=400, detail="'image_base64' is required in data")

    # 환자 정보를 dict로 변환 (파이프라인에서 사용)
    patient_info = {
        "age": req.patient_info.age,
        "sex": req.patient_info.sex,
        "chief_complaint": req.patient_info.chief_complaint,
        "history": req.patient_info.history,
    }

    # ── 6-stage 파이프라인 실행 ───────────────────────────────
    # pipeline.py의 run_pipeline()이 전체 분석 수행
    try:
        result = await run_pipeline(
            models=state["models"],
            image_b64=image_b64,
            patient_info=patient_info,
            context=req.context,
            report_generator=state["report_generator"],
        )
    except Exception as e:
        logger.error(f"Pipeline error for patient {req.patient_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Pipeline error: {str(e)}")

    # ── 응답 변환 (내부 dict -> PredictResponse 스키마) ────────
    findings = [
        Finding(
            name=f["name"],
            detected=f["detected"],
            confidence=f["confidence"],
            detail=f.get("detail", ""),
        )
        for f in result["findings"]
    ]

    return PredictResponse(
        status="success",
        modal="chest",
        findings=findings,
        summary=result["summary"],
        report=result.get("report", ""),
        risk_level=result.get("risk_level", "routine"),
        pertinent_negatives=result.get("pertinent_negatives", []),
        suggested_next_actions=result.get("suggested_next_actions", []),
        metadata=result.get("metadata", {}),
    )


# ── 정적 파일 서빙 (반드시 라우트 정의 후 마지막에) ──────────
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")
