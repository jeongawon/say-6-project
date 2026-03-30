# Central Orchestrator (중앙 오케스트레이터)

## 서비스 개요

**LLM 기반 순차 검사 오케스트레이터** 서비스입니다.

| 항목 | 내용 |
|------|------|
| 담당 | 팀원D + 팀원E |
| 역할 | 환자 정보를 받아 AWS Bedrock LLM이 다음 검사를 결정하고, 모달 서비스를 순차적으로 호출하여 종합 소견서를 생성 |
| 프레임워크 | FastAPI + asyncpg + redis.asyncio |
| LLM | AWS Bedrock (Claude Sonnet) |

환자가 도착하면 Bedrock에게 "다음에 어떤 검사를 해야 하는가?"를 질의하고, 해당 모달 서비스(chest-svc, ecg-svc, blood-svc)를 호출한 뒤, 결과를 누적하여 다시 Bedrock에게 판단을 요청하는 **순차 루프**를 수행합니다. 최종적으로 report-svc를 통해 종합 소견서를 생성합니다.

---

## 핵심 동작 흐름

```
환자 도착 (POST /examine)
    │
    ▼
┌─────────────────────────────────┐
│  1. 세션 생성 (DB + Redis)       │
└─────────────┬───────────────────┘
              │
              ▼
┌─────────────────────────────────┐
│  2. Bedrock에 다음 검사 질의     │◄──────────┐
│     (환자 정보 + 누적 결과)      │           │
└─────────────┬───────────────────┘           │
              │                               │
         ┌────┴────┐                          │
         │  DONE?  │── Yes ──┐               │
         └────┬────┘         │               │
              │ No           │               │
              ▼              │               │
┌─────────────────────────┐  │               │
│  3. 모달 서비스 호출     │  │               │
│  (chest/ecg/blood-svc)  │  │               │
└─────────────┬───────────┘  │               │
              │              │               │
              ▼              │               │
┌─────────────────────────┐  │               │
│  4. 결과 누적            │──┼───────────────┘
│  (DB + Redis 저장)       │  │
└─────────────────────────┘  │
                             │
              ┌──────────────┘
              ▼
┌─────────────────────────────────┐
│  5. report-svc 호출             │
│     (종합 소견서 생성)           │
└─────────────┬───────────────────┘
              │
              ▼
┌─────────────────────────────────┐
│  6. 세션 완료 + 결과 반환        │
└─────────────────────────────────┘
```

---

## 파일별 역할 설명

| 파일 | 역할 |
|------|------|
| `main.py` | FastAPI 진입점. 앱 생성, lifespan(DB+Redis 초기화/정리), 헬스체크(/healthz, /readyz), 핵심 엔드포인트(POST /examine) 정의 |
| `orchestrator.py` | **핵심 순차 루프 로직**. 세션 생성 → Bedrock 검사 결정 → 모달 호출 → 결과 누적 → 반복 → 종합 소견서 생성 |
| `session_manager.py` | PostgreSQL + Redis 이중 세션 관리. 세션 생성/결과 저장/완료/실패 처리 |
| `modal_client.py` | 모달 서비스(chest-svc, ecg-svc, blood-svc) 및 report-svc HTTP 클라이언트. httpx 기반 비동기 호출 |
| `prompts.py` | Bedrock LLM 프롬프트 구성. 시스템 프롬프트 + 유저 메시지 템플릿 + JSON 응답 파싱 |
| `db.py` | asyncpg 기반 DB 연결 풀 생성 및 테이블 자동 생성 (CREATE TABLE IF NOT EXISTS) |
| `config.py` | pydantic-settings 기반 환경 변수 설정. 12-Factor 원칙 준수 |

---

## 팀원이 수정해야 할 파일

### 1. `prompts.py` — LLM 프롬프트 튜닝 (가장 중요)

검사 순서 결정 품질을 좌우하는 핵심 파일입니다.

- `NEXT_EXAM_SYSTEM_PROMPT`: 시스템 프롬프트 문구 수정
- `NEXT_EXAM_USER_TEMPLATE`: 유저 메시지 템플릿 수정
- `ask_bedrock_next_exam()`: temperature, max_tokens 등 LLM 파라미터 조정
- 검사 우선순위 로직, 새로운 검사 항목 추가 등

### 2. `orchestrator.py` — 순차 루프 로직 조정

- `max_exam_iterations`: 최대 반복 횟수 (config.py에서 설정)
- 종료 조건 커스터마이징
- 결과 누적 방식 변경

### 3. `modal_client.py` — 새 모달 서비스 추가 시

- `MODAL_URLS` 딕셔너리에 새 서비스 URL 추가
- `config.py`에 해당 URL 환경 변수 추가
- `prompts.py`의 시스템 프롬프트에도 새 검사 항목 추가 필요

### 4. `db.py` — 테이블 스키마 변경 시

- `CREATE_TABLES_SQL`에서 테이블 구조 수정
- 기존 데이터 마이그레이션 주의

---

## 환경변수 목록

| 환경변수 | 기본값 | 설명 |
|---------|--------|------|
| `DATABASE_URL` | `postgresql://postgres:postgres@postgres-svc:5432/drai` | PostgreSQL 접속 URL |
| `REDIS_URL` | `redis://redis-svc:6379/0` | Redis 접속 URL |
| `CHEST_URL` | `http://chest-svc:8000/predict` | 흉부 X-Ray 모달 서비스 URL |
| `ECG_URL` | `http://ecg-svc:8000/predict` | ECG 모달 서비스 URL |
| `BLOOD_URL` | `http://blood-svc:8000/predict` | 혈액 검사 모달 서비스 URL |
| `REPORT_URL` | `http://report-svc:8000/generate` | 종합 소견서 서비스 URL |
| `BEDROCK_REGION` | `ap-northeast-2` | AWS Bedrock 리전 |
| `BEDROCK_MODEL_ID` | `anthropic.claude-sonnet-4-6-20250514` | Bedrock 모델 ID |
| `MAX_EXAM_ITERATIONS` | `5` | 순차 검사 최대 반복 횟수 |
| `LOG_LEVEL` | `INFO` | 로그 레벨 (DEBUG, INFO, WARNING, ERROR) |

---

## 로컬 실행 방법

### 사전 요구사항

- Python 3.11+
- PostgreSQL (로컬 또는 Docker)
- Redis (로컬 또는 Docker)
- AWS 자격 증명 (Bedrock 호출용)

### 1. 의존성 설치

```bash
pip install fastapi uvicorn asyncpg redis httpx boto3 pydantic-settings
```

### 2. PostgreSQL + Redis 실행 (Docker)

```bash
# PostgreSQL
docker run -d --name postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=drai \
  -p 5432:5432 postgres:15

# Redis
docker run -d --name redis \
  -p 6379:6379 redis:7
```

### 3. 환경변수 설정 및 실행

```bash
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/drai"
export REDIS_URL="redis://localhost:6379/0"
export BEDROCK_REGION="ap-northeast-2"

# 서버 실행
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. 테스트 요청

```bash
curl -X POST http://localhost:8000/examine \
  -H "Content-Type: application/json" \
  -d '{
    "patient_id": "P001",
    "patient_info": {
      "age": 65,
      "sex": "M",
      "chief_complaint": "흉통 및 호흡곤란",
      "history": ["고혈압", "당뇨"]
    },
    "data": {
      "chest": {"image_path": "/data/xray/P001.dcm"},
      "ecg": {"signal_data": [...]},
      "blood": {"lab_values": {...}}
    }
  }'
```

---

## API 스펙

### `POST /examine` — 순차 검사 실행

**Request Body:**

```json
{
  "patient_id": "P001",
  "patient_info": {
    "age": 65,
    "sex": "M",
    "chief_complaint": "흉통 및 호흡곤란",
    "history": ["고혈압", "당뇨"]
  },
  "data": {
    "chest": {},
    "ecg": {},
    "blood": {}
  }
}
```

**Response Body:**

```json
{
  "status": "success",
  "patient_id": "P001",
  "session_id": 42,
  "exams_performed": ["chest", "ecg", "blood"],
  "modal_reports": [
    {
      "modal": "chest",
      "status": "success",
      "findings": [
        {"name": "cardiomegaly", "detected": true, "confidence": 0.87, "detail": "..."}
      ],
      "summary": "심비대 의심 소견"
    }
  ],
  "exam_decisions": [
    {"next_exam": "chest", "reasoning": "흉통 호소 → 흉부 X-Ray 우선 시행"},
    {"next_exam": "ecg", "reasoning": "심비대 소견 → ECG 확인 필요"},
    {"next_exam": "DONE", "reasoning": "충분한 검사 결과 확보"}
  ],
  "final_report": "종합 소견서 텍스트...",
  "diagnosis": "심비대 의심, 추가 심장 초음파 권고",
  "metadata": {
    "total_time_ms": 4521,
    "exams_count": 2,
    "iterations": 3
  }
}
```

### `GET /healthz` — Liveness 프로브

프로세스 생존 확인. 항상 200 반환.

### `GET /readyz` — Readiness 프로브

DB + Redis 연결 상태 확인. 모두 정상이면 200, 아니면 503 반환.

---

## DB 테이블 설명

### `patients` — 환자 기본 정보

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `patient_id` | TEXT (PK) | 환자 고유 식별자 |
| `age` | INT | 나이 |
| `sex` | TEXT | 성별 |
| `chief_complaint` | TEXT | 주호소 |
| `history` | JSONB | 병력 리스트 |
| `created_at` | TIMESTAMPTZ | 생성 시각 |

### `exam_sessions` — 검사 세션

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | SERIAL (PK) | 세션 ID |
| `patient_id` | TEXT (FK → patients) | 환자 ID |
| `status` | TEXT | 상태 (`in_progress` / `completed` / `failed`) |
| `patient_info` | JSONB | 환자 정보 스냅샷 |
| `created_at` | TIMESTAMPTZ | 생성 시각 |
| `completed_at` | TIMESTAMPTZ | 완료 시각 |

### `modal_results` — 모달 검사 결과

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | SERIAL (PK) | 결과 ID |
| `session_id` | INT (FK → exam_sessions) | 세션 ID |
| `modal` | TEXT | 모달 종류 (`chest` / `ecg` / `blood`) |
| `findings` | JSONB | 검출 결과 리스트 |
| `summary` | TEXT | 요약 소견 |
| `report` | TEXT | 상세 리포트 |
| `metadata` | JSONB | 추가 메타데이터 |
| `created_at` | TIMESTAMPTZ | 생성 시각 |

### `comprehensive_reports` — 종합 소견서

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | SERIAL (PK) | 리포트 ID |
| `session_id` | INT (FK → exam_sessions) | 세션 ID |
| `report` | TEXT | 종합 소견서 본문 |
| `diagnosis` | TEXT | 최종 진단 |
| `created_at` | TIMESTAMPTZ | 생성 시각 |

### ER 다이어그램

```
patients (1) ──< exam_sessions (1) ──< modal_results (N)
                                  └──< comprehensive_reports (1)
```
