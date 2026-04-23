# 멀티모달 임상 의사결정 지원 시스템 — DB 설계

## 1. DB 구성 (2개)

```
Aurora Serverless v2 (PostgreSQL 호환)
  └── patients 테이블  ← 환자 기본 정보

DynamoDB
  └── modal_results 테이블  ← ECG/Lab/CXR 추론 결과 (통합)
```

---

## 2. 전체 데이터 흐름

```
환자 도착 → 의료진이 기본 정보 입력
                    │
                    ▼
        Aurora patients 테이블에 INSERT
        {patient_id, age, gender, 증상, 과거력}
                    │
                    ▼
        Bedrock Agent가 Aurora에서 환자 정보 조회
        → 증상 기반으로 첫 번째 모달 판단
                    │
          ┌─────────┼─────────┐
          ▼         ▼         ▼
        ECG       Lab        CXR
        모달       모달        모달
        호출       호출        호출
        (선택적 — Agent가 필요한 모달만 호출)
          │         │         │
          └─────────┴─────────┘
                    │
                    ▼
        각 모달 결과 → DynamoDB modal_results에 INSERT
        {patient_id, modal_type, result, abnormal_flags, ...}
                    │
                    ▼
        Bedrock Agent가 누적된 결과 보고 다음 모달 판단
        → 모든 필요한 검사 완료 시 최종 종합 진단
```

---

## 3. Aurora Serverless v2 — patients 테이블

### 왜 Aurora Serverless v2인가

- PostgreSQL 완전 호환 → 기존 SQL 그대로 사용
- 사용할 때만 과금 → 데모/PoC 단계에서 ~$5/월 수준
- 트래픽 없을 때 자동 스케일 다운 (거의 0)
- 상시 운영 RDS 대비 비용 80% 절감

### 테이블 구조

```sql
CREATE TABLE patients (
    patient_id      VARCHAR(20) PRIMARY KEY,   -- 고유 환자 ID
    age             INTEGER,                    -- 나이
    gender          CHAR(1),                    -- 'M' | 'F'
    chief_complaint TEXT,                       -- 주 증상 (흉통, 호흡곤란 등)
    past_history    TEXT[],                     -- 과거력 배열 ['고혈압', '당뇨']
    created_at      TIMESTAMP DEFAULT NOW()
);
```

### 예시 레코드

```json
{
  "patient_id": "p10001",
  "age": 72,
  "gender": "F",
  "chief_complaint": "흉통, 호흡곤란",
  "past_history": ["고혈압"],
  "created_at": "2026-04-02T09:00:00Z"
}
```

---

## 4. DynamoDB — modal_results 테이블

### 왜 DynamoDB인가

- 모달 결과가 JSON 구조 (ECG는 24개 질환 확률, Lab은 수치 플래그 등 모달마다 다름)
- patient_id 기반 빠른 읽기 → Bedrock Agent가 이전 결과 즉시 조회 가능
- TTL 설정으로 오래된 결과 자동 삭제
- 모달이 선택적으로 호출되므로 스키마가 유연해야 함

### 테이블 구조

```
PK: patient_id (String)
SK: result_id  (String)  ← {modal_type}#{timestamp}
                            예: "ECG#2026-04-02T09:15:00Z"
```

### 공통 속성

```json
{
  "patient_id":    "p10001",
  "result_id":     "ECG#2026-04-02T09:15:00Z",
  "modal_type":    "ECG",
  "model_version": "v1.2.0",
  "inference_ms":  480,
  "ttl":           1743638400
}
```

### 모달별 result 속성

**ECG 결과**
```json
{
  "modal_type": "ECG",
  "predictions": {
    "atrial_fibrillation": 0.87,
    "heart_failure":       0.72,
    "hyperkalemia":        0.45
  },
  "abnormal_flags": {
    "heart_rate": {"value": 142, "status": "CRITICAL_HIGH"}
  }
}
```

**Lab 결과**
```json
{
  "modal_type": "LAB",
  "predicted_group": "Sepsis_Group",
  "probabilities": {
    "Sepsis_Group": 0.72,
    "Cardio_Group": 0.18
  },
  "abnormal_flags": {
    "potassium":  {"value": 6.1, "status": "CRITICAL_HIGH"},
    "creatinine": {"value": 2.8, "status": "HIGH"}
  }
}
```

**CXR 결과**
```json
{
  "modal_type": "CXR",
  "predictions": {
    "pulmonary_edema":    0.78,
    "cardiomegaly":       0.65,
    "pleural_effusion":   0.42
  },
  "abnormal_flags": {
    "pulmonary_edema": {"value": 0.78, "status": "HIGH"}
  }
}
```

### 환자 전체 검사 결과 조회

```python
import boto3

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('modal_results')

# 이 환자에게 호출된 모달 결과 전체 조회
response = table.query(
    KeyConditionExpression='patient_id = :pid',
    ExpressionAttributeValues={':pid': 'p10001'}
)

# 결과: 호출된 모달만 반환 (Lab 미호출 시 Lab 레코드 없음)
for item in response['Items']:
    print(item['modal_type'], item['result_id'])
# ECG  ECG#2026-04-02T09:15:00Z
# CXR  CXR#2026-04-02T10:10:00Z
# (Lab 없음 → 레코드 자체가 없음)
```

---

## 5. 비용 요약

| DB | 서비스 | 데모/PoC 예상 비용 |
|----|--------|:-----------------:|
| 환자 기본 정보 | Aurora Serverless v2 | ~$5/월 |
| 모달 추론 결과 | DynamoDB | ~$1/월 |
| 합계 | | ~$6/월 |
