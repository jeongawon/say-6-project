# Backend — FHIR 기반 응급 멀티모달 오케스트레이터

## FHIR이 뭔가요?

FHIR(Fast Healthcare Interoperability Resources)은 **의료 데이터 교환 국제 표준**입니다.
전 세계 병원 EMR(전자의무기록)이 이 표준을 따르고 있어서, FHIR로 만들면 어떤 병원 시스템에든 붙을 수 있습니다.

쉽게 말하면:
- 일반 웹 서비스에서 PostgreSQL이나 MongoDB를 쓰듯이
- 의료 시스템에서는 **FHIR 서버**를 DB처럼 씁니다
- 데이터를 JSON으로 저장하고, REST API로 CRUD합니다

## 이 프로젝트에서 왜 FHIR을 쓰나요?

졸작에서 실제 병원 EMR을 연동할 수 없습니다.
대신 FHIR R4 표준을 준수하면 **"실배포 확장성 있음"** 을 심사관에게 증명할 수 있습니다.

핵심 포인트:
- Mock FHIR 서버 = HAPI FHIR R4 Docker (`localhost:8080/fhir`)
- 실제 병원 EMR로 스위칭 시 `FHIR_BASE_URL` 환경변수 **한 줄 교체**로 끝
- 별도 DB(PostgreSQL 등) 구축 불필요 — FHIR 서버가 곧 DB

## FHIR 서버에 뭐가 저장되나요?

한 환자의 ED 방문 전체 이력이 FHIR 서버 안에 들어갑니다:

```
트리아지 제출 (간호사)
  → Patient (환자 정보)              → FHIR 저장
  → Encounter (이번 ED 방문)         → FHIR 저장
  → Observation (바이탈 6개)         → FHIR 저장
  → Condition (주호소 + 과거력)       → FHIR 저장

AI Agent가 모달 제안
  → ServiceRequest (draft/proposal)  → FHIR 저장

의사가 승인
  → ServiceRequest (active)          → FHIR PATCH

모달 실행 결과 (CXR/ECG/LAB)
  → DocumentReference (원본 파일 URL) → FHIR 저장
  → Observation (AI 분석 결과)        → FHIR 저장
  → ServiceRequest (completed)        → FHIR PATCH

최종 SOAP 리포트
  → DiagnosticReport (preliminary)   → FHIR 저장

의사 서명
  → DiagnosticReport (final)         → FHIR PATCH
```

## 7종 FHIR 리소스 설명

| 리소스 | 역할 | 이 프로젝트에서 |
|--------|------|----------------|
| **Patient** | 환자 1명의 정체 | MRN·나이·성별 |
| **Encounter** | 1회 내원 | ED 방문 1건 |
| **Observation** | 단일 측정값 | vitals 6개, lab N개, AI 출력 수치 |
| **Condition** | 진단·문제 | 주호소 1개, 과거력 N개 |
| **ServiceRequest** | 검사·시술 오더 | **Agent 제안 = 이 리소스** |
| **DiagnosticReport** | 여러 Observation 묶은 결론 | 최종 SOAP, 모달별 판독지 |
| **DocumentReference** | 외부 파일 포인터 | CXR PNG, ECG WFDB 경로 |

## 설계 철학 3가지

1. **FHIR 서버에는 메타데이터만** — 실제 영상·신호 파일은 S3에 두고 URL만 참조
2. **모든 AI 출력은 `status: "preliminary"`** — 의사 서명 전까지 "확정 아님" 상태
3. **상태 전이는 FHIR 리소스의 status 필드로** — 별도 DB 테이블 만들지 않음

## 핵심 흐름 — ServiceRequest 라이프사이클

이 프로젝트의 핵심은 ServiceRequest입니다.
AI Agent가 "다음에 어떤 검사를 할지" 제안하는 것이 곧 ServiceRequest 생성입니다.

```
                    의사 승인
  ┌─────────┐  ──────────────►  ┌──────────┐
  │  draft   │                   │  active   │
  │ (Agent   │  의사 기각         │           │
  │  제안)   │  ──────────┐      └─────┬─────┘
  └─────────┘             │            │ 모달 실행 완료
                          ▼            ▼
                   ┌──────────┐  ┌──────────────┐
                   │ revoked  │  │  completed   │
                   └──────────┘  └──────┬───────┘
                                        │
                                  Agent 재호출 (다음 모달 판단)
```

- `draft` + `intent: proposal` → AI가 제안한 상태
- 의사가 승인 → `active` + `intent: order` → 실제 모달 실행
- 의사가 기각 → `revoked` → Agent가 대안 제안
- 모달 완료 → `completed` → Agent가 다음 판단

## "AI 결과가 확실하지 않은데 FHIR에 넣어도 되나요?"

됩니다. FHIR 표준에서 이걸 구분해놨습니다:

- AI 모델 출력 → `status: "preliminary"` (확정 아님, 임시 결과)
- 의사가 확인 후 → `status: "final"` (확정)

실제 병원 EMR에서도 검사 결과가 처음 나오면 preliminary로 들어가고,
판독의가 확인하면 final로 바뀝니다. 같은 패턴입니다.

## 모달 아웃풋 → FHIR 변환

ECG 서비스와 CXR 서비스는 각자 다른 아웃풋 포맷을 가집니다.
백엔드에서 이걸 통일된 FHIR Observation으로 변환합니다.

```
ECG 서비스 아웃풋 (자체 포맷) ─┐
                                ├→ 변환 함수 → FHIR Observation → HAPI FHIR 서버
CXR 서비스 아웃풋 (자체 포맷) ─┘
```

변환 함수 위치: `app/fhir/resources.py`
- `convert_ecg_to_observations()` — ECG PredictResponse → FHIR Observation 리스트
- `convert_cxr_to_observations()` — CXR PredictResponse → FHIR Observation 리스트

## central 오케스트레이터와의 관계

central의 `FusionDecisionEngine`이 "다음에 어떤 모달을 실행할지" 판단하는 두뇌입니다.
백엔드는 이 엔진을 직접 호출합니다 (AWS Step Functions를 거치지 않음).

```
트리아지 제출
  → FHIR에 저장
  → FHIR 데이터를 central 포맷으로 변환 (adapter.py)
  → FusionDecisionEngine.decide() 호출
  → "CXR, ECG 찍자" 판단
  → ServiceRequest 2개 생성 (draft)
  → 프론트에 WebSocket 푸시

의사 승인 후 모달 실행
  → 결과를 FHIR Observation으로 변환 후 저장
  → 다시 FusionDecisionEngine.decide() 호출
  → "LAB도 필요하다" 또는 "리포트 생성하자" 판단
  → 반복 (최대 3회)
```

포맷 변환 어댑터 위치: `app/fhir/adapter.py`
- `fhir_to_central_patient()` — FHIR 리소스 → central 포맷
- `fhir_observations_to_central_results()` — FHIR Observation → central 모달 결과 포맷

## 파일 구조

```
backend/
├── app/
│   ├── main.py              # FastAPI 진입점 + 라우터 등록
│   ├── config.py            # 환경변수 (FHIR_BASE_URL 등)
│   │
│   ├── fhir/                # ★ FHIR 핵심 모듈
│   │   ├── client.py        # HAPI FHIR httpx 래퍼 (create, read, patch, transaction, search)
│   │   ├── resources.py     # 빌더 함수 7종 + ECG/CXR → Observation 변환
│   │   ├── codes.py         # LOINC/ICD-10/SNOMED 코드 사전
│   │   ├── code_mapper.py   # 한글 텍스트 → ICD-10 매핑 (정적 사전 + Claude 폴백)
│   │   ├── state_machine.py # ServiceRequest/DiagnosticReport 상태 전이 검증
│   │   └── adapter.py       # FHIR ↔ central 포맷 변환 어댑터
│   │
│   ├── api/                 # REST API 엔드포인트
│   │   ├── triage.py        # POST /triage/submit (트리아지 제출)
│   │   ├── orders.py        # POST /orders/{id}/approve|reject (의사 승인/기각)
│   │   ├── encounters.py    # GET /encounters/* (조회)
│   │   ├── reports.py       # POST /reports/{id}/sign (리포트 서명)
│   │   └── ws.py            # WebSocket /ws/encounter/{id} (실시간 푸시)
│   │
│   ├── agent/               # Bedrock Agent
│   │   ├── bedrock_client.py # Claude 호출 래퍼
│   │   └── tools.py         # propose_order, get_encounter_context
│   │
│   └── clients/             # 외부 서비스 호출
│       └── sagemaker_invoke.py
│
├── tests/
│   └── fixtures/            # 테스트용 정답지 JSON
├── Dockerfile
├── requirements.txt
└── README.md                # 이 파일
```

## API 엔드포인트 요약

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

## 실행 방법

```bash
# 1. HAPI FHIR 서버 띄우기
cd ../infra
docker compose up -d

# 2. 백엔드 실행
cd ../backend
pip install -r requirements.txt
FHIR_BASE_URL=http://localhost:8080/fhir uvicorn app.main:app --reload --port 8000

# 3. API 문서 확인
open http://localhost:8000/docs
```

## 코드 시스템 사전 (codes.py)

백엔드는 의료 코드 표준을 사용합니다:

- **LOINC** — 검사/측정 항목 코드 (Heart rate = 8867-4, Troponin T = 6598-7 등)
- **ICD-10-CM** — 진단/증상 코드 (흉통 = R07.9, 고혈압 = I10 등)
- **SNOMED CT** — 확정 진단 코드 (STEMI = 401303003, Pneumonia = 233604007 등)

한글 주호소가 들어오면 정적 사전에서 ICD-10 코드를 찾고,
없으면 Claude Haiku에게 물어봐서 매핑합니다 (`code_mapper.py`).
