from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from pathlib import Path
from app.schema import BloodTestInput, PredictionResult
from app.model  import load_models, predict

models = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("모델 로딩 중...")
    models['final'] = load_models()
    print("모델 로딩 완료")
    yield
    models.clear()


app = FastAPI(
    title="혈액검사 악화 예측 API",
    description="응급실 초기 혈액검사 수치를 입력하면 6시간 후 악화 확률을 예측합니다.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {
        "status":       "ok",
        "model_loaded": 'final' in models,
        "n_models":     len(models.get('final', {})),
    }


@app.post("/predict", response_model=PredictionResult)
def predict_endpoint(input_data: BloodTestInput):
    input_dict = input_data.model_dump()
    result     = predict(models['final'], input_dict)
    return result


@app.get("/")
def root():
    return {"status": "ok", "message": "혈액검사 악화 예측 API 실행 중"}
