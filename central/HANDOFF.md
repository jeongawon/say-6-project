# 백엔드 인수인계 — 남은 작업 정리

## 현재 상태

`final/central/backend/` 에 FHIR 문서 기준 백엔드 스켈레톤이 **거의 완성**되어 있음.

### 완료된 것
- `app/fhir/codes.py` — LOINC/ICD-10/SNOMED 사전 테이블
- `app/fhir/client.py` — HAPI FHIR httpx 래퍼 (create, read, patch, transaction, search)
- `app/fhir/resources.py` — 빌더 함수 7종 + ECG/CXR → FHIR Observation 변환 함수
- `app/fhir/state_machine.py` — ServiceRequest/DiagnosticReport 상태 전이 검증
- `app/fhir/code_mapper.py` — 한글 → ICD-10 매핑 (정적 사전 + Claude Haiku 폴백)
- `app/api/triage.py` — POST /triage/submit (Patient + Encounter + Vitals + Condition 생성)
- `app/api/orders.py` — POST /orders/{id}/approve|reject (모달 실행 + Agent 재호출)
- `app/api/encounters.py` — GET /encounters/* (조회)
- `app/api/reports.py` — POST /reports/{id}/sign (DiagnosticReport 서명)
- `app/api/ws.py` — WebSocket /ws/encounter/{id}
- `app/agent/tools.py` — propose_order, get_encounter_context
- `app/agent/bedrock_client.py` — Bedrock Claude 호출 래퍼
- `app/clients/sagemaker_invoke.py` — SageMaker endpoint 호출
- `infra/docker-compose.yml` — HAPI FHIR + backend 컨테이너

---

## 남은 작업 3가지

### 1. DocumentReference 등록 흐름 (작음, 1~2시간)

CXR PNG, ECG WFDB 파일을 FHIR에 등록하는 흐름이 빠져 있음.

**할 일:**
- `orders.py`의 `_execute_modal_and_complete()`에서 모달 실행 전에 DocumentReference 생성
- `resources.py`에 이미 `build_diagnostic_report()`는 있지만, DocumentReference 빌더 호출하는 곳이 없음

**참고 — resources.py에 추가할 함수:**
```python
def build_document_reference(patient_id, encounter_id, content_type, url, loinc_code, display):
    return {
        "resourceType": "DocumentReference",
        "status": "current",
        "type": {"coding": [{"system": "http://loinc.org", "code": loinc_code, "display": display}]},
        "subject": {"reference": f"Patient/{patient_id}"},
        "context": {"encounter": [{"reference": f"Encounter/{encounter_id}"}]},
        "content": [{"attachment": {"contentType": content_type, "url": url}}],
    }
```

**호출 위치:** `orders.py` → `_execute_modal_and_complete()` 안에서 모달 호출 전에:
```python
docref = await fhir.create("DocumentReference", build_document_reference(...))
docref_id = docref["id"]
# 이후 convert_ecg_to_observations(..., docref_id=docref_id) 에 전달
```

---

### 2. central 오케스트레이터 ↔ backend 연결 (핵심, 3~4시간)

트리아지 제출 후 central의 FusionDecisionEngine이 초기 모달을 제안하고,
ServiceRequest(draft)를 자동 생성하는 연결 고리가 없음.

**할 일:**
- `app/api/triage.py`의 `submit_triage()` 끝에 오케스트레이터 호출 추가
- central의 `deploy/orchestrator/fusion_decision/decision_engine.py`를 import해서 사용

**흐름:**
```
POST /triage/submit
  → Patient, Encounter, Vitals, Condition 생성 (현재 완료)
  → FusionDecisionEngine(patient, [], [], iteration=1).decide()
  → 결과: CALL_NEXT_MODALITY + next_modalities: ["CXR", "ECG"]
  → 각 모달에 대해 propose_order() 호출 → ServiceRequest(draft) 생성
  → WebSocket으로 프론트에 "AI가 CXR, ECG를 권고합니다" 푸시
```

**파일 위치:**
- central 엔진: `final/central/deploy/orchestrator/fusion_decision/decision_engine.py`
- backend에서 import하려면 sys.path 추가하거나 패키지로 복사

---

### 3. 프론트엔드 페이지 구현 (UI, 4~6시간)

`final/central/frontend/` 에 React + Vite + Tailwind 스켈레톤만 있음.
`src/lib/api.ts`에 백엔드 호출 함수는 다 만들어져 있음.
`src/lib/types.ts`에 TriageSubmission 타입도 있음.

**필요한 페이지:**

1. **트리아지 폼 페이지** (`/triage`)
   - 환자 정보 (나이, 성별, 이름)
   - 바이탈 사인 (HR, SBP, DBP, SpO2, RR, Temp, GCS)
   - 주호소 (자유 텍스트 + ICD-10 드롭다운)
   - 과거력 (동적 추가)
   - 제출 → `submitTriage()` 호출

2. **의사 대시보드 페이지** (`/dashboard`)
   - 현재 Encounter의 ServiceRequest 목록 표시
   - 각 SR에 승인/기각 버튼
   - WebSocket으로 실시간 업데이트
   - 모달 결과(Observation) 표시

3. **결과/리포트 페이지** (`/report/:id`)
   - DiagnosticReport 내용 표시
   - 의사 서명 버튼 → `signReport()` 호출

**API 함수 (이미 구현됨):**
- `submitTriage(form)` — 트리아지 제출
- `approveOrder(srId)` — SR 승인
- `rejectOrder(srId)` — SR 기각
- `signReport(drId)` — 리포트 서명
- `connectEncounterWS(encounterId)` — WebSocket 연결

---

## 실행 방법

```bash
# 1. HAPI FHIR 서버 + 백엔드 띄우기
cd final/central/infra
docker compose up -d

# 2. 백엔드만 로컬 개발
cd final/central/backend
pip install -r requirements.txt
FHIR_BASE_URL=http://localhost:8080/fhir uvicorn app.main:app --reload

# 3. 프론트엔드
cd final/central/frontend
npm install
npm run dev
```

## 파일 구조 참고

```
final/central/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── fhir/        ← FHIR 핵심 (client, resources, codes, state_machine, code_mapper)
│   │   ├── api/         ← 엔드포인트 (triage, orders, encounters, reports, ws)
│   │   ├── agent/       ← Bedrock Agent (bedrock_client, tools)
│   │   └── clients/     ← 외부 호출 (sagemaker_invoke)
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── App.tsx
│       └── lib/          ← api.ts, types.ts (이미 구현)
├── infra/
│   └── docker-compose.yml
└── deploy/               ← 기존 central 오케스트레이터 (그대로)
```
