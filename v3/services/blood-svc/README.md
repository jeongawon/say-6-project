# blood-svc - 혈액검사 분석 마이크로서비스

> **담당자**: 팀원C
> **버전**: v3.0.0
> **분석 방식**: 규칙 기반 (참조 범위 비교 + 복합 평가)

---

## 서비스 개요

혈액검사 수치를 입력받아 정상/비정상/위급 여부를 판정하고,
복합 평가(심부전, 심근손상, 신기능, 빈혈, 감염/염증)를 수행한 뒤,
AWS Bedrock(Claude)을 통해 한국어 판독 소견서를 자동 생성하는 마이크로서비스입니다.

**분석 패널:**
- **CBC**: WBC, RBC, Hemoglobin, Hematocrit, Platelets, MCV, MCH, MCHC
- **BMP (기초대사패널)**: Na, K, Cl, CO2, BUN, Creatinine, Glucose, Calcium
- **심장 표지자**: BNP, NT-proBNP, Troponin I/T, CK-MB
- **간기능**: AST, ALT, ALP, Bilirubin (Total/Direct), Albumin
- **응고**: D-dimer, PT/INR
- **염증**: CRP, Procalcitonin, ESR

**복합 평가:**
- 심부전 지표 (BNP + NT-proBNP)
- 심근 손상 지표 (Troponin + CK-MB)
- 신기능 장애 (Creatinine + BUN/Cr ratio)
- 빈혈 (Hemoglobin + MCV 기반 유형 분류)
- 감염/염증 지표 (WBC + CRP + Procalcitonin)

---

## 파일별 역할

| 파일 | 역할 |
|------|------|
| `main.py` | FastAPI 앱 진입점. `/healthz`, `/readyz`, `/predict` 엔드포인트 정의 |
| `config.py` | 환경변수 설정 (pydantic-settings). 서비스명, 포트, Bedrock 리전/모델 등 |
| `analyzer.py` | **핵심 분석 로직**. 개별 검사 판정 + 복합 평가 (심부전/빈혈/감염 등) |
| `reference_ranges.py` | **정상 범위 테이블**. 각 검사항목의 단위, 정상범위, 위급값, 성별/나이별 범위 |
| `report/blood_report_generator.py` | Bedrock 호출로 한국어 소견서 생성 (실패 시 템플릿 폴백) |
| `report/__init__.py` | 패키지 초기화 |
| `Dockerfile` | 컨테이너 빌드 설정 (Python 3.11, uvicorn) |
| `requirements.txt` | Python 의존성 목록 |

---

## 팀원이 수정해야 할 파일

### 1. `analyzer.py` — 검사항목 추가/수정
- `_evaluate_test()`: 개별 검사 판정 로직 커스텀
- `_cardiac_assessment()`, `_renal_assessment()`, `_anemia_assessment()`, `_infection_assessment()`: 복합 평가 로직 수정
- 새로운 복합 평가 함수 추가 시 `analyze_blood()`에서 호출 추가

### 2. `reference_ranges.py` — 정상 범위 값 조정
- `RANGES` 딕셔너리에 새 검사항목 추가
- 기존 항목의 정상범위, 위급값(critical), 성별/나이별 범위 조정
- `tiers` (단계별 구분)이 필요한 항목 추가 (예: BNP, Procalcitonin처럼)

### 3. `report/blood_report_generator.py` — 소견서 프롬프트 커스텀
- `_call_bedrock()` 함수 내 `prompt` 변수를 수정하여 소견서 형식/내용 변경
- `_template_report()` 함수로 Bedrock 미사용 시 폴백 형식 조정

---

## 로컬 실행 방법

```bash
# 1. 의존성 설치
cd v3/services/blood-svc
pip install -r requirements.txt

# 2. shared 스키마 경로 설정 (로컬에서는 sys.path 수동 설정 필요)
#    main.py의 sys.path.insert(0, "/app/shared") 를
#    실제 shared 폴더 경로로 변경하거나, PYTHONPATH에 추가
export PYTHONPATH=$PYTHONPATH:$(pwd)/../shared

# 3. 환경변수 설정 (선택)
export LOG_LEVEL=DEBUG
export BEDROCK_REGION=us-east-1
export BEDROCK_MODEL_ID=anthropic.claude-sonnet-4-6-20250514

# 4. 서버 실행
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

---

## API 스펙

### `POST /predict`

**Request Body** (`PredictRequest`):
```json
{
  "patient_id": "P001",
  "patient_info": {
    "age": 65,
    "sex": "M",
    "chief_complaint": "흉통 및 호흡곤란",
    "history": ["고혈압", "당뇨", "만성신장질환"]
  },
  "data": {
    "cbc": {
      "wbc": 12.5,
      "rbc": 4.2,
      "hemoglobin": 11.0,
      "hematocrit": 33.0,
      "platelets": 180,
      "mcv": 78,
      "mch": 26,
      "mchc": 33
    },
    "bmp": {
      "sodium": 138,
      "potassium": 5.8,
      "chloride": 102,
      "co2": 22,
      "bun": 35,
      "creatinine": 1.8,
      "glucose": 145,
      "calcium": 9.0
    },
    "cardiac": {
      "bnp": 1200,
      "nt_probnp": 5000,
      "troponin_i": 0.02,
      "troponin_t": 0.008,
      "ck_mb": 3.5
    },
    "liver": {
      "ast": 45,
      "alt": 62,
      "alp": 120,
      "bilirubin_total": 1.0,
      "bilirubin_direct": 0.2,
      "albumin": 3.2
    },
    "coag": {
      "d_dimer": 1.2,
      "pt_inr": 1.1
    },
    "inflammatory": {
      "crp": 25.0,
      "procalcitonin": 0.3,
      "esr": 40
    }
  },
  "context": {
    "chest": {"summary": "심비대 소견"},
    "ecg": {"summary": "LVH with ST changes"}
  }
}
```

**Response Body** (`PredictResponse`):
```json
{
  "status": "success",
  "modal": "blood",
  "findings": [
    {
      "name": "potassium_abnormal",
      "detected": true,
      "confidence": 0.92,
      "detail": "Potassium (K): 5.8 mEq/L (high) [ref: 3.5-5.0 mEq/L]"
    },
    {
      "name": "heart_failure_indicator",
      "detected": true,
      "confidence": 0.98,
      "detail": "BNP 1200 pg/mL (strongly elevated)"
    }
  ],
  "summary": "Abnormal findings: heart failure indicator (98%), ...",
  "report": "[혈액검사 판독 소견서] ...",
  "metadata": {
    "service": "blood-svc",
    "version": "3.0.0",
    "inference_time_ms": 55,
    "tests_analyzed": 20,
    "abnormal_count": 8
  }
}
```

---

## 입력 데이터 형식 (`req.data`) 상세

데이터는 **패널별 중첩 구조** 또는 **플랫 구조** 모두 지원합니다.

### 패널별 중첩 구조 (권장)

```json
{
  "cbc": {"wbc": 12.5, "hemoglobin": 11.0, ...},
  "bmp": {"sodium": 138, "potassium": 5.8, ...},
  "cardiac": {"bnp": 1200, ...},
  "liver": {"ast": 45, ...},
  "coag": {"d_dimer": 1.2, ...},
  "inflammatory": {"crp": 25.0, ...}
}
```

### 플랫 구조 (단순 사용 시)

```json
{
  "wbc": 12.5,
  "hemoglobin": 11.0,
  "sodium": 138,
  "potassium": 5.8,
  "bnp": 1200,
  "crp": 25.0
}
```

### 지원 검사항목 전체 목록

| 패널 | 키 이름 | 단위 | 정상 범위 | 위급값 |
|------|---------|------|----------|--------|
| **CBC** | `wbc` | x10^3/uL | 4.5-11.0 | < 2.0 / > 30.0 |
| | `rbc` | x10^6/uL | M: 4.5-5.5 / F: 4.0-5.0 | < 2.0 |
| | `hemoglobin` | g/dL | M: 13.5-17.5 / F: 12.0-16.0 | < 7.0 / > 20.0 |
| | `hematocrit` | % | M: 38-50 / F: 36-44 | < 20 / > 60 |
| | `platelets` | x10^3/uL | 150-400 | < 50 / > 1000 |
| | `mcv` | fL | 80-100 | - |
| | `mch` | pg | 27-33 | - |
| | `mchc` | g/dL | 32-36 | - |
| **BMP** | `sodium` | mEq/L | 136-145 | < 120 / > 160 |
| | `potassium` | mEq/L | 3.5-5.0 | < 2.5 / > 6.5 |
| | `chloride` | mEq/L | 98-106 | < 80 / > 120 |
| | `co2` | mEq/L | 23-29 | < 10 / > 40 |
| | `bun` | mg/dL | 7-20 | > 100 |
| | `creatinine` | mg/dL | M: 0.7-1.3 / F: 0.6-1.1 | > 10.0 |
| | `glucose` | mg/dL | 70-100 (공복) | < 40 / > 500 |
| | `calcium` | mg/dL | 8.5-10.5 | < 6.0 / > 13.0 |
| **심장** | `bnp` | pg/mL | 0-100 | - |
| | `nt_probnp` | pg/mL | 0-125 (나이별 조정) | - |
| | `troponin_i` | ng/mL | 0-0.04 | > 0.4 |
| | `troponin_t` | ng/mL | 0-0.01 | > 0.1 |
| | `ck_mb` | ng/mL | 0-5.0 | - |
| **간기능** | `ast` | U/L | 10-40 | > 1000 |
| | `alt` | U/L | 7-56 | > 1000 |
| | `alp` | U/L | 44-147 | - |
| | `bilirubin_total` | mg/dL | 0.1-1.2 | > 15.0 |
| | `bilirubin_direct` | mg/dL | 0.0-0.3 | - |
| | `albumin` | g/dL | 3.5-5.5 | < 1.5 |
| **응고** | `d_dimer` | ug/mL | 0-0.5 | - |
| | `pt_inr` | (비율) | 0.8-1.2 | > 5.0 |
| **염증** | `crp` | mg/L | 0-10 | - |
| | `procalcitonin` | ng/mL | 0-0.1 | - |
| | `esr` | mm/hr | M: 0-15 / F: 0-20 | - |

---

## 기타 엔드포인트

| 엔드포인트 | 메서드 | 용도 |
|-----------|--------|------|
| `/healthz` | GET | Liveness probe (항상 200) |
| `/readyz` | GET | Readiness probe (준비 완료 시 200, 아니면 503) |
