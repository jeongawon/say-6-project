"""
Layer 3 Clinical Logic — 입출력 데이터 클래스
Layer 1/2 결과를 받아 Clinical Logic에 전달하기 위한 인터페이스 정의
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict


@dataclass
class AnatomyMeasurements:
    """Layer 1 출력 — 해부학 측정값"""
    # 심장
    ctr: float                          # 예: 0.6007
    ctr_status: str                     # normal / enlarged / severe
    heart_width_px: int
    thorax_width_px: int
    heart_area_px2: int

    # 폐
    right_lung_area_px2: int
    left_lung_area_px2: int
    lung_area_ratio: float              # 좌/우 면적비, 예: 0.7807
    total_lung_area_px2: int

    # 종격동
    mediastinum_width_px: Optional[int] = None
    mediastinum_status: Optional[str] = None       # normal / enlarged

    # 기관 중심선
    trachea_deviation_px: Optional[float] = None
    trachea_deviation_ratio: Optional[float] = None
    trachea_midline: Optional[bool] = None
    trachea_deviation_direction: Optional[str] = None  # none / right / left

    # CP angle
    right_cp_angle_degrees: Optional[float] = None
    right_cp_status: Optional[str] = None          # sharp / blunted
    left_cp_angle_degrees: Optional[float] = None
    left_cp_status: Optional[str] = None

    # 횡격막
    diaphragm_height_diff_px: Optional[float] = None
    diaphragm_height_diff_ratio: Optional[float] = None
    diaphragm_status: Optional[str] = None         # normal / elevated_right / elevated_left

    # 뷰/환자정보
    view: str = "PA"
    predicted_age: Optional[float] = None
    predicted_sex: Optional[str] = None


@dataclass
class DenseNetPredictions:
    """Layer 2a 출력 — DenseNet-121 14-label 확률"""
    Atelectasis: float = 0.0
    Cardiomegaly: float = 0.0
    Consolidation: float = 0.0
    Edema: float = 0.0
    Enlarged_Cardiomediastinum: float = 0.0
    Fracture: float = 0.0
    Lung_Lesion: float = 0.0
    Lung_Opacity: float = 0.0
    No_Finding: float = 0.0
    Pleural_Effusion: float = 0.0
    Pleural_Other: float = 0.0
    Pneumonia: float = 0.0
    Pneumothorax: float = 0.0
    Support_Devices: float = 0.0


@dataclass
class YoloDetection:
    """YOLOv8 개별 탐지 결과"""
    class_name: str               # 예: "Consolidation"
    bbox: List[int]               # [x_min, y_min, x_max, y_max]
    confidence: float             # 예: 0.84
    lobe: Optional[str] = None    # 폐엽 매핑 결과: RUL/RML/RLL/LUL/LLL


@dataclass
class PatientInfo:
    """오케스트레이터에서 전달된 환자 정보"""
    age: Optional[int] = None
    sex: Optional[str] = None
    chief_complaint: Optional[str] = None     # "흉통, 호흡곤란, 기침"
    temperature: Optional[float] = None       # 체온 (°C)
    heart_rate: Optional[int] = None
    blood_pressure: Optional[str] = None      # "90/60"
    spo2: Optional[int] = None
    respiratory_rate: Optional[int] = None


@dataclass
class PriorResult:
    """이전 모달 검사 결과"""
    modal: str                    # "ecg", "lab" 등
    summary: str                  # "정상 동성리듬, STEMI 아님"
    findings: Dict = field(default_factory=dict)  # {"WBC": 15000, "CRP": 12.5}


@dataclass
class ClinicalLogicInput:
    """Layer 3 전체 입력"""
    anatomy: AnatomyMeasurements
    densenet: DenseNetPredictions
    yolo_detections: List[YoloDetection] = field(default_factory=list)
    patient_info: Optional[PatientInfo] = None
    prior_results: List[PriorResult] = field(default_factory=list)
