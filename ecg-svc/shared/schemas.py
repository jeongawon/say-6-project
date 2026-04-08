from pydantic import BaseModel
from typing import List, Optional


class PatientInfo(BaseModel):
    age: float
    sex: str                              # "M" / "F"
    chief_complaint: str = ""
    history: List[str] = []
    temperature: Optional[float] = None
    blood_pressure: Optional[str] = None
    spo2: Optional[float] = None
    respiratory_rate: Optional[int] = None


class ECGData(BaseModel):
    signal_path: Optional[str] = None    # S3 URI 또는 로컬 경로
    leads: int = 12


class PredictRequest(BaseModel):
    patient_id: str
    patient_info: Optional[PatientInfo] = None
    data: ECGData
    context: dict = {}


class Finding(BaseModel):
    name: str
    confidence: float
    detail: str = ""
    severity: Optional[str] = None       # mild / moderate / severe / critical
    recommendation: Optional[str] = None


class PredictResponse(BaseModel):
    status: str
    modal: str = "ecg"
    findings: List[Finding] = []
    summary: str = ""
    risk_level: str = "routine"          # routine / urgent / critical
    metadata: dict = {}
    error: Optional[str] = None
