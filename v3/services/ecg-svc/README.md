# ecg-svc - 12-Lead ECG 분석 마이크로서비스

> **담당자**: 원정아
> **버전**: v3.0.0
> **분석 방식**: 규칙 기반 (Rule-based) — ML 모델 교체 예정

---

## 서비스 개요

12-lead ECG(심전도) 데이터를 입력받아 8가지 항목을 규칙 기반으로 분석하고,
AWS Bedrock(Claude)을 통해 한국어 판독 소견서를 자동 생성하는 마이크로서비스입니다.

**분석 항목:**
1. 심박수 분류 (서맥/정상/빈맥)
2. 리듬/부정맥 (심방세동, SVT, VT)
3. PR 간격 (방실차단, WPW)
4. QRS / 각차단 (RBBB, LBBB)
5. 심실비대 (LVH — Sokolow-Lyon/Cornell, RVH)
6. ST 분절 (상승/하강, 관상동맥 영역 매핑)
7. QT/QTc 간격 (Bazett 공식)
8. 전기축 편위

---

## 파일별 역할

| 파일 | 역할 |
|------|------|
| `main.py` | FastAPI 앱 진입점. `/healthz`, `/readyz`, `/predict` 엔드포인트 정의 |
| `config.py` | 환경변수 설정 (pydantic-settings). 서비스명, 포트, Bedrock 리전/모델 등 |
| `analyzer.py` | **핵심 분석 로직**. 8개 규칙 기반 ECG 분석 모듈 |
| `report/ecg_report_generator.py` | Bedrock 호출로 한국어 소견서 생성 (실패 시 템플릿 폴백) |
| `report/__init__.py` | 패키지 초기화 |
| `Dockerfile` | 컨테이너 빌드 설정 (Python 3.11, uvicorn) |
| `requirements.txt` | Python 의존성 목록 |

---

## 팀원이 수정해야 할 파일

### 1. `analyzer.py` — 실제 ECG 모델 추가 시 수정
현재는 **규칙 기반 템플릿**입니다. ML/DL 모델을 도입하려면:
- `analyze_ecg()` 함수에서 모델 로딩 및 추론 로직 추가
- 각 `_rate_analysis()`, `_rhythm_analysis()` 등 8개 함수를 모델 출력으로 교체
- `main.py`의 `lifespan()`에서 모델 로딩 코드 추가 필요

### 2. `report/ecg_report_generator.py` — 소견서 프롬프트 커스텀
- `_call_bedrock()` 함수 내 `prompt` 변수를 수정하여 소견서 형식/내용 변경
- `_template_report()` 함수로 Bedrock 미사용 시 폴백 형식 조정

### 3. `config.py` — 환경변수 추가
- 새로운 설정값이 필요하면 `Settings` 클래스에 필드 추가
- 예: 모델 경로, 추가 외부 서비스 URL 등

---

## 로컬 실행 방법

```bash
# 1. 의존성 설치
cd v3/services/ecg-svc
pip install -r requirements.txt

# 2. shared 스키마 경로 설정 (로컬에서는 sys.path 수동 설정 필요)
#    main.py의 sys.path.insert(0, "/app/shared") 를
#    실제 shared 폴더 경로로 변경하거나, PYTHONPATH에 추가
export PYTHONPATH=$PYTHONPATH:$(pwd)/../shared

# 3. 환경변수 설정 (선택)
export LOG_LEVEL=DEBUG
export BEDROCK_REGION=ap-northeast-2
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
    "chief_complaint": "흉통",
    "history": ["고혈압", "당뇨"]
  },
  "data": {
    "heart_rate": 78,
    "rhythm_regular": true,
    "p_wave_present": true,
    "pr_interval": 160,
    "qrs_duration": 90,
    "qt_interval": 400,
    "rr_intervals": [780, 790, 785],
    "leads": {
      "I":   {"r_amp": 0.8, "s_amp": -0.2, "st_dev": 0.0},
      "II":  {"r_amp": 1.2, "s_amp": -0.3, "st_dev": 0.0},
      "III": {"r_amp": 0.6, "s_amp": -0.4, "st_dev": 0.0},
      "aVR": {"r_amp": 0.2, "s_amp": -1.0, "st_dev": 0.0},
      "aVL": {"r_amp": 0.7, "s_amp": -0.1, "st_dev": 0.0},
      "aVF": {"r_amp": 0.9, "s_amp": -0.3, "st_dev": 0.0},
      "V1":  {"r_amp": 0.3, "s_amp": -1.2, "st_dev": 0.0},
      "V2":  {"r_amp": 0.5, "s_amp": -1.5, "st_dev": 0.0},
      "V3":  {"r_amp": 1.0, "s_amp": -0.8, "st_dev": 0.0},
      "V4":  {"r_amp": 1.5, "s_amp": -0.3, "st_dev": 0.0},
      "V5":  {"r_amp": 1.8, "s_amp": -0.2, "st_dev": 0.0},
      "V6":  {"r_amp": 1.5, "s_amp": -0.1, "st_dev": 0.0}
    }
  },
  "context": null
}
```

**Response Body** (`PredictResponse`):
```json
{
  "status": "success",
  "modal": "ecg",
  "findings": [
    {
      "name": "normal_sinus_rate",
      "detected": true,
      "confidence": 0.95,
      "detail": "Heart rate 78 bpm (normal range 60-100)"
    }
  ],
  "summary": "Normal ECG — no significant abnormalities detected.",
  "report": "[ECG 판독 소견서] ...",
  "metadata": {
    "service": "ecg-svc",
    "version": "3.0.0",
    "inference_time_ms": 42,
    "analysis_type": "rule-based"
  }
}
```

---

## 입력 데이터 형식 (`req.data`) 상세

| 필드 | 타입 | 단위 | 필수 | 설명 |
|------|------|------|------|------|
| `heart_rate` | float | bpm | 권장 | 심박수 |
| `rhythm_regular` | bool | - | 선택 (기본: true) | 리듬 규칙성 |
| `p_wave_present` | bool | - | 선택 (기본: true) | P파 존재 여부 |
| `pr_interval` | float | ms | 선택 | PR 간격 (정상: 120-200ms) |
| `qrs_duration` | float | ms | 선택 | QRS 폭 (정상: < 120ms) |
| `qt_interval` | float | ms | 선택 | QT 간격 |
| `rr_intervals` | list[float] | ms | 선택 | RR 간격 목록 (부정맥 분석용, 3개 이상 권장) |
| `leads` | dict | - | 권장 | 12-lead 데이터 (아래 참조) |

### `leads` 내부 구조

각 리드(`I`, `II`, `III`, `aVR`, `aVL`, `aVF`, `V1`~`V6`)는 다음 필드를 가집니다:

| 필드 | 타입 | 단위 | 설명 |
|------|------|------|------|
| `r_amp` | float | mV | R파 진폭 (양수) |
| `s_amp` | float | mV | S파 진폭 (음수) |
| `st_dev` | float | mV | ST 편위 (양수 = 상승, 음수 = 하강) |

---

## 기타 엔드포인트

| 엔드포인트 | 메서드 | 용도 |
|-----------|--------|------|
| `/healthz` | GET | Liveness probe (항상 200) |
| `/readyz` | GET | Readiness probe (준비 완료 시 200, 아니면 503) |
