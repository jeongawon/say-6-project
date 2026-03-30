import os
import boto3
import numpy as np
import tempfile
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from mangum import Mangum

from app.schemas import PredictRequest, PredictResponse, PatientInfo, ECGData, SimulateRequest
from app.model_loader import get_session
from app.inference import run_inference

# ── MIMIC S3 설정 ──────────────────────────────────────────
MIMIC_BUCKET = os.environ.get("MIMIC_BUCKET", "say2-6team")
MIMIC_PREFIX = os.environ.get("MIMIC_PREFIX", "mimic-iv")   # 버킷 내 폴더
SIGNAL_PREFIX = "mimic/ecg/signals"                          # {study_id}.npy 저장 위치

_mimic_cache: dict[str, pd.DataFrame] = {}


def _read_csv_from_s3(key: str) -> pd.DataFrame:
    """S3에서 CSV 읽기 (Lambda 수명 내 캐시)"""
    if key not in _mimic_cache:
        s3  = boto3.client("s3")
        obj = s3.get_object(Bucket=MIMIC_BUCKET, Key=key)
        _mimic_cache[key] = pd.read_csv(obj["Body"])
    return _mimic_cache[key]

app = FastAPI(title="ecg-svc", version="1.0.0")

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

@app.get("/", include_in_schema=False)
def ui():
    return FileResponse(os.path.join(_STATIC_DIR, "index.html"))


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


@app.post("/simulate", response_model=PredictResponse)
def simulate(req: SimulateRequest):
    subject_id = req.subject_id
    chief_complaint = req.chief_complaint
    """
    subject_id → MIMIC 조회 → ECG 추론

    흐름:
      1. patients.csv     → age, sex
      2. vitalsign.csv    → HR, BP, SpO2, RR, Temp
      3. record_list.csv  → study_id (최신 ECG)
      4. signals/{study_id}.npy → (12, 5000) 파형
      5. run_inference()  → PredictResponse
    """
    # 1. patient_info
    patients = _read_csv_from_s3(f"{MIMIC_PREFIX}/hosp/patients.csv")
    pt = patients[patients["subject_id"] == subject_id]
    if pt.empty:
        raise HTTPException(status_code=404, detail=f"subject_id {subject_id} 없음")
    pt = pt.iloc[0]
    age = int(pt["anchor_age"])
    sex = str(pt["gender"])

    # 2. vitals (없으면 빈값)
    vitals: dict = {}
    try:
        vs_df = _read_csv_from_s3(f"{MIMIC_PREFIX}/ed/vitalsign.csv")
        vs_rows = vs_df[vs_df["subject_id"] == subject_id].dropna(how="all")
        if not vs_rows.empty:
            v = vs_rows.iloc[-1]
            if pd.notna(v.get("temperature")):
                vitals["temperature"] = float(v["temperature"])
            if pd.notna(v.get("sbp")) and pd.notna(v.get("dbp")):
                vitals["blood_pressure"] = f"{int(v['sbp'])}/{int(v['dbp'])}"
            if pd.notna(v.get("spo2")):
                vitals["spo2"] = float(v["spo2"])
            if pd.notna(v.get("resprate")):
                vitals["respiratory_rate"] = int(v["resprate"])
    except Exception:
        pass  # vitalsign 없으면 스킵

    # 3. ECG record → study_id
    rec = _read_csv_from_s3(f"{MIMIC_PREFIX}/mimic_iv_ecg/record_list.csv")
    ecg_rows = rec[rec["subject_id"] == subject_id]
    if ecg_rows.empty:
        raise HTTPException(status_code=404, detail=f"subject_id {subject_id}의 ECG 없음")
    if "ecg_time" in ecg_rows.columns:
        ecg_rows = ecg_rows.sort_values("ecg_time")
    study_id = str(ecg_rows.iloc[-1]["study_id"])

    # 4. 파형 로드
    signal_s3_path = f"s3://{MIMIC_BUCKET}/{SIGNAL_PREFIX}/{study_id}.npy"
    try:
        signal = _load_signal_from_s3(signal_s3_path)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"파형 로드 실패 ({study_id}.npy): {e}")

    # 5. 추론
    predict_req = PredictRequest(
        patient_id   = str(subject_id),
        patient_info = PatientInfo(
            age=age, sex=sex,
            chief_complaint=chief_complaint,
            **vitals,
        ),
        data    = ECGData(signal_path=signal_s3_path, leads=12),
        context = req.context,
    )
    return run_inference(signal, predict_req, get_session())


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
