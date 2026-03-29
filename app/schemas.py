from pydantic import BaseModel
from typing import List, Optional


class PatientInfo(BaseModel):
    age: int
    sex: str
    chief_complaint: str
    history: List[str] = []
    # 활력징후 — Optional (오케스트레이터가 있을 때만 전달)
    temperature: Optional[float] = None
    blood_pressure: Optional[str] = None
    spo2: Optional[float] = None
    respiratory_rate: Optional[int] = None


class ECGData(BaseModel):
    signal_path: Optional[str] = None   # S3 경로 (운영)
    leads: int = 12


class PredictRequest(BaseModel):
    patient_id: str
    patient_info: Optional[PatientInfo] = None
    data: ECGData
    context: dict = {}


class Finding(BaseModel):
    name: str
    detected: bool
    confidence: float
    detail: str = ""
    severity: Optional[str] = None       # mild / moderate / severe / critical
    recommendation: Optional[str] = None


class SimulateRequest(BaseModel):
    subject_id: int
    chief_complaint: str = ""
    context: dict = {}


class PredictResponse(BaseModel):
    status: str
    modal: str = "ecg"
    findings: List[Finding] = []
    summary: str = ""
    report: str = ""                     # ECG 소견서 (impression)
    risk_level: str = "routine"          # routine / urgent / critical
    pertinent_negatives: List[str] = []       # 주소증 관련 음성 소견
    suggested_next_actions: List[dict] = []   # 다음 모달 호출 추천
    metadata: dict = {}
    error: Optional[str] = None
