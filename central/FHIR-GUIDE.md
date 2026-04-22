# FHIR 가이드 — 팀원용 설명 문서

## 1. FHIR은 DB인가?

FHIR 자체는 **데이터 규격(표준)**이다. "환자 정보는 이런 JSON 형태로 저장해라"라는 약속.

근데 **HAPI FHIR 서버**는 그 규격을 구현한 **DB 서버**다. Docker로 띄우면 REST API로 데이터 넣고 빼는 저장소가 된다. 내부에 PostgreSQL을 달 수도 있다.

```
FHIR = 데이터 규격 (JSON 형태 정의)
HAPI FHIR 서버 = 그 규격을 따르는 DB 서버 (Docker로 띄움)
```

비유하면:
```
SQL = 쿼리 언어 규격
PostgreSQL = 그 규격을 구현한 DB 서버

FHIR = 의료 데이터 규격
HAPI FHIR = 그 규격을 구현한 DB 서버
```

---

## 2. 이 프로젝트에서 왜 FHIR을 쓰는가

프로젝트에서 실제 병원 EMR을 연동할 수 없다.
대신 FHIR R4 표준을 준수하면 **"실배포 확장성 있음"** 을 심사관에게 증명할 수 있다.

- Mock FHIR 서버 = HAPI FHIR R4 Docker (`localhost:8080/fhir`)
- 실제 병원 EMR로 스위칭 시 `FHIR_BASE_URL` 환경변수 **한 줄 교체**로 끝
- 별도 DB(PostgreSQL 등) 직접 구축 불필요 — HAPI FHIR 서버가 곧 DB

---

## 3. 저장소 구조 (2개면 충분)

```
1. HAPI FHIR 서버 (내부 PostgreSQL) → 모든 메타데이터
   - 환자 정보, 바이탈, 모달 결과, 오더 상태, 리포트

2. S3 → 바이너리 파일
   - CXR 이미지 (PNG), ECG 파형 (WFDB)
   - FHIR에는 URL만 저장 (DocumentReference)
```

---

## 4. "내부 DB를 하나 더 둬야 한다"에 대해


| 저장하려는 것 | 필요한가? | 이유 |
|-------------|---------|------|
| 환자 정보, 모달 결과, 오더 상태 | ❌ 불필요 | HAPI FHIR 서버가 이미 이 역할 |
| AI 결과 (확실하지 않은 결과) | ❌ 불필요 | FHIR `status: "preliminary"` = "확정 아닌 임시 결과". 실제 병원 EMR에서도 이렇게 동작 |
| 세션, 로그인, 사용자 관리 | △ 졸작 범위에선 불필요 | 인증 없이 가도 됨 |
| 원본 이미지, 파형 파일 | ❌ DB 아님 | S3(오브젝트 스토리지)에 저장. FHIR에는 URL만 |


---

## 5. FHIR 없이 하면 어떻게 되는가

PostgreSQL에 직접 테이블을 만들어야 한다:

```sql
-- 환자
CREATE TABLE patients (
    id UUID PRIMARY KEY,
    mrn VARCHAR,
    name VARCHAR,
    gender VARCHAR,
    birth_date DATE,
    created_at TIMESTAMP
);

-- ED 방문
CREATE TABLE encounters (
    id UUID PRIMARY KEY,
    patient_id UUID REFERENCES patients(id),
    status VARCHAR,
    chief_complaint TEXT,
    started_at TIMESTAMP,
    ended_at TIMESTAMP
);

-- 바이탈 + 모달 결과
CREATE TABLE observations (
    id UUID PRIMARY KEY,
    encounter_id UUID REFERENCES encounters(id),
    category VARCHAR,
    code VARCHAR,
    value_text TEXT,
    value_number FLOAT,
    unit VARCHAR,
    status VARCHAR,
    created_at TIMESTAMP
);

-- 주호소 + 과거력
CREATE TABLE conditions (
    id UUID PRIMARY KEY,
    patient_id UUID REFERENCES patients(id),
    encounter_id UUID,
    category VARCHAR,
    code VARCHAR,
    text TEXT,
    verification VARCHAR,
    created_at TIMESTAMP
);

-- AI 검사 제안
CREATE TABLE service_requests (
    id UUID PRIMARY KEY,
    encounter_id UUID REFERENCES encounters(id),
    status VARCHAR,
    intent VARCHAR,
    modality VARCHAR,
    priority VARCHAR,
    reason TEXT,
    created_at TIMESTAMP
);

-- 최종 리포트
CREATE TABLE diagnostic_reports (
    id UUID PRIMARY KEY,
    encounter_id UUID REFERENCES encounters(id),
    status VARCHAR,
    conclusion TEXT,
    created_at TIMESTAMP,
    signed_at TIMESTAMP
);

-- 원본 파일 URL
CREATE TABLE document_references (
    id UUID PRIMARY KEY,
    encounter_id UUID REFERENCES encounters(id),
    content_type VARCHAR,
    url TEXT,
    created_at TIMESTAMP
);
```

그리고 추가로 해야 하는 것:
- 테이블 7개 설계 ← 위에 다 있음
- SQLAlchemy ORM 모델 정의
- Alembic 마이그레이션
- CRUD 함수 전부 직접 구현
- 검색 API 직접 구현
- 상태 전이 검증 SQL로 다시 구현
- **"FHIR 표준 준수" 심사 포인트 사라짐**

**HAPI FHIR 쓰면 이걸 전부 안 해도 된다.**
HAPI FHIR = PostgreSQL + 테이블 7개 + CRUD API + 검색 + 상태 관리가 이미 다 구현된 패키지.
Docker 하나 띄우면 끝. 직접 만들면 2주 더 걸림.

### 왜 테이블 설계가 필요 없는가

HAPI FHIR 서버를 Docker로 띄우면, 내부적으로 PostgreSQL에 FHIR 리소스용 테이블을 **자동으로 생성**한다.
Patient 테이블, Observation 테이블, ServiceRequest 테이블 등등.

```
우리가 하는 것:
  POST /fhir/Patient {"gender": "male", "birthDate": "1961-01-01"}

HAPI FHIR가 알아서 하는 것:
  → JSON 파싱
  → 내부 테이블에 INSERT
  → ID 부여
  → 검색 인덱스 생성
  → 참조 관계 검증
  → 응답 반환
```

우리는 SQL도 안 쓰고, 테이블 이름도 모르고, 그냥 FHIR JSON을 HTTP로 보내면
HAPI FHIR가 알아서 저장하고 조회해준다. 그래서 테이블 설계가 필요 없다.

---

## 6. 백엔드 폴더 구조 설명

### `app/fhir/` — 데이터 저장소 연결
HAPI FHIR 서버(=DB)와 통신하는 코드.
우리 데이터를 FHIR 규격 JSON으로 변환하고, 저장하고, 조회하는 역할.

| 파일 | 역할 |
|------|------|
| `client.py` | DB 연결 (HTTP로 FHIR 서버와 통신) |
| `resources.py` | 데이터 변환 (우리 포맷 → FHIR JSON). **가장 핵심 파일** |
| `codes.py` | 의료 코드 사전 (LOINC, ICD-10, SNOMED). ECG 24개 + CXR 7개 레이블 포함 |
| `code_mapper.py` | 한글 → 의료 코드 변환 ("흉통" → ICD-10 R07.9) |
| `state_machine.py` | 상태 전이 규칙 (draft→active→completed) |
| `adapter.py` | FHIR ↔ central 포맷 변환 |

### `app/api/` — REST API 엔드포인트
프론트엔드가 호출하는 API들. 각 파일이 하나의 기능.

| 파일 | API | 역할 |
|------|-----|------|
| `triage.py` | POST /triage/submit | 간호사가 환자 등록 → FHIR 저장 → AI 초기 모달 제안 |
| `orders.py` | POST /orders/{id}/approve\|reject | 의사가 AI 제안 승인/기각 → 모달 실행 → 결과 저장 |
| `encounters.py` | GET /encounters/{id}/* | 환자 데이터 조회 (바이탈, 모달 결과, 오더 목록) |
| `reports.py` | POST /reports/{id}/sign | 최종 리포트 의사 서명 (preliminary → final) |
| `ws.py` | WS /ws/encounter/{id} | 실시간 알림 (모달 완료, 새 제안 등) |

### `app/agent/` — AI 판단

| 파일 | 역할 |
|------|------|
| `decision_engine.py` | "다음에 어떤 검사할지" 판단하는 두뇌 (central에서 가져옴) |
| `bedrock_client.py` | Claude AI 호출 (한글→ICD-10 매핑 폴백용) |
| `tools.py` | AI가 검사 제안을 FHIR에 쓰고, 환자 상태를 읽는 도구 |

### `app/clients/` — 외부 서비스 호출

| 파일 | 역할 |
|------|------|
| `sagemaker_invoke.py` | K8s에 떠있는 ECG/CXR 모달 서비스 호출 |

### `tests/` — 테스트

| 파일 | 역할 |
|------|------|
| `fixtures/` | 테스트용 샘플 데이터 (아직 비어있음) |

---

## 7. API 엔드포인트 전체 목록

| Method | Path | 설명 |
|--------|------|------|
| POST | `/triage/submit` | 트리아지 제출 → Patient+Encounter+Vitals+Condition 생성 |
| POST | `/orders/{id}/approve` | 의사 승인 → SR active → 모달 실행 → 결과 저장 |
| POST | `/orders/{id}/reject` | 의사 기각 → SR revoked → Agent 대안 제안 |
| GET | `/encounters/{id}` | Encounter 조회 |
| GET | `/encounters/{id}/observations` | 해당 Encounter의 Observation 목록 |
| GET | `/encounters/{id}/conditions` | 해당 Encounter의 Condition 목록 |
| GET | `/encounters/{id}/service-requests` | 해당 Encounter의 ServiceRequest 목록 |
| POST | `/reports/{id}/sign` | 의사 서명 → DiagnosticReport final |
| WS | `/ws/encounter/{id}` | 실시간 상태 업데이트 |
| GET | `/health` | 헬스체크 |

---

## 8. 전체 데이터 흐름 (한눈에 보기)

```
간호사 트리아지 입력
  │
  ▼
POST /triage/submit
  │
  ├→ Patient 생성 ──────────────────→ FHIR 서버 저장
  ├→ Encounter 생성 ────────────────→ FHIR 서버 저장
  ├→ Observation(바이탈 6개) 생성 ──→ FHIR 서버 저장
  ├→ Condition(주호소+과거력) 생성 ─→ FHIR 서버 저장
  │
  ├→ FusionDecisionEngine 호출
  │   └→ "chest pain이니까 CXR, ECG 찍자"
  │
  ├→ ServiceRequest 2개 생성 (draft) → FHIR 서버 저장
  └→ WebSocket 푸시 → 프론트에 "AI가 CXR, ECG를 권고합니다"

의사가 CXR 승인 버튼 클릭
  │
  ▼
POST /orders/{id}/approve
  │
  ├→ ServiceRequest: draft → active ─→ FHIR 서버 PATCH
  ├→ DocumentReference 생성 (원본 URL) → FHIR 서버 저장
  ├→ CXR 서비스(K8s) 호출
  │   └→ 결과: {"findings": [...], "confidence": 0.82}
  │
  ├→ resources.py가 FHIR Observation으로 변환
  ├→ Observation 저장 ──────────────→ FHIR 서버 저장
  ├→ ServiceRequest: active → completed → FHIR 서버 PATCH
  └→ WebSocket 푸시 → 프론트에 "CXR 결과 나왔습니다"

(ECG도 같은 흐름으로 반복)

모든 모달 완료 후
  │
  ▼
DiagnosticReport 생성 (SOAP 리포트)
  │
  ├→ status: "preliminary" (AI 생성) → FHIR 서버 저장
  │
  ▼
의사가 서명 버튼 클릭
  │
  ▼
POST /reports/{id}/sign
  │
  └→ status: "preliminary" → "final" → FHIR 서버 PATCH
```

---

## 9. 모달 서비스와의 관계

ECG/CXR 서비스는 FHIR을 모른다. 자기 포맷으로 결과만 뱉으면 끝.
백엔드가 중간에서 FHIR 규격으로 변환해준다.

```
CXR 서비스 (K8s)
  → {"findings": [{"name": "Cardiomegaly", "confidence": 0.82}]}
       │
       │  백엔드 resources.py가 변환
       ▼
  → {"resourceType": "Observation", "status": "preliminary", "valueString": "..."}
       │
       │  백엔드 client.py가 저장
       ▼
  → HAPI FHIR 서버 (PostgreSQL)
```

모달 서비스 코드는 건드릴 필요 없다.

---

## 10. 현재 docker-compose 구조

```yaml
services:
  postgres:       # DB (HAPI FHIR의 내부 저장소)
    image: postgres:16
    port: 5432

  hapi-fhir:      # FHIR API 서버 (PostgreSQL 위에서 동작)
    image: hapiproject/hapi:latest
    port: 8080
    depends_on: postgres

  backend:        # 우리 FastAPI 백엔드
    port: 8000
    depends_on: hapi-fhir
```

```
docker compose up -d
→ PostgreSQL + HAPI FHIR + 백엔드 3개 컨테이너가 뜸
```

---

## 요약

- FHIR = 의료 데이터 규격. HAPI FHIR = 그 규격을 구현한 DB 서버.
- HAPI FHIR 쓰면 테이블 설계, CRUD API, 검색, 상태 관리를 안 해도 됨.
- 안 쓰면 테이블 7개 + ORM + CRUD + 마이그레이션 직접 구현해야 함 (2주+).
- 저장소는 HAPI FHIR(PostgreSQL) + S3 두 개면 충분.
- 모달 서비스는 FHIR 몰라도 됨. 백엔드가 중간에서 변환.
- 백엔드 코드는 이미 다 짜여있음. 띄워서 테스트하면 됨.
