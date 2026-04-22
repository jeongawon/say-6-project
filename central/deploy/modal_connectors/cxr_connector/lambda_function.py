"""CXR Modal Connector - Connects to external CXR inference service."""
import json
import logging
import os
import boto3
import requests
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# CXR API endpoint (from SSM Parameter Store or environment)
CXR_API_ENDPOINT = os.environ.get('CXR_API_ENDPOINT', '')


def handler(event, context):
    """
    Call external CXR modal and return standardized response.
    
    Expected input:
    - case_id
    - patient (with cxr_image_url or cxr_data)
    
    Returns standardized modal response:
    - modality: "CXR"
    - finding: diagnosis result
    - confidence: 0.0-1.0
    - details: additional information
    - rationale: diagnostic reasoning
    """
    case_id = event.get('case_id', 'unknown')
    patient = event.get('patient', {})
    
    logger.info(f"CXR connector invoked for case {case_id}")
    
    # Extract CXR data
    cxr_image_url = patient.get('cxr_image_url')
    cxr_data = patient.get('cxr_data', {})
    
    if not cxr_image_url and not cxr_data:
        logger.warning(f"No CXR data provided for case {case_id}, using mock response")
        return generate_mock_response(case_id, patient)
    
    # Call external CXR API
    if CXR_API_ENDPOINT:
        try:
            response = call_cxr_api(case_id, cxr_image_url, cxr_data)
            return response
        except Exception as e:
            logger.error(f"CXR API call failed: {e}, falling back to mock")
            return generate_mock_response(case_id, patient)
    else:
        logger.info("CXR_API_ENDPOINT not configured, using mock response")
        return generate_mock_response(case_id, patient)


def call_cxr_api(case_id, image_url, cxr_data):
    """Call chest-svc-pre API (/predict endpoint)."""
    
    # chest-svc-pre 요청 형식에 맞게 변환
    payload = {
        "patient_id": case_id,
        "patient_info": {
            "age": cxr_data.get('age', 50),
            "sex": cxr_data.get('sex', 'M'),
            "chief_complaint": cxr_data.get('chief_complaint', 'Chest X-ray analysis'),
            "history": []
        },
        "data": {
            "image_base64": image_url  # Base64 encoded image data
        },
        "context": {}
    }
    
    logger.info(f"Calling chest-svc-pre API: {CXR_API_ENDPOINT}/predict")
    
    response = requests.post(
        f"{CXR_API_ENDPOINT}/predict",
        json=payload,
        timeout=300,  # 5 minutes for inference
        headers={'Content-Type': 'application/json'}
    )
    
    response.raise_for_status()
    result = response.json()
    
    # Transform chest-svc-pre response to standardized format
    return transform_cxr_response(result)


def transform_cxr_response(cxr_result):
    """Transform chest-svc-pre response to orchestrator standard format."""
    
    findings = cxr_result.get('findings', [])
    
    # 가장 높은 confidence의 detected 질환 찾기
    detected_findings = [f for f in findings if f.get('detected', False)]
    primary_finding = max(detected_findings, key=lambda x: x.get('confidence', 0)) if detected_findings else None
    
    if primary_finding:
        finding = primary_finding['name']
        confidence = primary_finding['confidence']
    else:
        finding = "No significant abnormality detected"
        confidence = 0.9
    
    # 상세 정보 구성
    details = {
        "diseases": [
            {
                "name": f['name'],
                "probability": f['confidence'],
                "severity": f.get('severity'),
                "detected": f.get('detected', False),
                "verification": f.get('verification', {}),
                "evidence": f.get('evidence', []),
                "location": f.get('location'),
                "recommendation": f.get('recommendation')
            }
            for f in findings
        ],
        "measurements": cxr_result.get('measurements', {}),
        "severity": cxr_result.get('risk_level', 'routine'),
        "key_findings": [
            f"{f['name']} (confidence: {f['confidence']:.2f})" 
            for f in detected_findings[:3]  # Top 3
        ]
    }
    
    return {
        "modality": "CXR",
        "finding": finding,
        "confidence": confidence,
        "details": details,
        "rationale": cxr_result.get('impression', cxr_result.get('summary', 'CXR analysis completed')),
        "findings_text": cxr_result.get('findings_text', ''),
        "impression": cxr_result.get('impression', ''),
        "rag_query_hints": cxr_result.get('rag_query_hints', []),
        "risk_level": cxr_result.get('risk_level', 'routine'),
        "timestamp": datetime.utcnow().isoformat()
    }


def generate_mock_response(case_id, patient):
    """Generate mock CXR response for testing."""
    
    chief_complaint = patient.get('chief_complaint', '').lower()
    
    # Mock logic based on chief complaint
    if 'chest pain' in chief_complaint or 'cardiac' in chief_complaint:
        finding = "Cardiomegaly with possible pulmonary edema"
        confidence = 0.82
        details = {
            "diseases": ["Cardiomegaly", "Pulmonary Edema"],
            "lesions": [],
            "severity": "moderate",
            "key_findings": [
                "Enlarged cardiac silhouette",
                "Bilateral perihilar opacities",
                "Cephalization of pulmonary vessels"
            ]
        }
        rationale = "Chest X-ray shows enlarged heart with signs of fluid overload"
        
    elif 'shortness of breath' in chief_complaint or 'dyspnea' in chief_complaint:
        finding = "Right lower lobe pneumonia"
        confidence = 0.88
        details = {
            "diseases": ["Pneumonia"],
            "lesions": [{"location": "right lower lobe", "type": "consolidation"}],
            "severity": "moderate",
            "key_findings": [
                "Right lower lobe consolidation",
                "Air bronchograms present",
                "Blunting of right costophrenic angle"
            ]
        }
        rationale = "Consolidation pattern consistent with bacterial pneumonia"
        
    elif 'trauma' in chief_complaint:
        finding = "Multiple rib fractures, no pneumothorax"
        confidence = 0.91
        details = {
            "diseases": [],
            "lesions": [
                {"location": "left ribs 4-6", "type": "fracture"},
                {"location": "right rib 8", "type": "fracture"}
            ],
            "severity": "moderate",
            "key_findings": [
                "Fractures of left ribs 4, 5, 6",
                "Fracture of right rib 8",
                "No pneumothorax",
                "No hemothorax"
            ]
        }
        rationale = "Traumatic rib fractures without complications"
        
    else:
        finding = "No acute cardiopulmonary abnormality"
        confidence = 0.89
        details = {
            "diseases": [],
            "lesions": [],
            "severity": "low",
            "key_findings": [
                "Clear lung fields",
                "Normal cardiac silhouette",
                "No pleural effusion"
            ]
        }
        rationale = "Chest X-ray within normal limits"
    
    logger.info(f"Mock CXR response generated for case {case_id}: {finding}")
    
    return {
        "modality": "CXR",
        "finding": finding,
        "confidence": confidence,
        "details": details,
        "rationale": rationale,
        "timestamp": datetime.utcnow().isoformat(),
        "mock": True
    }
