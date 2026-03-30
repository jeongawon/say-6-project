# report-svc - 종합 소견서 생성 서비스

> **담당:** 팀원E
> **역할:** 3개 모달(chest / ecg / blood) 소견서를 합산하여 **Bedrock Claude**로 종합 진단 보고서 생성

---

## 서비스 개요

`report-svc`는 각 모달 분석 서비스(chest-svc, ecg-svc, blood-svc)의 개별 결과를
**AWS Bedrock Claude** 모델에 전달하여 **종합 진단 소견서**를 생성합니다.

- 3개 모달의 분석 결과 + 환자 정보를 입력으로 받음
- RAG 유사 케이스(rag-svc)를 참고 근거로 프롬프트에 삽입 가능
- 한국어/영어 이중 언어 지원
- JSON 구조화 출력 + 자연어 서술형 보고서 동시 생성
- 위험도 분류(ROUTINE / URGENT / CRITICAL) 자동 판정

---

## 파일별 역할

| 파일 | 설명 |
|------|------|
| `main.py` | FastAPI 앱 진입점. Lifespan(startup/shutdown), 헬스체크, `/generate` API 정의 |
| `config.py` | 환경변수 기반 설정 (pydantic-settings). Bedrock 리전, 모델 ID, 토큰 수 등 |
| `report_generator.py` | 핵심 생성 로직. 프롬프트 조립, Bedrock 호출, 응답 파싱, 보고서 조립 |
| `prompt_templates.py` | 시스템/유저 프롬프트 템플릿, RAG 섹션 템플릿 (가장 중요한 커스텀 포인트) |
| `Dockerfile` | Docker 이미지 빌드 설정 |
| `requirements.txt` | Python 의존성 목록 |

---

## 팀원이 수정해야 할 파일

### 1. `prompt_templates.py` — 종합 소견서 프롬프트 커스텀 (가장 중요!)
- `SYSTEM_PROMPT` / `SYSTEM_PROMPT_EN`: 시스템 프롬프트 (판독 원칙, 보고서 구조, 주의사항)
- `USER_PROMPT_TEMPLATE` / `USER_PROMPT_TEMPLATE_EN`: 유저 프롬프트 (JSON 응답 포맷 정의)
- `RAG_SECTION_TEMPLATE`: RAG 유사 케이스 삽입 템플릿
- `RAG_SECTION_PLACEHOLDER` / `RAG_SECTION_PLACEHOLDER_EN`: RAG 결과 없을 때 대체 텍스트
- **종합 소견서의 톤, 구조, 포함 항목을 모두 이 파일에서 조정**

### 2. `report_generator.py` — Bedrock 호출 로직 조정
- `_invoke_bedrock()`: Bedrock API 호출 파라미터 (anthropic_version, max_tokens 등)
- `_parse_response()`: Claude 응답에서 JSON 파싱 로직
- `_compose_report_text()` / `_compose_diagnosis_text()`: 최종 보고서 포맷팅
- `_format_modal_reports()`: 모달별 결과를 프롬프트용 텍스트로 변환

### 3. `config.py` — 모델 ID, 리전 변경
- `bedrock_region`: AWS 리전 (기본값: `ap-northeast-2`)
- `bedrock_model_id`: Bedrock 모델 ID (기본값: `global.anthropic.claude-sonnet-4-6`)
- `max_tokens`: 최대 출력 토큰 수 (기본값: `4096`)
- `temperature`: 생성 온도 (기본값: `0.2`, 재시도 시 `0.0`)

---

## 로컬 실행 방법

```bash
# 1. 의존성 설치
cd v3/services/report-svc
pip install -r requirements.txt

# 2. AWS 자격 증명 설정 (Bedrock 호출에 필요)
export AWS_ACCESS_KEY_ID=your_key
export AWS_SECRET_ACCESS_KEY=your_secret
export AWS_DEFAULT_REGION=ap-northeast-2

# 3. 환경변수 설정 (선택)
export BEDROCK_REGION=ap-northeast-2
export BEDROCK_MODEL_ID=global.anthropic.claude-sonnet-4-6
export MAX_TOKENS=4096
export PORT=8000

# 4. 서버 실행
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

> **참고:** `shared/schemas.py`가 필요하므로, `/app/shared` 경로에 심볼릭 링크를 걸거나
> `sys.path`를 로컬 환경에 맞게 수정해야 합니다.

---

## API 스펙

### `POST /generate` — 종합 소견서 생성

**Request Body:**
```json
{
  "patient_id": "P-12345",
  "patient_info": {
    "age": 65,
    "sex": "M",
    "chief_complaint": "흉통",
    "history": ["고혈압", "당뇨"]
  },
  "modal_reports": [
    {
      "modal": "chest",
      "report": "Cardiomegaly with bilateral pleural effusions.",
      "findings": [
        {"name": "Cardiomegaly", "detected": true, "confidence": 0.92, "detail": "CTR 0.58"}
      ],
      "summary": "심비대 및 양측 흉막삼출 소견"
    },
    {
      "modal": "ecg",
      "report": "Normal sinus rhythm.",
      "findings": [],
      "summary": "정상 동율동"
    }
  ]
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `patient_id` | string | O | 환자 ID |
| `patient_info` | object | O | 환자 정보 (age, sex, chief_complaint, history) |
| `modal_reports` | list | O | 각 모달의 분석 결과 리스트 |

**Response (200):**
```json
{
  "status": "success",
  "report": "종합 판독문 텍스트...\n--- 구조화 소견 ---\n...",
  "diagnosis": "종합 인상 및 감별 진단 텍스트"
}
```

### `GET /healthz` — Liveness Probe
```json
{"status": "ok"}
```

### `GET /readyz` — Readiness Probe
```json
{"status": "ready", "model_id": "global.anthropic.claude-sonnet-4-6"}
```
