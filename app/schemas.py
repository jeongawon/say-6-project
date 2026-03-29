from pydantic import BaseModel
from typing import List, Optional


class PatientInfo(BaseModel):
    age: Optional[int] = None
    sex: Optional[str] = None
    chief_complaint: Optional[str] = None
    history: Optional[List[str]] = []


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


class PredictResponse(BaseModel):
    status: str
    modal: str = "ecg"
    findings: List[Finding] = []
    summary: str = ""
    report: str = ""                     # ECG 소견서 (impression)
    risk_level: str = "routine"          # routine / urgent / critical
    pertinent_negatives: List[str] = []  # 주소증 관련 음성 소견
    metadata: dict = {}
    error: Optional[str] = None
