"""
테스트용 Mock 데이터 — 4개 시나리오
Layer 2 결과가 없으므로, 다양한 임상 시나리오를 시뮬레이션
"""

from .models import (
    AnatomyMeasurements,
    DenseNetPredictions,
    YoloDetection,
    PatientInfo,
    PriorResult,
    ClinicalLogicInput,
)


# ============================================================
# 시나리오 1: 심부전 환자 (심비대 + 양측 흉수 + 폐부종)
# ============================================================
mock_chf_patient = ClinicalLogicInput(
    anatomy=AnatomyMeasurements(
        ctr=0.62, ctr_status="severe",
        heart_width_px=1500, thorax_width_px=2400, heart_area_px2=1200000,
        right_lung_area_px2=800000, left_lung_area_px2=700000,
        lung_area_ratio=0.875, total_lung_area_px2=1500000,
        right_cp_status="blunted", right_cp_angle_degrees=95,
        left_cp_status="blunted", left_cp_angle_degrees=88,
        mediastinum_status="normal", trachea_midline=True,
        diaphragm_status="normal",
    ),
    densenet=DenseNetPredictions(
        Cardiomegaly=0.92, Edema=0.85, Pleural_Effusion=0.78,
    ),
    patient_info=PatientInfo(
        age=72, sex="M", chief_complaint="호흡곤란, 하지부종",
    ),
    prior_results=[
        PriorResult(modal="ecg", summary="심방세동"),
    ],
)


# ============================================================
# 시나리오 2: 폐렴 환자 (경화 + 발열 + 정상 심장)
# ============================================================
mock_pneumonia_patient = ClinicalLogicInput(
    anatomy=AnatomyMeasurements(
        ctr=0.45, ctr_status="normal",
        heart_width_px=1100, thorax_width_px=2400, heart_area_px2=900000,
        right_lung_area_px2=950000, left_lung_area_px2=880000,
        lung_area_ratio=0.926, total_lung_area_px2=1830000,
        right_cp_status="sharp", left_cp_status="sharp",
        mediastinum_status="normal", trachea_midline=True,
        diaphragm_status="normal",
    ),
    densenet=DenseNetPredictions(
        Pneumonia=0.87, Consolidation=0.82, Lung_Opacity=0.79,
    ),
    yolo_detections=[
        YoloDetection(
            class_name="Consolidation",
            bbox=[120, 340, 320, 520],
            confidence=0.84,
            lobe="LLL",
        ),
    ],
    patient_info=PatientInfo(
        age=67, sex="M",
        chief_complaint="기침, 발열, 호흡곤란",
        temperature=38.2, respiratory_rate=28,
    ),
    prior_results=[
        PriorResult(modal="ecg", summary="정상 동성리듬, STEMI 아님"),
    ],
)


# ============================================================
# 시나리오 3: 긴장성 기흉 (응급!)
# ============================================================
mock_tension_pneumo = ClinicalLogicInput(
    anatomy=AnatomyMeasurements(
        ctr=0.48, ctr_status="normal",
        heart_width_px=1150, thorax_width_px=2400, heart_area_px2=950000,
        right_lung_area_px2=950000, left_lung_area_px2=400000,
        lung_area_ratio=0.421, total_lung_area_px2=1350000,
        right_cp_status="sharp", left_cp_status="sharp",
        mediastinum_status="normal",
        trachea_midline=False,
        trachea_deviation_direction="right",
        trachea_deviation_ratio=0.09,
        diaphragm_status="elevated_left",
    ),
    densenet=DenseNetPredictions(Pneumothorax=0.95),
    patient_info=PatientInfo(
        age=25, sex="M",
        chief_complaint="교통사고 후 흉통, 호흡곤란",
        spo2=82,
    ),
)


# ============================================================
# 시나리오 4: 정상
# ============================================================
mock_normal = ClinicalLogicInput(
    anatomy=AnatomyMeasurements(
        ctr=0.44, ctr_status="normal",
        heart_width_px=1050, thorax_width_px=2400, heart_area_px2=850000,
        right_lung_area_px2=950000, left_lung_area_px2=870000,
        lung_area_ratio=0.916, total_lung_area_px2=1820000,
        right_cp_status="sharp", left_cp_status="sharp",
        mediastinum_status="normal", trachea_midline=True,
        diaphragm_status="normal",
    ),
    densenet=DenseNetPredictions(No_Finding=0.92),
)
