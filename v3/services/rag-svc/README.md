# rag-svc - 공유 RAG 검색 서비스

> **담당:** 팀원E
> **역할:** 3개 모달(chest / ecg / blood)이 **공통으로 사용하는** FAISS 유사 케이스 검색 마이크로서비스

---

## 서비스 개요

`rag-svc`는 FAISS 벡터 인덱스와 SentenceTransformer(`bge-small-en-v1.5`) 임베딩을 활용하여,
모달별 소견 텍스트를 기반으로 **유사한 과거 전문의 판독문**을 검색합니다.

- 흉부 X선(chest), 심전도(ECG), 혈액검사(blood) 3개 모달에서 공통으로 호출
- `central-orchestrator`가 각 모달 분석 결과를 바탕으로 이 서비스를 호출
- 검색된 유사 케이스는 `report-svc`의 종합 소견서 프롬프트에 RAG 근거로 삽입

---

## 파일별 역할

| 파일 | 설명 |
|------|------|
| `main.py` | FastAPI 앱 진입점. Lifespan(startup/shutdown), 헬스체크, `/search` API 정의 |
| `config.py` | 환경변수 기반 설정 (pydantic-settings). 인덱스 경로, 임베더 모델, 포트 등 |
| `rag_service.py` | 핵심 검색 로직. FAISS 인덱스 로드, SentenceTransformer 임베딩, Top-K 검색 |
| `query_builder.py` | 모달별 쿼리 최적화. chest/ecg/blood 각각에 맞는 검색 쿼리 생성 |
| `Dockerfile` | Docker 이미지 빌드 설정 |
| `requirements.txt` | Python 의존성 목록 |

---

## 팀원이 수정해야 할 파일

### 1. `rag_service.py` — FAISS 인덱스 경로, 검색 로직 조정
- `_load_index()`: FAISS 인덱스 파일 경로 및 메타데이터 로딩 로직
- `search()`: 검색 결과 필터링, 반환 필드 커스텀
- `format_for_report()`: 검색 결과를 리포트용 텍스트로 변환하는 포맷

### 2. `query_builder.py` — 모달별 쿼리 템플릿 수정
- `_build_chest_query()`: 흉부 X선 검색 쿼리 템플릿
- `_build_ecg_query()`: ECG 검색 쿼리 템플릿
- `_build_blood_query()`: 혈액검사 검색 쿼리 템플릿
- `build_query_from_findings()`: v2 호환 findings dict → 검색 쿼리 변환

### 3. `config.py` — 환경변수
- `model_dir`: FAISS 인덱스 디렉토리 경로 (기본값: `/data/rag`)
- `embedder_model`: 임베딩 모델명 (기본값: `BAAI/bge-small-en-v1.5`)
- `embedding_dimension`: 임베딩 차원 (기본값: `384`)

---

## FAISS 인덱스 파일 위치

| 파일 | 경로 | 설명 |
|------|------|------|
| FAISS 인덱스 | `{MODEL_DIR}/faiss_index.bin` | FAISS IndexFlatIP 바이너리 파일 |
| 메타데이터 | `{MODEL_DIR}/metadata.jsonl` | 벡터별 메타데이터 (JSONL 형식) |

- `MODEL_DIR` 환경변수로 경로 지정 (기본값: `/data/rag`)
- K8s 배포 시 PVC 또는 initContainer를 통해 마운트
- 인덱스 파일이 없으면 빈 인덱스로 시작 (에러 없이 동작)

**메타데이터 JSONL 포맷 예시:**
```json
{"note_id": "12345", "subject_id": "67890", "charttime": "2024-01-01", "impression": "No acute findings.", "findings": "...", "indication": "...", "source": "MIMIC-IV Note (radiology.csv)"}
```

---

## 로컬 실행 방법

```bash
# 1. 의존성 설치
cd v3/services/rag-svc
pip install -r requirements.txt

# 2. 환경변수 설정 (선택)
export MODEL_DIR=./data          # FAISS 인덱스 디렉토리
export EMBEDDER_MODEL=BAAI/bge-small-en-v1.5
export PORT=8000

# 3. 서버 실행
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

> **참고:** `shared/schemas.py`가 필요하므로, `/app/shared` 경로에 심볼릭 링크를 걸거나
> `sys.path`를 로컬 환경에 맞게 수정해야 합니다.

---

## API 스펙

### `POST /search` — 유사 케이스 검색

**Request Body:**
```json
{
  "query": "Bilateral pleural effusion with cardiomegaly.",
  "modal": "chest",
  "top_k": 5
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `query` | string | O | 검색 쿼리 텍스트 (소견, 진단명 등) |
| `modal` | string | O | 모달 유형 (`chest`, `ecg`, `blood`) |
| `top_k` | int | X | 반환할 결과 수 (기본값: 5) |

**Response (200):**
```json
{
  "results": [
    {
      "rank": 1,
      "similarity": 0.9234,
      "note_id": "12345",
      "subject_id": "67890",
      "charttime": "2024-01-01",
      "impression": "Bilateral pleural effusions, cardiomegaly.",
      "findings": "...",
      "indication": "...",
      "examination": "...",
      "comparison": "...",
      "source": "MIMIC-IV Note (radiology.csv)"
    }
  ]
}
```

### `GET /healthz` — Liveness Probe
```json
{"status": "ok"}
```

### `GET /readyz` — Readiness Probe
```json
{"status": "ready", "index_size": 50000}
```
