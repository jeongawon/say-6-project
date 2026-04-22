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
    """Call external CXR inference API."""
    
    payload = {
        "case_id": case_id,
        "image_url": image_url,
        "metadata": cxr_data
    }
    
    logger.info(f"Calling CXR API: {CXR_API_ENDPOINT}")
    
    response = requests.post(
        CXR_API_ENDPOINT,
        json=payload,
        timeout=300  # 5 minutes for inference
    )
    
    response.raise_for_status()
    result = response.json()
    
    # Transform to standardized format
    return {
        "modality": "CXR",
        "finding": result.get('diagnosis', 'Unknown'),
        "confidence": result.get('confidence', 0.0),
        "details": {
            "diseases": result.get('diseases', []),
            "lesions": result.get('lesions', []),
            "severity": result.get('severity', 'unknown'),
            "key_findings": result.get('key_findings', [])
        },
        "rationale": result.get('rationale', 'CXR analysis completed'),
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
