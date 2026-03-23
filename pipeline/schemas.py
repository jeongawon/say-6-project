"""
흉부 모달 v2 입출력 JSON 스키마 정의
오케스트레이터 ↔ 흉부 모달 간 데이터 계약
"""

# 입력 스키마 (오케스트레이터 → 흉부 모달)
INPUT_SCHEMA = {
    "patient_id": str,          # e.g. "p10000032"
    "request_id": str,          # e.g. "req_001"
    "modal": str,               # "chest_xray"
    "cxr_image_s3_path": str,   # S3 이미지 경로
    "patient_info": {
        "age": int,
        "sex": str,             # "M" or "F"
        "chief_complaint": str, # 주소
        "vitals": {
            "HR": int,
            "BP": str,          # "120/80"
            "SpO2": int,
            "RR": int,
            "Temp": float
        }
    },
    "prior_results": list       # 이전 검사 결과 리스트
}

# 출력 스키마 (흉부 모달 → 오케스트레이터)
OUTPUT_SCHEMA = {
    "modal": str,
    "timestamp": str,
    "anatomy_measurements": dict,   # CTR, 폐 면적, 종격동 너비 등
    "densenet_predictions": dict,   # 14-label 확률
    "yolo_detections": list,        # bbox + class + confidence + lobe
    "clinical_logic_findings": list,  # 질환별 Clinical Logic 결과
    "cross_validation": dict,       # 3중 교차 검증 결과
    "differential_diagnosis": list, # 감별 진단
    "rag_evidence": list,           # 유사 판독문
    "annotated_image_s3_path": str, # 어노테이션 이미지 S3 경로
    "alert_flags": list,            # 긴급 알림
    "recommendations": list,        # 추천 조치
    "suggested_next_actions": list  # 다음 모달 호출 제안
}
