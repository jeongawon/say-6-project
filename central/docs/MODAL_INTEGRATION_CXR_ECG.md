# CXR & ECG Modal Integration Guide

## 호환성 분석

### ✅ 완벽하게 호환 가능!

두 모달 모두 독립적인 API 서비스로 구성되어 있어, 오케스트레이터의 Modal Connector를 통해 쉽게 연동할 수 있습니다.

## 아키텍처 매핑

```
┌─────────────────────────────────────────────────────────────────┐
│              Emergency Orchestrator (Step Functions)             │
└────────────┬────────────────────────────┬────────────────────────┘
             │                            │
             ▼                            ▼
┌────────────────────────┐    ┌────────────────────────┐
│   CXR Connector        │    │   ECG Connector        │
│   (Lambda)             │    │   (Lambda)             │
└────────────┬───────────┘    └────────────┬───────────┘
             │                              │
             ▼                              ▼
┌────────────────────────┐    ┌────────────────────────┐
│   CXR Service          │    │   ECG Service          │
│   (Lambda A + B)       │    │   (FastAPI)            │
│   - Vision Inference   │    │   - Preprocessing      │
│   - Clinical Logic     │    │   - Mamba S6 Inference │
│   - RAG + Bedrock      │    │   - Clinical Logic     │
└────────────────────────┘    └────────────────────────┘
```

## 1. CXR Modal 통합

### CXR 서비스 구조
```
CXR Service (HTTP API)
├── Lambda A: Vision Inference (ONNX)
│   ├── Segmentation (UNet)
│   ├── Classification (DenseNet-121, 14 diseases)
│   └── Detection (YOLOv8, lesions)
└── Lambda B: Analysis & Report
    ├── Clinical Logic (14 disease rules)
    ├── RAG (FAISS, 123k cases)
    └── Bedrock Report (Claude Sonnet)
```

### CXR Connector 구현

```python
# deploy/modal_connectors/cxr_connector/lambda_function.py
import json
import logging
import os
import requests
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# CXR API endpoint (Lambda A의 API Gateway 엔드포인트)
CXR_API_ENDPOINT = os.environ.get('CXR_API_ENDPOINT')


def handler(event, context):
    """
    CXR Modal Connector - 기존 CXR 서비스 호출
    """
    case_id = event.get('case_id', 'unknown')
    patient = event.get('patient', {})
    
    logger.info(f"CXR connector invoked for case {case_id}")
    
    # CXR 이미지 URL 추출
    cxr_image_url = patient.get('cxr_image_url')
    cxr_image_data = patient.get('cxr_image_data')  # Base64 encoded
    
    if not cxr_image_url and not cxr_image_data:
        logger.warning(f"No CXR data provided for case {case_id}")
        return {
            "modality": "CXR",
            "finding": "No CXR data provided",
            "confidence": 0.0,
            "details": {},
            "rationale": "CXR image not available",
            "timestamp": datetime.utcnow().isoformat()
        }
    
    # CXR 서비스 호출
    try:
        result = call_cxr_service(case_id, cxr_image_url, cxr_image_data, patient)
        return transform_cxr_response(result)
    except Exception as e:
        logger.error(f"CXR service call failed: {e}")
        raise


def call_cxr_service(case_id, image_url, image_data, patient):
    """
    CXR 서비스 API 호출
    
    CXR 서비스의 Lambda A (Vision Inference) 엔드포인트 호출
    """
    # CXR 서비스 요청 형식에 맞게 변환
    payload = {
        "image_url": image_url,
        "image_data": image_data,
        "patient_info": {
            "age": patient.get('age'),
            "sex": patient.get('sex'),
            "chief_complaint": patient.get('chief_complaint')
        },
        "case_id": case_id
    }
    
    logger.info(f"Calling CXR service: {CXR_API_ENDPOINT}")
    
    response = requests.post(
        CXR_API_ENDPOINT,
        json=payload,
        timeout=300,  # 5 minutes for full pipeline
        headers={'Content-Type': 'application/json'}
    )
    
    response.raise_for_status()
    return response.json()


def transform_cxr_response(cxr_result):
    """
    CXR 서비스 응답을 오케스트레이터 표준 형식으로 변환
    
    CXR 서비스 응답 형식:
    {
        "diseases": [{"name": "...", "probability": 0.xx, "tier": "..."}],
        "lesions": [{"type": "...", "location": "...", "bbox": [...]}],
        "clinical_summary": "...",
        "report": "...",
        "risk_level": "..."
    }
    """
    # 주요 진단 추출 (가장 높은 확률의 질환)
    diseases = cxr_result.get('diseases', [])
    primary_disease = max(diseases, key=lambda x: x['probability']) if diseases else None
    
    if primary_disease:
        finding = f"{primary_disease['name']}"
        confidence = primary_disease['probability']
    else:
        finding = "No significant abnormality detected"
        confidence = 0.9
    
    # 병변 정보
    lesions = cxr_result.get('lesions', [])
    
    # 상세 정보 구성
    details = {
        "diseases": [
            {
                "name": d['name'],
                "probability": d['probability'],
                "tier": d.get('tier', 'unknown')
            }
            for d in diseases
        ],
        "lesions": [
            {
                "type": l['type'],
                "location": l['location'],
                "confidence": l.get('confidence', 0.0)
            }
            for l in lesions
        ],
        "severity": cxr_result.get('risk_level', 'unknown'),
        "key_findings": extract_key_findings(diseases, lesions)
    }
    
    # 표준 형식으로 반환
    return {
        "modality": "CXR",
        "finding": finding,
        "confidence": confidence,
        "details": details,
        "rationale": cxr_result.get('clinical_summary', 'CXR analysis completed'),
        "full_report": cxr_result.get('report'),  # 전체 리포트 (선택적)
        "timestamp": datetime.utcnow().isoformat()
    }


def extract_key_findings(diseases, lesions):
    """주요 소견 추출"""
    findings = []
    
    # 높은 확률의 질환
    for disease in diseases:
        if disease['probability'] > 0.5:
            findings.append(f"{disease['name']} (p={disease['probability']:.2f})")
    
    # 병변 요약
    if lesions:
        findings.append(f"{len(lesions)} lesion(s) detected")
    
    return findings
```

### CXR 서비스 배포 및 엔드포인트 설정

```bash
# 1. CXR 서비스 배포 (기존 레포)
cd cxr-service
python deploy/scripts/deploy_v2.py

# 2. API Gateway 엔드포인트 확인
CXR_ENDPOINT=$(aws cloudformation describe-stacks \
  --stack-name cxr-service \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiEndpoint`].OutputValue' \
  --output text)

echo "CXR Endpoint: $CXR_ENDPOINT"

# 3. 오케스트레이터에 엔드포인트 등록
aws ssm put-parameter \
  --name /emergency-orchestrator/cxr-endpoint \
  --value "$CXR_ENDPOINT" \
  --type String \
  --overwrite
```

## 2. ECG Modal 통합

### ECG 서비스 구조
```
ECG Service (FastAPI)
├── Layer 1: Preprocessing (WFDB)
│   └── ECG Vitals (HR, rhythm, QRS count)
├── Layer 2: Inference (Mamba S6 ONNX)
│   └── 24 disease classification
└── Layer 3: Clinical Logic
    └── Tier-based thresholds + Vitals correction
```

### ECG Connector 구현

```python
# deploy/modal_connectors/ecg_connector/lambda_function.py
import json
import logging
import os
import requests
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ECG API endpoint (FastAPI 서비스)
ECG_API_ENDPOINT = os.environ.get('ECG_API_ENDPOINT')


def handler(event, context):
    """
    ECG Modal Connector - FastAPI ECG 서비스 호출
    """
    case_id = event.get('case_id', 'unknown')
    patient = event.get('patient', {})
    
    logger.info(f"ECG connector invoked for case {case_id}")
    
    # ECG 데이터 추출
    ecg_data = patient.get('ecg_data')
    ecg_file_url = patient.get('ecg_file_url')
    
    if not ecg_data and not ecg_file_url:
        logger.warning(f"No ECG data provided for case {case_id}")
        return {
            "modality": "ECG",
            "finding": "No ECG data provided",
            "confidence": 0.0,
            "details": {},
            "rationale": "ECG data not available",
            "timestamp": datetime.utcnow().isoformat()
        }
    
    # ECG 서비스 호출
    try:
        result = call_ecg_service(case_id, ecg_data, ecg_file_url, patient)
        return transform_ecg_response(result)
    except Exception as e:
        logger.error(f"ECG service call failed: {e}")
        raise


def call_ecg_service(case_id, ecg_data, ecg_file_url, patient):
    """
    ECG 서비스 API 호출
    
    FastAPI /predict 엔드포인트 호출
    """
    # ECG 서비스 요청 형식
    payload = {
        "ecg_data": ecg_data,  # WFDB format or raw signal
        "ecg_file_url": ecg_file_url,
        "patient_info": {
            "age": patient.get('age'),
            "sex": patient.get('sex'),
            "chief_complaint": patient.get('chief_complaint')
        },
        "case_id": case_id
    }
    
    logger.info(f"Calling ECG service: {ECG_API_ENDPOINT}/predict")
    
    response = requests.post(
        f"{ECG_API_ENDPOINT}/predict",
        json=payload,
        timeout=60,
        headers={'Content-Type': 'application/json'}
    )
    
    response.raise_for_status()
    return response.json()


def transform_ecg_response(ecg_result):
    """
    ECG 서비스 응답을 오케스트레이터 표준 형식으로 변환
    
    ECG 서비스 응답 형식:
    {
        "vitals": {"hr": 88, "rhythm": "SR", "qrs_count": 12, ...},
        "findings": [
            {"label": "NORM", "probability": 0.95, "tier": 0},
            {"label": "AFIB", "probability": 0.03, "tier": 1},
            ...
        ],
        "abnormal_leads": ["II", "III", "aVF"],
        "risk_level": "ROUTINE|URGENT|CRITICAL",
        "next_modal_hint": "CXR|LAB|..."
    }
    """
    # 주요 진단 추출
    findings = ecg_result.get('findings', [])
    primary_finding = findings[0] if findings else None
    
    if primary_finding:
        finding = interpret_ecg_finding(primary_finding, ecg_result.get('vitals', {}))
        confidence = primary_finding['probability']
    else:
        finding = "ECG analysis completed"
        confidence = 0.0
    
    # Vitals 정보
    vitals = ecg_result.get('vitals', {})
    
    # 상세 정보 구성
    details = {
        "rhythm": vitals.get('rhythm', 'Unknown'),
        "rate": vitals.get('hr', 0),
        "qrs_count": vitals.get('qrs_count', 0),
        "intervals": {
            "PR": vitals.get('pr_interval'),
            "QRS": vitals.get('qrs_duration'),
            "QT": vitals.get('qt_interval'),
            "QTc": vitals.get('qtc')
        },
        "findings": [
            {
                "label": f['label'],
                "probability": f['probability'],
                "tier": f.get('tier', 0)
            }
            for f in findings[:5]  # Top 5
        ],
        "abnormal_leads": ecg_result.get('abnormal_leads', []),
        "key_findings": extract_ecg_key_findings(findings, vitals)
    }
    
    # 표준 형식으로 반환
    return {
        "modality": "ECG",
        "finding": finding,
        "confidence": confidence,
        "details": details,
        "rationale": generate_ecg_rationale(findings, vitals),
        "risk_level": ecg_result.get('risk_level', 'ROUTINE'),
        "next_modal_hint": ecg_result.get('next_modal_hint'),  # Bedrock 제안
        "timestamp": datetime.utcnow().isoformat()
    }


def interpret_ecg_finding(primary_finding, vitals):
    """ECG 소견을 임상적으로 해석"""
    label = primary_finding['label']
    prob = primary_finding['probability']
    hr = vitals.get('hr', 0)
    rhythm = vitals.get('rhythm', '')
    
    # 레이블별 해석
    interpretations = {
        'NORM': f"Normal sinus rhythm, HR {hr} bpm",
        'AFIB': f"Atrial fibrillation, HR {hr} bpm",
        'STACH': f"Sinus tachycardia, HR {hr} bpm",
        'SBRAD': f"Sinus bradycardia, HR {hr} bpm",
        'AFLT': f"Atrial flutter, HR {hr} bpm",
        'SVTAC': f"Supraventricular tachycardia, HR {hr} bpm",
        'PSVT': f"Paroxysmal supraventricular tachycardia",
        'BIGU': f"Bigeminy pattern detected",
        'TRIGU': f"Trigeminy pattern detected",
        'PACE': f"Paced rhythm detected",
        'SVARR': f"Supraventricular arrhythmia",
        'PVC': f"Premature ventricular contractions",
        'STD_': f"ST depression detected",
        'STE_': f"ST elevation detected - URGENT",
        'LBBB': f"Left bundle branch block",
        'RBBB': f"Right bundle branch block",
        'LAFB': f"Left anterior fascicular block",
        'IRBBB': f"Incomplete right bundle branch block",
        '1AVB': f"First-degree AV block",
        'IVCD': f"Intraventricular conduction delay",
        'LVH': f"Left ventricular hypertrophy",
        'LAO/LAE': f"Left atrial abnormality/enlargement",
        'RAO/RAE': f"Right atrial abnormality/enlargement",
        'WPW': f"Wolff-Parkinson-White pattern"
    }
    
    return interpretations.get(label, f"{label} detected (p={prob:.2f})")


def extract_ecg_key_findings(findings, vitals):
    """주요 ECG 소견 추출"""
    key_findings = []
    
    # 리듬
    rhythm = vitals.get('rhythm', 'Unknown')
    hr = vitals.get('hr', 0)
    key_findings.append(f"Rhythm: {rhythm}, Rate: {hr} bpm")
    
    # 높은 확률의 이상 소견
    for finding in findings:
        if finding['label'] != 'NORM' and finding['probability'] > 0.3:
            key_findings.append(f"{finding['label']} (p={finding['probability']:.2f})")
    
    return key_findings


def generate_ecg_rationale(findings, vitals):
    """ECG 판독 근거 생성"""
    primary = findings[0] if findings else None
    
    if not primary:
        return "ECG analysis completed"
    
    if primary['label'] == 'NORM':
        return f"ECG shows normal sinus rhythm with heart rate {vitals.get('hr', 0)} bpm"
    
    # 이상 소견
    rationale = f"ECG findings consistent with {primary['label']}"
    
    # 추가 컨텍스트
    if primary.get('tier', 0) >= 2:
        rationale += " - requires immediate attention"
    
    return rationale
```

### ECG 서비스 배포 및 엔드포인트 설정

```bash
# 1. ECG 서비스 배포 (FastAPI)
cd ecg-svc

# Docker 빌드 및 ECR 푸시
docker build -t ecg-service .
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account>.dkr.ecr.us-east-1.amazonaws.com
docker tag ecg-service:latest <account>.dkr.ecr.us-east-1.amazonaws.com/ecg-service:latest
docker push <account>.dkr.ecr.us-east-1.amazonaws.com/ecg-service:latest

# ECS/Fargate 또는 Lambda Container로 배포
# (또는 EC2에 직접 배포)

# 2. API 엔드포인트 확인
ECG_ENDPOINT="http://your-ecg-service.com:8000"

# 3. 오케스트레이터에 엔드포인트 등록
aws ssm put-parameter \
  --name /emergency-orchestrator/ecg-endpoint \
  --value "$ECG_ENDPOINT" \
  --type String \
  --overwrite
```

## 3. 통합 테스트

### 로컬 테스트 (Mock 서버)

```python
# tests/integration/test_cxr_ecg_integration.py
"""
CXR & ECG 모달 통합 테스트
"""
import json
from unittest.mock import Mock, patch

def test_cxr_integration():
    """CXR 모달 통합 테스트"""
    
    # Mock CXR 서비스 응답
    mock_cxr_response = {
        "diseases": [
            {"name": "Cardiomegaly", "probability": 0.85, "tier": 1},
            {"name": "Pulmonary Edema", "probability": 0.72, "tier": 2}
        ],
        "lesions": [
            {"type": "opacity", "location": "bilateral perihilar", "confidence": 0.8}
        ],
        "clinical_summary": "Enlarged heart with signs of fluid overload",
        "report": "Full radiology report...",
        "risk_level": "high"
    }
    
    # CXR Connector 호출
    from modal_connectors.cxr_connector.lambda_function import transform_cxr_response
    
    result = transform_cxr_response(mock_cxr_response)
    
    # 검증
    assert result['modality'] == 'CXR'
    assert result['finding'] == 'Cardiomegaly'
    assert result['confidence'] == 0.85
    assert 'diseases' in result['details']
    assert 'lesions' in result['details']
    
    print("✓ CXR integration test passed")


def test_ecg_integration():
    """ECG 모달 통합 테스트"""
    
    # Mock ECG 서비스 응답
    mock_ecg_response = {
        "vitals": {
            "hr": 88,
            "rhythm": "SR",
            "qrs_count": 12,
            "pr_interval": 160,
            "qrs_duration": 90,
            "qt_interval": 400,
            "qtc": 420
        },
        "findings": [
            {"label": "STE_", "probability": 0.92, "tier": 3},
            {"label": "NORM", "probability": 0.05, "tier": 0}
        ],
        "abnormal_leads": ["II", "III", "aVF"],
        "risk_level": "CRITICAL",
        "next_modal_hint": "LAB"
    }
    
    # ECG Connector 호출
    from modal_connectors.ecg_connector.lambda_function import transform_ecg_response
    
    result = transform_ecg_response(mock_ecg_response)
    
    # 검증
    assert result['modality'] == 'ECG'
    assert 'ST elevation' in result['finding']
    assert result['confidence'] > 0.9
    assert result['risk_level'] == 'CRITICAL'
    assert result['details']['rhythm'] == 'SR'
    assert result['details']['rate'] == 88
    
    print("✓ ECG integration test passed")


def test_full_workflow_with_cxr_ecg():
    """전체 워크플로우 테스트 (CXR + ECG)"""
    
    from orchestrator.fusion_decision.decision_engine import FusionDecisionEngine
    
    patient = {
        "age": 65,
        "sex": "Male",
        "chief_complaint": "chest pain"
    }
    
    # Iteration 1: 초기 결정
    engine = FusionDecisionEngine(
        patient=patient,
        modalities_completed=[],
        inference_results=[],
        iteration=1
    )
    
    decision = engine.decide()
    assert decision['decision'] == 'CALL_NEXT_MODALITY'
    assert 'CXR' in decision['next_modalities']
    assert 'ECG' in decision['next_modalities']
    
    # Iteration 2: CXR + ECG 결과 후
    cxr_result = {
        "modality": "CXR",
        "finding": "Cardiomegaly",
        "confidence": 0.85,
        "details": {"diseases": [{"name": "Cardiomegaly", "probability": 0.85}]}
    }
    
    ecg_result = {
        "modality": "ECG",
        "finding": "ST elevation in leads II, III, aVF - URGENT",
        "confidence": 0.92,
        "details": {"findings": [{"label": "STE_", "probability": 0.92}]},
        "risk_level": "CRITICAL"
    }
    
    engine = FusionDecisionEngine(
        patient=patient,
        modalities_completed=["CXR", "ECG"],
        inference_results=[cxr_result, ecg_result],
        iteration=2
    )
    
    decision = engine.decide()
    
    # 고위험 패턴 감지 확인
    assert decision['decision'] in ['NEED_REASONING', 'CALL_NEXT_MODALITY']
    assert decision['risk_level'] == 'high'
    
    print("✓ Full workflow integration test passed")


if __name__ == "__main__":
    test_cxr_integration()
    test_ecg_integration()
    test_full_workflow_with_cxr_ecg()
    print("\n✓ All integration tests passed!")
```

## 4. 배포 구성

### template.yaml 업데이트

```yaml
# emergency-multimodal-orchestrator/template.yaml

Resources:
  # CXR Connector
  CxrConnectorFunction:
    Type: AWS::Serverless::Function
    Properties:
      FunctionName: emergency-cxr-connector
      Handler: lambda_function.handler
      CodeUri: deploy/modal_connectors/cxr_connector/
      Timeout: 300  # CXR 서비스는 시간이 걸릴 수 있음
      MemorySize: 512
      Environment:
        Variables:
          CXR_API_ENDPOINT: !Sub '{{resolve:ssm:/emergency-orchestrator/cxr-endpoint:1}}'
      Policies:
        - SSMParameterReadPolicy:
            ParameterName: /emergency-orchestrator/cxr-endpoint

  # ECG Connector
  EcgConnectorFunction:
    Type: AWS::Serverless::Function
    Properties:
      FunctionName: emergency-ecg-connector
      Handler: lambda_function.handler
      CodeUri: deploy/modal_connectors/ecg_connector/
      Timeout: 60
      MemorySize: 256
      Environment:
        Variables:
          ECG_API_ENDPOINT: !Sub '{{resolve:ssm:/emergency-orchestrator/ecg-endpoint:1}}'
      Policies:
        - SSMParameterReadPolicy:
            ParameterName: /emergency-orchestrator/ecg-endpoint
```

## 5. Fusion Decision 로직 업데이트

### ECG 위험도 통합

```python
# deploy/orchestrator/fusion_decision/decision_engine.py

def _assess_risk_level(self):
    """위험도 평가 - ECG risk_level 반영"""
    if not self.inference_results:
        return 'unknown'
    
    # ECG CRITICAL 체크
    for result in self.inference_results:
        if result.get('modality') == 'ECG':
            ecg_risk = result.get('risk_level', '').upper()
            if ecg_risk == 'CRITICAL':
                return 'high'
            elif ecg_risk == 'URGENT':
                return 'medium'
    
    # 기존 로직...
    high_risk_keywords = [
        'stemi', 'st elevation', 'pneumothorax', 'massive', 'severe',
        'critical', 'acute', 'emergency'
    ]
    
    all_findings = ' '.join([r.get('finding', '').lower() for r in self.inference_results])
    
    if any(kw in all_findings for kw in high_risk_keywords):
        return 'high'
    
    return 'low'
```

### ECG next_modal_hint 활용

```python
def _suggest_based_on_findings(self):
    """ECG의 next_modal_hint 활용"""
    suggestions = []
    
    # ECG에서 제안한 다음 모달 확인
    for result in self.inference_results:
        if result.get('modality') == 'ECG':
            hint = result.get('next_modal_hint')
            if hint and hint not in self.modalities_completed:
                suggestions.append(hint)
    
    # 기존 로직도 유지...
    # ...
    
    return suggestions
```

## 요약

### ✅ 호환성 체크리스트

- [x] **API 인터페이스**: 두 모달 모두 HTTP API로 호출 가능
- [x] **응답 형식**: 표준 형식으로 변환 가능
- [x] **타임아웃**: CXR 300초, ECG 60초로 충분
- [x] **에러 처리**: 각 Connector에서 독립적으로 처리
- [x] **확장성**: 새로운 모달 추가 시 Connector만 추가하면 됨

### 🚀 배포 순서

1. **CXR 서비스 배포** (기존 레포)
2. **ECG 서비스 배포** (FastAPI)
3. **엔드포인트 SSM 등록**
4. **오케스트레이터 배포** (Connector 포함)
5. **통합 테스트**

### 📊 예상 워크플로우

```
Patient: 65yo Male, Chest Pain
  ↓
[Iteration 1] Fusion Decision
  → CALL_NEXT_MODALITY: [CXR, ECG]
  ↓
[CXR Service] → Cardiomegaly (0.85)
[ECG Service] → ST Elevation (0.92, CRITICAL)
  ↓
[Iteration 2] Fusion Decision
  → NEED_REASONING (high-risk pattern)
  ↓
[Bedrock Reasoning] → Clinical synthesis
  ↓
[Report Generator] → Final report
```

완벽하게 통합 가능합니다! 🎉
