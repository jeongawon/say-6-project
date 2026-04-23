# Lab-svc — 혈액검사 Rule Engine 해석 서비스

응급실 혈액검사 수치를 주호소(Chief Complaint) 맥락에 맞게 해석하는 Rule Engine 기반 서비스.
ML 모델 대신 수십 년간 검증된 임상 cut-off 기준을 사용하며, < 10ms 응답 속도를 제공한다.

## 아키텍처

```
POST /predict 요청
  → Layer 1: Input Processor (입력 검증 + 주호소 → Profile 매핑)
  → Layer 2: Rule Engine (Stage A: Critical Flags → Stage B: Profile별 규칙 → Stage C: Full Scan)
  → Layer 3: Report Generator (risk_level + cross_modal_hints + summary)
  → JSON 응답
```

## 디렉터리 구조

```
Lab-svc/
├── config.py                          # HOST, PORT, LOG_LEVEL
├── main.py                            # FastAPI (POST /predict, GET /health, /ready)
├── pipeline.py                        # Layer 1→2→3 오케스트레이션
├── thresholds.py                      # 임상 정상 범위 + Critical Flag + 유효 범위
├── layer1_input_processor/
│   ├── complaint_mapper.py            # 약어 확장 + 7개 Profile 매핑
│   └── processor.py                   # 입력 검증 + indicator 생성
├── layer2_rule_engine/
│   ├── stage_a_critical.py            # 8개 Critical Flag (주호소 무관)
│   ├── stage_b_complaint.py           # 7개 Profile별 규칙
│   ├── stage_c_fullscan.py            # 나머지 항목 스캔
│   └── engine.py                      # Stage A→B→C 오케스트레이션
├── layer3_report_generator/
│   └── generator.py                   # risk_level + hints + summary
├── shared/schemas.py                  # Pydantic 모델
├── Dockerfile
└── requirements.txt
```

## 실행 방법

```bash
# Docker
docker build -t lab-svc .
docker run -p 8000:8000 lab-svc

# 로컬
pip install -r requirements.txt
python main.py
```

## API

### POST /predict

```json
{
  "patient_id": "P001",
  "patient_info": { "chief_complaint": "chest pain" },
  "data": {
    "lab_values": {
      "wbc": 11.2, "hemoglobin": 10.5, "potassium": 6.8,
      "creatinine": 1.8, "glucose": 220, "sodium": 138
    }
  }
}
```

### 응답 예시

```json
{
  "status": "ok",
  "modal": "lab",
  "complaint_profile": "CARDIAC",
  "risk_level": "critical",
  "findings": [
    {
      "name": "critical_potassium_high",
      "category": "critical",
      "severity": "critical",
      "detail": "칼륨 6.8 mEq/L — 고칼륨혈증으로 심정지 위험",
      "measurement": { "value": 6.8, "unit": "mEq/L", "reference_low": 3.5, "reference_high": 5.0, "status": "high" }
    },
    {
      "name": "cardiac_glucose_high",
      "category": "primary",
      "severity": "moderate",
      "detail": "혈당 220 mg/dL — MI 예후 불량 인자"
    }
  ],
  "suggested_next_actions": [
    { "target_modal": "ECG", "reason": "K+ 6.8 — 심전도 변화 확인", "priority": 10 }
  ],
  "lab_summary": [ ... ],
  "measurements": { "critical_count": 1, "primary_count": 3, "total_findings": 6 }
}
```

---

## 설계 상세

### 3-Stage Rule Engine

| Stage | 역할 | 실행 조건 |
|-------|------|----------|
| Stage A | Critical Flags (8개) | 모든 입력, 주호소 무관 |
| Stage B | Complaint-Focused | Profile별 우선 검사 |
| Stage C | Full Scan | Stage B 미검사 항목 |

### Critical Flags (Stage A)

| 조건 | Flag | severity |
|------|------|----------|
| K+ > 6.5 | 심정지 위험 | critical |
| K+ < 2.5 | 치명적 부정맥 위험 | critical |
| Na+ < 120 | 경련/뇌부종 위험 | critical |
| Glucose > 500 | DKA/HHS 의심 | critical |
| Glucose < 40 | 즉시 포도당 투여 | critical |
| Lactate > 4.0 | 조직 저관류/쇼크 | critical |
| Hgb < 7.0 | 수혈 고려 | critical |
| PLT < 20 | 자발 출혈 위험 | critical |

### 7개 Complaint Profile별 우선 확인 검사 (Stage B)

| Profile | 트리거 주호소 | 우선 확인 검사 순서 |
|---------|-------------|-------------------|
| CARDIAC | 가슴통증, 심계항진, 실신 | troponin → BNP → K+ → glucose → Cr → Hgb |
| SEPSIS | 발열, 오한, 감염 | lactate → WBC → PLT → Cr → glucose |
| GI | 복통, 구토, 흑색변 | amylase → AST → Hgb → BUN/Cr ratio → Ca2+ |
| RENAL | 옆구리 통증, 혈뇨 | Cr → BUN → K+ → Na+ → Ca2+ |
| RESPIRATORY | 호흡곤란, 기침 | WBC → lactate → Hgb |
| NEUROLOGICAL | 두통, 경련, 의식변화 | glucose → Na+ → Ca2+ → K+ → WBC |
| GENERAL | 전신 쇠약, 분류 불가 | WBC → Hgb → Cr → glucose |

### 임상 정상 범위 (12개 Value_Feature)

| Feature | 정상 범위 | 단위 |
|---------|----------|------|
| wbc | 4.5 – 11.0 | K/uL |
| hemoglobin | 12.0 – 17.5 | g/dL |
| platelet | 150 – 400 | K/uL |
| creatinine | 0.7 – 1.2 | mg/dL |
| bun | 7 – 20 | mg/dL |
| sodium | 136 – 145 | mEq/L |
| potassium | 3.5 – 5.0 | mEq/L |
| glucose | 70 – 100 | mg/dL |
| ast | 0 – 40 | U/L |
| albumin | 3.5 – 5.5 | g/dL |
| lactate | 0.5 – 2.0 | mmol/L |
| calcium | 8.5 – 10.5 | mg/dL |

### 3-Tier 결측률 전략

| Tier | 항목 | 결측률 | 전략 |
|------|------|--------|------|
| Tier 1 | wbc, hemoglobin, platelet, creatinine, bun, sodium, potassium, glucose | < 10% | 값만 사용 |
| Tier 2 | ast, albumin, lactate, calcium | 50~65% | 값 + indicator |
| Tier 3 | troponin_t, bnp, amylase | > 80% | indicator만 (MNAR) |

### Risk Level 결정

| Level | 조건 |
|-------|------|
| critical | Critical Flag ≥ 1개 |
| urgent | primary 이상 수치 ≥ 2개 |
| watch | primary 1개 또는 미측정 경고 |
| routine | 모든 수치 정상 |

### Cross-modal Hints (SuggestedNextAction)

| 조건 | 대상 모달 | 사유 |
|------|----------|------|
| K+ > 5.5 or < 3.0 | ECG | 전해질 이상 → 심전도 변화 확인 |
| troponin + CARDIAC | ECG | ACS 의심 → ST 변화 교차 확인 |
| BNP + RESPIRATORY | CXR | 심부전 의심 → 폐부종/심비대 확인 |
| WBC↑ + SEPSIS | CXR | 감염 초점 → 폐렴 여부 확인 |
| Lactate > 2.0 | ECG | 패혈증 → 심근 기능 영향 확인 |

### SageMaker 데이터 분석 결과 (MIMIC-IV ED, 44,755명)

| Profile | 환자 수 | 비율 |
|---------|--------|------|
| GENERAL | 16,870 | 37.7% |
| GI | 9,044 | 20.2% |
| NEUROLOGICAL | 5,687 | 12.7% |
| CARDIAC | 5,493 | 12.3% |
| RESPIRATORY | 3,495 | 7.8% |
| SEPSIS | 3,307 | 7.4% |
| RENAL | 859 | 1.9% |

### 골든셋 테스트 결과 (200건)

| Risk Level | 건수 | 비율 |
|-----------|------|------|
| critical | 9 | 4.5% |
| urgent | 5 | 2.5% |
| watch | 130 | 65.0% |
| routine | 56 | 28.0% |

---

## 기술 스택

- Python 3.11
- FastAPI + Uvicorn + Pydantic
- Docker
- ML 모델 없음 (Rule Engine only)
- 응답 시간: < 10ms
