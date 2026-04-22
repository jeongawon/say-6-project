# Modal Integration Guide

## 개요

이 문서는 외부 모달 시스템(CXR, ECG, LAB)을 오케스트레이터와 연동하는 방법을 설명합니다.

## 모달 응답 프로토콜

모든 모달은 다음 표준 형식으로 응답해야 합니다:

```json
{
  "modality": "CXR|ECG|LAB",
  "finding": "진단 결과 요약",
  "confidence": 0.0-1.0,
  "details": {
    "key_findings": ["finding1", "finding2"],
    "severity": "low|medium|high",
    "additional_info": {}
  },
  "rationale": "진단 근거 설명",
  "timestamp": "ISO 8601 timestamp"
}
```

### 필수 필드

- `modality`: 모달 타입 (CXR, ECG, LAB)
- `finding`: 주요 진단 결과 (문자열)
- `confidence`: 신뢰도 (0.0 ~ 1.0)
- `rationale`: 진단 근거

### 선택 필드

- `details`: 추가 상세 정보
- `timestamp`: 결과 생성 시간

## CXR Modal 연동

### 현재 상태
CXR Connector는 외부 API 호출을 지원합니다.

### 연동 방법

#### 1. CXR API 엔드포인트 설정

SSM Parameter Store에 엔드포인트 등록:

```bash
aws ssm put-parameter \
  --name /emergency-orchestrator/cxr-endpoint \
  --value "https://your-cxr-api.example.com/inference" \
  --type String
```

#### 2. CXR API 요청 형식

Connector가 CXR API로 보내는 요청:

```json
{
  "case_id": "a1b2c3d4",
  "image_url": "s3://bucket/path/to/image.dcm",
  "metadata": {
    "patient_age": 65,
    "patient_sex": "M"
  }
}
```

#### 3. CXR API 응답 형식

CXR API는 다음 형식으로 응답해야 합니다:

```json
{
  "diagnosis": "Cardiomegaly with possible pulmonary edema",
  "confidence": 0.82,
  "diseases": [
    {"name": "Cardiomegaly", "probability": 0.85},
    {"name": "Pulmonary Edema", "probability": 0.78}
  ],
  "lesions": [
    {
      "type": "opacity",
      "location": "bilateral perihilar",
      "bbox": [x, y, w, h]
    }
  ],
  "severity": "moderate",
  "key_findings": [
    "Enlarged cardiac silhouette",
    "Bilateral perihilar opacities"
  ],
  "rationale": "Chest X-ray shows enlarged heart with signs of fluid overload"
}
```

#### 4. 인증

CXR API가 인증을 요구하는 경우, Connector Lambda에 환경변수 추가:

```yaml
Environment:
  Variables:
    CXR_API_KEY: !Sub '{{resolve:secretsmanager:cxr-api-key}}'
```

그리고 `cxr_connector/lambda_function.py`의 `call_cxr_api` 함수 수정:

```python
headers = {
    'Authorization': f'Bearer {os.environ.get("CXR_API_KEY")}'
}

response = requests.post(
    CXR_API_ENDPOINT,
    json=payload,
    headers=headers,
    timeout=300
)
```

### Mock 모드

CXR API가 설정되지 않은 경우, Connector는 자동으로 mock 응답을 생성합니다.

## ECG Modal 연동 (준비 중)

### 현재 상태
ECG Connector는 현재 mock 응답만 제공합니다.

### 연동 준비

`deploy/modal_connectors/ecg_connector/lambda_function.py` 파일을 수정하여 실제 ECG 시스템과 연동:

```python
def call_ecg_api(case_id, ecg_data):
    """Call external ECG inference API."""
    
    ECG_API_ENDPOINT = os.environ.get('ECG_API_ENDPOINT')
    
    payload = {
        "case_id": case_id,
        "ecg_data": ecg_data
    }
    
    response = requests.post(
        ECG_API_ENDPOINT,
        json=payload,
        timeout=60
    )
    
    response.raise_for_status()
    result = response.json()
    
    # Transform to standardized format
    return {
        "modality": "ECG",
        "finding": result.get('interpretation', 'Unknown'),
        "confidence": result.get('confidence', 0.0),
        "details": {
            "rhythm": result.get('rhythm'),
            "rate": result.get('rate'),
            "intervals": result.get('intervals'),
            "st_changes": result.get('st_changes'),
            "key_findings": result.get('key_findings', [])
        },
        "rationale": result.get('rationale', 'ECG analysis completed'),
        "timestamp": datetime.utcnow().isoformat()
    }
```

### ECG 데이터 형식

ECG 데이터는 다음 형식으로 전달:

```json
{
  "format": "MUSE_XML|HL7|DICOM",
  "data_url": "s3://bucket/path/to/ecg.xml",
  "raw_data": "base64_encoded_data"
}
```

## LAB Modal 연동 (준비 중)

### 현재 상태
LAB Connector는 현재 mock 응답만 제공합니다.

### 연동 준비

Lab 시스템과의 연동은 일반적으로 HL7 메시지나 FHIR API를 통해 이루어집니다.

#### HL7 연동 예시

```python
def parse_hl7_lab_results(hl7_message):
    """Parse HL7 lab results."""
    
    # Parse HL7 message (using hl7apy or similar library)
    results = {}
    
    # Extract lab values
    # OBX segments contain observation results
    
    return {
        "modality": "LAB",
        "finding": generate_lab_summary(results),
        "confidence": 0.95,  # Lab results are typically high confidence
        "details": results,
        "rationale": "Laboratory studies completed",
        "timestamp": datetime.utcnow().isoformat()
    }
```

#### FHIR API 연동 예시

```python
def call_fhir_lab_api(patient_id):
    """Call FHIR API for lab results."""
    
    FHIR_ENDPOINT = os.environ.get('FHIR_ENDPOINT')
    
    # Query for recent lab observations
    url = f"{FHIR_ENDPOINT}/Observation"
    params = {
        "patient": patient_id,
        "category": "laboratory",
        "_sort": "-date",
        "_count": 50
    }
    
    response = requests.get(url, params=params)
    response.raise_for_status()
    
    bundle = response.json()
    
    # Parse FHIR bundle and extract lab values
    lab_results = parse_fhir_observations(bundle)
    
    return {
        "modality": "LAB",
        "finding": generate_lab_summary(lab_results),
        "confidence": 0.95,
        "details": lab_results,
        "rationale": "Laboratory studies retrieved from FHIR server",
        "timestamp": datetime.utcnow().isoformat()
    }
```

## 새로운 모달 추가

### 1. Connector Lambda 생성

```bash
mkdir -p deploy/modal_connectors/new_modal_connector
```

`lambda_function.py` 작성:

```python
def handler(event, context):
    case_id = event.get('case_id')
    patient = event.get('patient')
    
    # Call external API or process data
    result = call_new_modal_api(case_id, patient)
    
    # Return standardized format
    return {
        "modality": "NEW_MODAL",
        "finding": result['finding'],
        "confidence": result['confidence'],
        "details": result['details'],
        "rationale": result['rationale'],
        "timestamp": datetime.utcnow().isoformat()
    }
```

### 2. template.yaml 업데이트

```yaml
NewModalConnectorFunction:
  Type: AWS::Serverless::Function
  Properties:
    FunctionName: emergency-new-modal-connector
    Handler: lambda_function.handler
    CodeUri: deploy/modal_connectors/new_modal_connector/
    Timeout: 60
```

### 3. Step Functions 업데이트

`deploy/step_functions/orchestration.asl.json`의 `RouteModality` Choice에 추가:

```json
{
  "Variable": "$.modality",
  "StringEquals": "NEW_MODAL",
  "Next": "CallNewModal"
}
```

그리고 새로운 State 추가:

```json
"CallNewModal": {
  "Type": "Task",
  "Resource": "arn:aws:states:::lambda:invoke",
  "Parameters": {
    "FunctionName": "${NewModalConnectorFunctionArn}",
    "Payload.$": "$"
  },
  "ResultSelector": {
    "body.$": "$.Payload"
  },
  "OutputPath": "$.body",
  "End": true
}
```

### 4. Fusion Decision 로직 업데이트

`deploy/orchestrator/fusion_decision/decision_engine.py`에 새로운 모달 관련 로직 추가.

## 테스트

### 단위 테스트

각 Connector를 독립적으로 테스트:

```bash
# CXR Connector 테스트
aws lambda invoke \
  --function-name emergency-cxr-connector \
  --payload file://test_cxr_input.json \
  output.json
```

### 통합 테스트

전체 워크플로우 테스트:

```bash
curl -X POST $API_ENDPOINT/case \
  -H "Content-Type: application/json" \
  -d @test_request.json
```

## 모니터링

각 모달의 성능 모니터링:

```bash
# CloudWatch Logs 확인
aws logs tail /aws/lambda/emergency-cxr-connector --follow

# 메트릭 확인
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Duration \
  --dimensions Name=FunctionName,Value=emergency-cxr-connector \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-02T00:00:00Z \
  --period 3600 \
  --statistics Average,Maximum
```

## 문제 해결

### Timeout 문제

모달 추론이 오래 걸리는 경우 Lambda timeout 증가:

```yaml
Timeout: 300  # 5 minutes
```

### 메모리 부족

큰 이미지나 데이터 처리 시 메모리 증가:

```yaml
MemorySize: 2048  # 2GB
```

### API 연결 실패

- VPC 설정 확인
- Security Group 규칙 확인
- API 엔드포인트 접근 가능 여부 확인
