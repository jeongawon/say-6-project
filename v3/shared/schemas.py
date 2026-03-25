"""
공통 Pydantic 스키마 — 모든 서비스가 import하여 사용.

사용법:
    # 각 서비스의 main.py에서
    import sys; sys.path.insert(0, "/app/shared")  # Docker에서
    from schemas import PredictRequest, PredictResponse, Finding, PatientInfo
"""

from pydantic import BaseModel
from typing import Optional


class PatientInfo(BaseModel):
    age: int
    sex: str                          # "M" | "F"
    chief_complaint: str
    history: list[str] = []


class Finding(BaseModel):
    name: str
    detected: bool
    confidence: float
    detail: str = ""
    secondary: bool = False           # True = 동반 소견 (독립 소견 아님)


class PredictRequest(BaseModel):
    patient_id: str
    patient_info: PatientInfo
    data: dict                        # 모달마다 다름
    context: dict = {}                # 이전 모달 결과 요약


class PredictResponse(BaseModel):
    status: str = "success"
    modal: str
    findings: list[Finding]
    summary: str
    report: str = ""                  # 모달별 소견서 (impression)
    risk_level: str = "routine"       # routine / urgent / critical
    pertinent_negatives: list[str] = []  # 주소증 관련 음성 소견
    suggested_next_actions: list[dict] = []  # 권장 후속 조치
    metadata: dict = {}


class RAGRequest(BaseModel):
    query: str
    modal: str
    top_k: int = 5


class RAGResponse(BaseModel):
    results: list[dict]


class ReportRequest(BaseModel):
    patient_id: str
    patient_info: PatientInfo
    modal_reports: list[dict]


class ReportResponse(BaseModel):
    status: str = "success"
    report: str                       # 종합 소견서
    diagnosis: str
