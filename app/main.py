import os
import boto3
import numpy as np
import tempfile
from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from mangum import Mangum

from app.schemas import PredictRequest, PredictResponse
from app.model_loader import get_session
from app.inference import run_inference

app = FastAPI(title="ecg-svc", version="1.0.0")


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_session()
    yield

app.router.lifespan_context = lifespan


def _load_signal_from_s3(signal_path: str) -> np.ndarray:
    """
    ECG 파형 로드 → (12, 5000) numpy array

    signal_path 예시:
      - "s3://say2-6team/test-samples/stemi.npy"  (운영)
      - "test-samples/stemi.npy"                  (로컬 개발)
    """
    if not signal_path.startswith("s3://"):
        signal = np.load(signal_path)
    else:
        path   = signal_path.replace("s3://", "")
        bucket = path.split("/")[0]
        key    = "/".join(path.split("/")[1:])

        s3 = boto3.client("s3")

        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = os.path.join(tmpdir, "signal.npy")
            s3.download_file(bucket, key, local_path)
            signal = np.load(local_path)

    # shape 보정
    if signal.shape == (5000, 12):
        signal = signal.T                        # (5000, 12) → (12, 5000)
    if signal.shape != (12, 5000):
        raise ValueError(f"지원하지 않는 신호 shape: {signal.shape}")

    if np.isnan(signal).any():
        signal = np.nan_to_num(signal, nan=0.0)

    return signal.astype(np.float32)


handler = Mangum(app)  # Lambda 핸들러


@app.get("/health")
def health():
    return {"status": "ok", "service": "ecg-svc"}


@app.post("/predict", response_model=PredictResponse)
def predict(request: PredictRequest):
    signal_path = request.data.signal_path
    if not signal_path:
        raise HTTPException(status_code=400, detail="data.signal_path가 필요합니다.")

    try:
        signal_array = _load_signal_from_s3(signal_path)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"파형 로드 실패: {e}")

    session  = get_session()
    response = run_inference(signal_array, request, session)
    return response
