"""
Layer 6 테스트용 Mock 데이터 - 4개 시나리오
Layer 3 Clinical Logic 결과를 포함한 완성된 입력 데이터
"""

# ============================================================
# 시나리오 1: 심부전 (CHF)
# 72세 남성, 심비대 + 양측 흉수 + 폐부종, 심방세동
# ============================================================
SCENARIO_CHF = {
    "request_id": "test_chf_001",
    "anatomy_measurements": {
        "ctr": 0.62, "ctr_status": "severe",
        "heart_width_px": 1500, "thorax_width_px": 2400,
        "lung_area_ratio": 0.875,
        "mediastinum_width_px": 180, "mediastinum_status": "normal",
        "trachea_midline": True,
        "right_cp_status": "blunted", "right_cp_angle_degrees": 95.0,
        "left_cp_status": "blunted", "left_cp_angle_degrees": 88.0,
        "diaphragm_status": "normal",
        "view": "PA",
        "predicted_age": 72, "predicted_sex": "M",
    },
    "densenet_predictions": {
        "Cardiomegaly": 0.92, "Edema": 0.85, "Pleural Effusion": 0.78,
        "Atelectasis": 0.35, "Consolidation": 0.05, "Pneumothorax": 0.02,
        "Pneumonia": 0.08, "Lung Opacity": 0.42, "No Finding": 0.03,
        "Fracture": 0.01, "Lung Lesion": 0.03, "Pleural Other": 0.04,
        "Enlarged Cardiomediastinum": 0.15, "Support Devices": 0.02,
    },
    "yolo_detections": [],
    "clinical_logic": {
        "findings": {
            "Cardiomegaly": {
                "detected": True, "confidence": "high", "severity": "severe",
                "evidence": ["CTR 0.6200 (정상 <0.50)", "DenseNet 0.92"],
                "quantitative": {"ctr": 0.62},
                "recommendation": "심초음파 추적 권장",
            },
            "Pleural Effusion": {
                "detected": True, "confidence": "high", "severity": "moderate",
                "location": "bilateral",
                "evidence": ["우측 CP angle 95deg - moderate", "좌측 88deg - small", "CTR 0.62 - CHF 관련"],
                "quantitative": {"right_cp_angle": 95.0, "left_cp_angle": 88.0},
            },
            "Edema": {
                "detected": True, "confidence": "high", "severity": "severe",
                "location": "bilateral",
                "evidence": ["양측 대칭", "Butterfly 패턴 의심", "CTR 0.62 + 흉수 - CHF 폐부종"],
            },
        },
        "differential_diagnosis": [
            {"diagnosis": "울혈성 심부전 (CHF)", "probability": "high",
             "reasoning": "Cardiomegaly + bilateral effusion + edema"},
        ],
        "risk_level": "URGENT",
        "alert_flags": [],
        "detected_count": 3,
    },
    "cross_validation_summary": {
        "high_agreement": ["Cardiomegaly"],
        "medium_agreement": ["Pleural Effusion", "Edema"],
        "flags": [],
    },
    "rag_evidence": [],
    "patient_info": {
        "age": 72, "sex": "M",
        "chief_complaint": "호흡곤란, 하지부종",
        "temperature": 36.8, "heart_rate": 98,
        "blood_pressure": "150/95", "spo2": 91,
        "respiratory_rate": 24,
    },
    "prior_results": [
        {"modal": "ecg", "summary": "심방세동 (AFib)"},
    ],
    "report_language": "ko",
    "report_format": "both",
}


# ============================================================
# 시나리오 2: 폐렴 (Pneumonia)
# 67세 남성, 좌하엽 경화 + 발열, ECG 정상
# ============================================================
SCENARIO_PNEUMONIA = {
    "request_id": "test_pneumonia_001",
    "anatomy_measurements": {
        "ctr": 0.45, "ctr_status": "normal",
        "heart_width_px": 1100, "thorax_width_px": 2400,
        "lung_area_ratio": 0.926,
        "mediastinum_width_px": 150, "mediastinum_status": "normal",
        "trachea_midline": True,
        "right_cp_status": "sharp", "right_cp_angle_degrees": 45.0,
        "left_cp_status": "sharp", "left_cp_angle_degrees": 42.0,
        "diaphragm_status": "normal",
        "view": "PA",
        "predicted_age": 67, "predicted_sex": "M",
    },
    "densenet_predictions": {
        "Pneumonia": 0.87, "Consolidation": 0.82, "Lung Opacity": 0.79,
        "Cardiomegaly": 0.05, "Edema": 0.03, "Pleural Effusion": 0.12,
        "Atelectasis": 0.28, "Pneumothorax": 0.01, "No Finding": 0.04,
        "Fracture": 0.01, "Lung Lesion": 0.05, "Pleural Other": 0.02,
        "Enlarged Cardiomediastinum": 0.03, "Support Devices": 0.01,
    },
    "yolo_detections": [
        {"class_name": "Consolidation", "bbox": [120, 340, 320, 520],
         "confidence": 0.84, "lobe": "LLL"},
    ],
    "clinical_logic": {
        "findings": {
            "Pneumonia": {
                "detected": True, "confidence": "high", "severity": "moderate",
                "location": "left_lower_lobe",
                "evidence": ["좌하엽 경화 소견", "DenseNet 0.87", "YOLO LLL 경화 bbox"],
                "recommendation": "혈액배양, 항생제 투여 고려",
            },
            "Consolidation": {
                "detected": True, "confidence": "high", "severity": "moderate",
                "location": "left_lower_lobe",
                "evidence": ["YOLO bbox conf 0.84", "DenseNet 0.82"],
                "quantitative": {"lobe": "LLL"},
            },
        },
        "differential_diagnosis": [
            {"diagnosis": "지역사회 획득 폐렴 (CAP)", "probability": "high",
             "reasoning": "좌하엽 경화 + 발열 38.2 + 호흡곤란"},
        ],
        "risk_level": "URGENT",
        "alert_flags": [],
        "detected_count": 2,
    },
    "cross_validation_summary": {
        "high_agreement": ["Consolidation"],
        "medium_agreement": ["Pneumonia"],
        "flags": [],
    },
    "rag_evidence": [],
    "patient_info": {
        "age": 67, "sex": "M",
        "chief_complaint": "기침, 발열, 호흡곤란",
        "temperature": 38.2, "respiratory_rate": 28, "spo2": 94,
    },
    "prior_results": [
        {"modal": "ecg", "summary": "정상 동성리듬, STEMI 아님"},
    ],
    "report_language": "ko",
    "report_format": "both",
}


# ============================================================
# 시나리오 3: 긴장성 기흉 (Tension Pneumothorax) - 응급!
# 25세 남성, 교통사고, 좌측 기흉 + 기관 편위
# ============================================================
SCENARIO_TENSION_PNEUMO = {
    "request_id": "test_tension_001",
    "anatomy_measurements": {
        "ctr": 0.48, "ctr_status": "normal",
        "heart_width_px": 1150, "thorax_width_px": 2400,
        "lung_area_ratio": 0.421,
        "mediastinum_width_px": 160, "mediastinum_status": "normal",
        "trachea_midline": False,
        "trachea_deviation_direction": "right",
        "trachea_deviation_ratio": 0.09,
        "right_cp_status": "sharp", "right_cp_angle_degrees": 40.0,
        "left_cp_status": "sharp", "left_cp_angle_degrees": 38.0,
        "diaphragm_status": "elevated_left",
        "view": "PA",
        "predicted_age": 25, "predicted_sex": "M",
    },
    "densenet_predictions": {
        "Pneumothorax": 0.95, "Fracture": 0.45,
        "Cardiomegaly": 0.03, "Edema": 0.02, "Pleural Effusion": 0.05,
        "Consolidation": 0.04, "Pneumonia": 0.03, "Atelectasis": 0.15,
        "Lung Opacity": 0.08, "No Finding": 0.02,
        "Lung Lesion": 0.01, "Pleural Other": 0.03,
        "Enlarged Cardiomediastinum": 0.02, "Support Devices": 0.01,
    },
    "yolo_detections": [],
    "clinical_logic": {
        "findings": {
            "Pneumothorax": {
                "detected": True, "confidence": "high", "severity": "critical",
                "location": "left",
                "evidence": [
                    "좌/우 폐면적비 0.421 (정상 0.85~1.15)",
                    "기관 우측 편위 (deviation ratio 0.09)",
                    "좌측 횡격막 거상",
                    "DenseNet 0.95",
                ],
                "quantitative": {"lung_area_ratio": 0.421, "trachea_deviation_ratio": 0.09},
                "recommendation": "즉시 흉관 삽입 (chest tube)",
            },
        },
        "differential_diagnosis": [
            {"diagnosis": "긴장성 기흉 (Tension Pneumothorax)", "probability": "high",
             "reasoning": "좌측 폐허탈 + 기관 우측 편위 + SpO2 82% + 외상력"},
        ],
        "risk_level": "CRITICAL",
        "alert_flags": ["TENSION_PNEUMOTHORAX"],
        "detected_count": 1,
    },
    "cross_validation_summary": {
        "high_agreement": ["Pneumothorax"],
        "flags": [],
    },
    "rag_evidence": [],
    "patient_info": {
        "age": 25, "sex": "M",
        "chief_complaint": "교통사고 후 흉통, 호흡곤란",
        "spo2": 82, "heart_rate": 130,
        "blood_pressure": "85/50", "respiratory_rate": 35,
    },
    "prior_results": [],
    "report_language": "ko",
    "report_format": "both",
}


# ============================================================
# 시나리오 4: 정상 (Normal)
# 모든 지표 정상
# ============================================================
SCENARIO_NORMAL = {
    "request_id": "test_normal_001",
    "anatomy_measurements": {
        "ctr": 0.44, "ctr_status": "normal",
        "heart_width_px": 1050, "thorax_width_px": 2400,
        "lung_area_ratio": 0.916,
        "mediastinum_width_px": 140, "mediastinum_status": "normal",
        "trachea_midline": True,
        "right_cp_status": "sharp", "right_cp_angle_degrees": 42.0,
        "left_cp_status": "sharp", "left_cp_angle_degrees": 40.0,
        "diaphragm_status": "normal",
        "view": "PA",
        "predicted_age": 35, "predicted_sex": "F",
    },
    "densenet_predictions": {
        "No Finding": 0.92,
        "Cardiomegaly": 0.03, "Edema": 0.02, "Pleural Effusion": 0.04,
        "Consolidation": 0.02, "Pneumonia": 0.03, "Atelectasis": 0.05,
        "Pneumothorax": 0.01, "Lung Opacity": 0.06, "Fracture": 0.01,
        "Lung Lesion": 0.02, "Pleural Other": 0.01,
        "Enlarged Cardiomediastinum": 0.02, "Support Devices": 0.01,
    },
    "yolo_detections": [],
    "clinical_logic": {
        "findings": {},
        "differential_diagnosis": [],
        "risk_level": "ROUTINE",
        "alert_flags": [],
        "detected_count": 0,
    },
    "cross_validation_summary": {},
    "rag_evidence": [],
    "patient_info": {
        "age": 35, "sex": "F",
        "chief_complaint": "건강검진",
    },
    "prior_results": [],
    "report_language": "ko",
    "report_format": "both",
}


# 시나리오 매핑
SCENARIOS = {
    "chf": {
        "name": "심부전 (CHF)",
        "description": "72세 남성, 심비대 + 양측 흉수 + 폐부종, 심방세동",
        "input": SCENARIO_CHF,
    },
    "pneumonia": {
        "name": "폐렴 (Pneumonia)",
        "description": "67세 남성, 좌하엽 경화 + 발열 38.2C, ECG 정상",
        "input": SCENARIO_PNEUMONIA,
    },
    "tension_pneumo": {
        "name": "긴장성 기흉 (Tension Pneumothorax)",
        "description": "25세 남성, 교통사고 후 좌측 기흉, 기관 우측 편위, SpO2 82%",
        "input": SCENARIO_TENSION_PNEUMO,
    },
    "normal": {
        "name": "정상 (Normal)",
        "description": "35세 여성, 건강검진, 모든 지표 정상",
        "input": SCENARIO_NORMAL,
    },
}
