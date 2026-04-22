"""Lab Modal Connector - Mock Lab results (준비 중)."""
import json
import logging
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    """
    Mock Lab modal connector.
    실제 Lab 시스템 연동 시 이 파일을 수정하여 사용.
    """
    case_id = event.get('case_id', 'unknown')
    patient = event.get('patient', {})
    
    logger.info(f"Lab connector invoked for case {case_id} (MOCK)")
    
    chief_complaint = patient.get('chief_complaint', '').lower()
    
    # Mock lab results based on chief complaint
    if 'chest pain' in chief_complaint or 'cardiac' in chief_complaint:
        finding = "Elevated troponin, consistent with myocardial injury"
        confidence = 0.95
        details = {
            "cardiac_markers": {
                "troponin_I": {"value": 2.8, "unit": "ng/mL", "reference": "<0.04", "status": "HIGH"},
                "CK_MB": {"value": 45, "unit": "ng/mL", "reference": "<5", "status": "HIGH"},
                "BNP": {"value": 320, "unit": "pg/mL", "reference": "<100", "status": "HIGH"}
            },
            "cbc": {
                "WBC": {"value": 11.2, "unit": "K/uL", "reference": "4.5-11.0", "status": "NORMAL"},
                "hemoglobin": {"value": 14.5, "unit": "g/dL", "reference": "13.5-17.5", "status": "NORMAL"},
                "platelets": {"value": 245, "unit": "K/uL", "reference": "150-400", "status": "NORMAL"}
            },
            "key_findings": [
                "Significantly elevated troponin I",
                "Elevated CK-MB",
                "Elevated BNP suggesting cardiac strain"
            ]
        }
        rationale = "Lab results confirm acute myocardial injury"
        
    elif 'fever' in chief_complaint or 'infection' in chief_complaint:
        finding = "Leukocytosis with left shift, elevated inflammatory markers"
        confidence = 0.89
        details = {
            "cbc": {
                "WBC": {"value": 18.5, "unit": "K/uL", "reference": "4.5-11.0", "status": "HIGH"},
                "neutrophils": {"value": 85, "unit": "%", "reference": "40-70", "status": "HIGH"},
                "bands": {"value": 12, "unit": "%", "reference": "0-5", "status": "HIGH"},
                "hemoglobin": {"value": 13.2, "unit": "g/dL", "reference": "13.5-17.5", "status": "LOW"},
                "platelets": {"value": 195, "unit": "K/uL", "reference": "150-400", "status": "NORMAL"}
            },
            "inflammatory_markers": {
                "CRP": {"value": 125, "unit": "mg/L", "reference": "<10", "status": "HIGH"},
                "procalcitonin": {"value": 2.8, "unit": "ng/mL", "reference": "<0.5", "status": "HIGH"}
            },
            "key_findings": [
                "Marked leukocytosis",
                "Left shift with bandemia",
                "Elevated CRP and procalcitonin",
                "Findings consistent with bacterial infection"
            ]
        }
        rationale = "Lab findings strongly suggest bacterial infection/sepsis"
        
    elif 'abdominal pain' in chief_complaint:
        finding = "Elevated lipase, consistent with pancreatitis"
        confidence = 0.87
        details = {
            "pancreatic_enzymes": {
                "lipase": {"value": 850, "unit": "U/L", "reference": "<60", "status": "HIGH"},
                "amylase": {"value": 420, "unit": "U/L", "reference": "<100", "status": "HIGH"}
            },
            "liver_function": {
                "ALT": {"value": 85, "unit": "U/L", "reference": "7-56", "status": "HIGH"},
                "AST": {"value": 92, "unit": "U/L", "reference": "10-40", "status": "HIGH"},
                "bilirubin": {"value": 1.8, "unit": "mg/dL", "reference": "0.1-1.2", "status": "HIGH"}
            },
            "key_findings": [
                "Markedly elevated lipase",
                "Elevated amylase",
                "Mild transaminitis",
                "Findings consistent with acute pancreatitis"
            ]
        }
        rationale = "Lab results diagnostic for acute pancreatitis"
        
    else:
        finding = "Lab values within normal limits"
        confidence = 0.91
        details = {
            "cbc": {
                "WBC": {"value": 7.8, "unit": "K/uL", "reference": "4.5-11.0", "status": "NORMAL"},
                "hemoglobin": {"value": 14.8, "unit": "g/dL", "reference": "13.5-17.5", "status": "NORMAL"},
                "platelets": {"value": 265, "unit": "K/uL", "reference": "150-400", "status": "NORMAL"}
            },
            "bmp": {
                "sodium": {"value": 140, "unit": "mEq/L", "reference": "136-145", "status": "NORMAL"},
                "potassium": {"value": 4.2, "unit": "mEq/L", "reference": "3.5-5.0", "status": "NORMAL"},
                "creatinine": {"value": 0.9, "unit": "mg/dL", "reference": "0.7-1.3", "status": "NORMAL"}
            },
            "key_findings": [
                "Normal complete blood count",
                "Normal electrolytes",
                "Normal renal function"
            ]
        }
        rationale = "Laboratory studies unremarkable"
    
    logger.info(f"Mock Lab response generated for case {case_id}: {finding}")
    
    return {
        "modality": "LAB",
        "finding": finding,
        "confidence": confidence,
        "details": details,
        "rationale": rationale,
        "timestamp": datetime.utcnow().isoformat(),
        "mock": True
    }
