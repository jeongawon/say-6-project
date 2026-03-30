# RAG FastEmbed Migration Planning Document

> **Summary**: rag-svc 임베딩 엔진을 sentence-transformers → FastEmbed로 교체하여 Docker 이미지 8.84GB → ~1.2GB 축소
>
> **Project**: DR-AI v3
> **Version**: v3
> **Author**: 프로젝트 6팀
> **Date**: 2026-03-30
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | rag-svc Docker 이미지가 8.84GB. 원인은 sentence-transformers → PyTorch(~1.8GB) 자동 설치. 쿼리 임베딩 하나 때문에 딥러닝 프레임워크 전체가 딸려옴 |
| **Solution** | sentence-transformers를 fastembed(Qdrant 팀, ONNX Runtime 기반)로 교체. PyTorch 의존 완전 제거. 동일 모델(bge-small-en-v1.5, 384차원)이라 기존 FAISS 인덱스 재빌드 불필요 |
| **Function/UX Effect** | 이미지 크기 8.84GB → ~1.2GB (86% 감소), Pod 시작 시간 단축, 검색 기능 동일 유지 |
| **Core Value** | 인프라 비용 절감 + 빌드/배포 속도 향상. 기능 변경 없이 순수 최적화 |

---

## Context Anchor

| Key | Value |
|-----|-------|
| **WHY** | rag-svc 8.84GB 이미지 — PyTorch가 원인, 실제 사용은 쿼리 임베딩 한 곳뿐 |
| **WHO** | 개발팀 (빌드/배포 속도), 인프라 (EKS 노드 디스크/메모리) |
| **RISK** | FastEmbed 양자화 ONNX 모델과 기존 FAISS 인덱스 호환성 검증 필요 |
| **SUCCESS** | Docker 이미지 ≤ 1.5GB, /search 동일 쿼리 → 유사한 결과, FAISS 인덱스 재빌드 불필요 |
| **SCOPE** | rag_service.py + config.py + requirements.txt + Dockerfile + embedding-model 폴더 삭제 |

---

## 1. Overview

### 1.1 Purpose

rag-svc의 임베딩 엔진을 `sentence-transformers`(PyTorch 기반)에서 `fastembed`(ONNX Runtime 기반)로 교체하여 PyTorch 의존성을 완전 제거하고 Docker 이미지를 ~1.2GB로 축소한다.

### 1.2 Background

- **현재**: `sentence-transformers==3.3.1` → `torch`(~1.8GB), `transformers`, `huggingface-hub` 자동 설치
- **실제 사용**: `SentenceTransformer.encode(query)` — 쿼리 텍스트를 384차원 벡터로 변환하는 것 뿐
- **FastEmbed**: Qdrant 팀 경량 임베딩 라이브러리, ONNX Runtime 기반, PyTorch 불필요
- **호환성**: 동일 모델(BAAI/bge-small-en-v1.5), 동일 차원(384), 동일 벡터 공간 → FAISS 인덱스 재빌드 불필요

### 1.3 Related Documents

- 마이그레이션 프롬프트: `RAG_SVC_FASTEMBED_MIGRATION_PROMPT.md`
- rag-svc 현재 코드: `v3/services/rag-svc/`

---

## 2. Scope

### 2.1 In Scope

- [ ] `requirements.txt` — `sentence-transformers` 제거, `fastembed` 추가
- [ ] `rag_service.py` — `SentenceTransformer` → `TextEmbedding` 교체
- [ ] `config.py` — `embedder_model` 경로 → 모델명으로 변경
- [ ] `Dockerfile` — PyTorch 제거 효과 + FastEmbed 모델 프리캐시
- [ ] `v3/models/rag-svc/embedding-model/` — 폴더 전체 삭제 (sentence-transformers 포맷)

### 2.2 Out of Scope

- FAISS 인덱스 파일 (faiss_index.bin, metadata.jsonl, config.json) — 변경 없음
- query_builder.py — 변경 없음
- main.py — 인터페이스 동일하면 변경 없음
- K8s manifest — 변경 없음
- 다른 서비스 (chest/ecg/blood/orchestrator/report) — 변경 없음

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | sentence-transformers → fastembed 교체 | High | Pending |
| FR-02 | 기존 FAISS 인덱스와 호환 (재빌드 불필요) | High | Pending |
| FR-03 | /search 엔드포인트 동일 입출력 유지 | High | Pending |
| FR-04 | Docker 이미지 내 FastEmbed 모델 프리캐시 (런타임 인터넷 불필요) | Medium | Pending |
| FR-05 | embedding-model 폴더 삭제 | Low | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| Size | Docker 이미지 ≤ 1.5GB | `docker images` |
| Performance | 임베딩 속도 ≤ 100ms/쿼리 | metadata 또는 로그 |
| Compatibility | 동일 쿼리 → 유사한 검색 결과 (Top-5 중 3개 이상 동일) | Before/After 비교 |
| Reliability | /healthz, /readyz 정상 | curl 테스트 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] `docker build` 성공
- [ ] `docker images` 크기 ≤ 1.5GB (기존 8.84GB)
- [ ] /healthz, /readyz 200 정상
- [ ] /search 엔드포인트 정상 반환
- [ ] 기존 FAISS 인덱스 호환 확인 (동일 쿼리 → 유사 결과)
- [ ] embedding-model 폴더 삭제 완료
- [ ] PyTorch 의존 완전 제거 (`pip list | grep torch` → 없음)

### 4.2 Quality Criteria

- [ ] 다른 서비스 영향 없음
- [ ] main.py 변경 최소화 (인터페이스 동일)

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| FastEmbed 양자화 ONNX 벡터가 기존 FAISS 인덱스와 미호환 | High | Low | 동일 모델(bge-small-en-v1.5) + 동일 차원(384). Before/After 벡터 비교 테스트 |
| FastEmbed 모델 자동 다운로드 실패 (Docker 빌드 시) | Medium | Low | Dockerfile에서 프리캐시. 실패 시 수동 다운로드 |
| fastembed API 차이로 인한 버그 | Medium | Medium | `embed()` 제너레이터 → `list()` 감싸기. 정규화 옵션 확인 |
| faiss-cpu와 fastembed의 onnxruntime 버전 충돌 | Medium | Low | requirements.txt에서 버전 핀 확인 |

---

## 6. Impact Analysis

### 6.1 Changed Resources

| Resource | Type | Change |
|----------|------|--------|
| `rag_service.py` | Code | SentenceTransformer → TextEmbedding |
| `config.py` | Config | embedder_model 경로 → 모델명 |
| `requirements.txt` | Deps | -sentence-transformers, +fastembed |
| `Dockerfile` | Build | 프리캐시 추가, PyTorch 제거 효과 |
| `models/rag-svc/embedding-model/` | 삭제 | ~430MB 폴더 전체 삭제 |

### 6.2 Current Consumers

| Resource | Consumer | Impact |
|----------|----------|--------|
| rag-svc /search | chest-svc, ecg-svc (report 생성 시) | ✅ None (API 동일) |
| rag-svc /search | report-svc | ✅ None (API 동일) |
| RAGService.search() | main.py | ✅ None (메서드 시그니처 동일) |
| RAGService.format_for_report() | main.py | ✅ None (변경 없음) |

---

## 7. Architecture Considerations

### 7.1 핵심 변경점

```
Before:
  SentenceTransformer("...bge-small-en-v1.5")
    → model.encode(query, normalize_embeddings=True)
    → numpy array (384,)

After:
  TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    → list(model.embed([query]))[0]
    → numpy array (384,)
```

### 7.2 주의사항

| 항목 | SentenceTransformer | FastEmbed |
|------|-------------------|-----------|
| 반환 타입 | numpy array 직접 | **제너레이터** → list() 필요 |
| 정규화 | `normalize_embeddings=True` 옵션 | 기본 정규화 (확인 필요) |
| 모델 저장 | 로컬 경로 / HuggingFace | **자동 캐시** (~/.cache/fastembed/) |
| 모델 포맷 | safetensors (PyTorch) | **양자화 ONNX** |

---

## 8. Implementation Phases

| Phase | 작업 | 수정 파일 | 예상 시간 |
|-------|------|----------|----------|
| 1 | requirements.txt 수정 | requirements.txt | 2분 |
| 2 | config.py embedder_model 변경 | config.py | 3분 |
| 3 | rag_service.py 임베딩 교체 | rag_service.py | 10분 |
| 4 | Dockerfile 프리캐시 추가 | Dockerfile | 5분 |
| 5 | embedding-model 폴더 삭제 | 파일시스템 | 2분 |
| 6 | 로컬 검증 (uvicorn + /search) | — | 10분 |
| 7 | Docker 빌드 + 이미지 크기 확인 | — | 10분 |
| **합계** | | | **~42분** |

---

## 9. Next Steps

1. [ ] Design 문서 작성 (또는 바로 구현 — 변경 범위가 작음)
2. [ ] Implementation
3. [ ] Before/After 벡터 비교 테스트
4. [ ] Docker 빌드 + 이미지 크기 확인

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-30 | 초안 — RAG_SVC_FASTEMBED_MIGRATION_PROMPT.md 기반 | 프로젝트 6팀 |
