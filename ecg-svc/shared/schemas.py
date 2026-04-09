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
    record_path: str                     # WFDB 레코드 경로 (확장자 없이, S3 URI 또는 로컬)
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


class ECGVitals(BaseModel):
    """
    ECG 파형에서 직접 측정된 바이탈 수치.
    다음 모달 라우팅 결정은 Bedrock Agent가 전담.
    """
    heart_rate: Optional[float] = None       # bpm (None = 측정 불가)
    bradycardia: bool = False                # HR < 50 bpm
    tachycardia: bool = False                # HR > 100 bpm
    irregular_rhythm: bool = False           # RR 변동계수 > 0.15 또는 Afib 계열 감지


class PredictResponse(BaseModel):
    status: str
    modal: str = "ecg"
    findings: List[Finding] = []
    summary: str = ""
    risk_level: str = "routine"          # routine / urgent / critical
    ecg_vitals: Optional[ECGVitals] = None
    all_probs: dict[str, float] = {}     # 24개 전체 질환 확률 (Bedrock Agent 라우팅용)
    waveform: Optional[List[List[float]]] = None  # (1000, 12) 원본 파형 — 프론트엔드 시각화용
    metadata: dict = {}
    error: Optional[str] = None
