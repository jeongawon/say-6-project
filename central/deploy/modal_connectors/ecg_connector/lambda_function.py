"""ECG Modal Connector - Mock ECG inference (준비 중)."""
import json
import logging
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    """
    Mock ECG modal connector.
    실제 ECG 모달 연동 시 이 파일을 수정하여 사용.
    """
    case_id = event.get('case_id', 'unknown')
    patient = event.get('patient', {})
    
    logger.info(f"ECG connector invoked for case {case_id} (MOCK)")
    
    chief_complaint = patient.get('chief_complaint', '').lower()
    
    # Mock ECG responses based on chief complaint
    if 'chest pain' in chief_complaint or 'cardiac' in chief_complaint:
        finding = "ST elevation in leads II, III, aVF - Inferior STEMI"
        confidence = 0.93
        details = {
            "rhythm": "Sinus rhythm",
            "rate": 88,
            "intervals": {
                "PR": 160,
                "QRS": 90,
                "QT": 420,
                "QTc": 445
            },
            "st_changes": [
                {"leads": ["II", "III", "aVF"], "type": "elevation", "magnitude": "2-3mm"}
            ],
            "key_findings": [
                "ST elevation in inferior leads",
                "Reciprocal ST depression in I, aVL",
                "Q waves in III, aVF"
            ]
        }
        rationale = "ECG findings consistent with acute inferior myocardial infarction"
        
    elif 'syncope' in chief_complaint or 'palpitation' in chief_complaint:
        finding = "Atrial fibrillation with rapid ventricular response"
        confidence = 0.91
        details = {
            "rhythm": "Atrial fibrillation",
            "rate": 142,
            "intervals": {
                "PR": "Variable",
                "QRS": 95,
                "QT": 380,
                "QTc": 465
            },
            "st_changes": [],
            "key_findings": [
                "Irregularly irregular rhythm",
                "Absent P waves",
                "Rapid ventricular rate",
                "No acute ST changes"
            ]
        }
        rationale = "ECG shows atrial fibrillation requiring rate control"
        
    elif 'shortness of breath' in chief_complaint:
        finding = "Sinus tachycardia, right heart strain pattern"
        confidence = 0.85
        details = {
            "rhythm": "Sinus tachycardia",
            "rate": 115,
            "intervals": {
                "PR": 155,
                "QRS": 88,
                "QT": 360,
                "QTc": 425
            },
            "st_changes": [],
            "key_findings": [
                "Sinus tachycardia",
                "Right axis deviation",
                "S1Q3T3 pattern",
                "T wave inversions in V1-V3"
            ]
        }
        rationale = "ECG findings suggestive of right heart strain, consider PE"
        
    else:
        finding = "Normal sinus rhythm, no acute changes"
        confidence = 0.92
        details = {
            "rhythm": "Normal sinus rhythm",
            "rate": 78,
            "intervals": {
                "PR": 165,
                "QRS": 92,
                "QT": 400,
                "QTc": 415
            },
            "st_changes": [],
            "key_findings": [
                "Normal sinus rhythm",
                "Normal axis",
                "No ST-T wave abnormalities",
                "No conduction delays"
            ]
        }
        rationale = "ECG within normal limits"
    
    logger.info(f"Mock ECG response generated for case {case_id}: {finding}")
    
    return {
        "modality": "ECG",
        "finding": finding,
        "confidence": confidence,
        "details": details,
        "rationale": rationale,
        "timestamp": datetime.utcnow().isoformat(),
        "mock": True
    }
