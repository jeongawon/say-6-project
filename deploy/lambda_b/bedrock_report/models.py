"""
Layer 6 Bedrock Report — 입출력 데이터 클래스
"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


@dataclass
class ReportInput:
    """Layer 6 입력 - 모든 Layer 결과 종합"""
    request_id: str = ""

    # Layer 1 결과
    anatomy_measurements: Dict[str, Any] = field(default_factory=dict)

    # Layer 2 결과
    densenet_predictions: Dict[str, float] = field(default_factory=dict)
    yolo_detections: List[Dict] = field(default_factory=list)

    # Layer 3 결과
    clinical_logic: Dict[str, Any] = field(default_factory=dict)

    # Layer 4 교차검증
    cross_validation_summary: Dict[str, Any] = field(default_factory=dict)

    # Layer 5 RAG
    rag_evidence: List[Dict] = field(default_factory=list)

    # 환자 정보
    patient_info: Dict[str, Any] = field(default_factory=dict)
    prior_results: List[Dict] = field(default_factory=list)

    # 설정
    report_language: str = "ko"
    report_format: str = "both"  # structured / narrative / both


@dataclass
class StructuredReport:
    """구조화된 소견서"""
    heart: str = ""
    pleura: str = ""
    lungs: str = ""
    mediastinum: str = ""
    bones: str = ""
    devices: str = ""
    impression: str = ""
    recommendation: str = ""


@dataclass
class NextAction:
    """다음 조치 추천"""
    action: str = ""       # order_test / immediate_action
    modal: str = ""        # lab / echocardiogram 등
    description: str = ""
    tests: List[str] = field(default_factory=list)


@dataclass
class ReportOutput:
    """Layer 6 출력 - 최종 소견서"""
    request_id: str = ""
    structured: Dict[str, str] = field(default_factory=dict)
    narrative: str = ""
    summary: str = ""
    risk_level: str = "ROUTINE"
    alert_flags: List[str] = field(default_factory=list)
    suggested_next_actions: List[Dict] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
