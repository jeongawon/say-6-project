# RAG FastEmbed Migration Design Document

> **Summary**: rag-svc sentence-transformers → fastembed 교체 (Option A: Minimal)
>
> **Project**: DR-AI v3
> **Date**: 2026-03-30
> **Planning Doc**: [rag-fastembed-migration.plan.md](../../01-plan/features/rag-fastembed-migration.plan.md)

---

## Context Anchor

| Key | Value |
|-----|-------|
| **WHY** | rag-svc 8.84GB — PyTorch 원인, 쿼리 임베딩 한 곳만 사용 |
| **SUCCESS** | Docker 이미지 ≤ 1.5GB, /search 동일 결과, FAISS 재빌드 불필요 |
| **SCOPE** | rag_service.py + config.py + requirements.txt + Dockerfile + embedding-model 삭제 |

---

## 1. 수정 상세

### 1.1 requirements.txt

```diff
- sentence-transformers==3.3.1
+ fastembed
```

### 1.2 config.py

```diff
- embedder_model: str = "/models/embedding-model/bge-small-en-v1.5"
+ embedder_model: str = "BAAI/bge-small-en-v1.5"
```

### 1.3 rag_service.py

**_load_embedder():**
```diff
- from sentence_transformers import SentenceTransformer
+ from fastembed import TextEmbedding

- self.embedder: SentenceTransformer | None = None
+ self.embedder: TextEmbedding | None = None

  def _load_embedder(self) -> None:
-     self.embedder = SentenceTransformer(settings.embedder_model)
+     self.embedder = TextEmbedding(model_name=settings.embedder_model)
```

**_embed_query():**
```diff
  def _embed_query(self, text: str) -> np.ndarray:
-     embedding = self.embedder.encode(text, normalize_embeddings=True)
-     return np.array(embedding, dtype=np.float32)
+     embeddings = list(self.embedder.embed([text]))
+     return np.array(embeddings[0], dtype=np.float32)
```

### 1.4 Dockerfile

```diff
  RUN pip install --no-cache-dir -r requirements.txt
+
+ # FastEmbed 모델 프리캐시 (런타임 인터넷 불필요)
+ RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5')"
```

### 1.5 embedding-model 폴더 삭제

```bash
rm -rf v3/models/rag-svc/embedding-model/
```

---

## 2. 변경하지 않는 것

- main.py — RAGService 인터페이스 동일
- query_builder.py — 변경 없음
- FAISS 인덱스 파일 — 호환 (재빌드 불필요)
- K8s manifest — 변경 없음
- 다른 서비스 — 변경 없음

---

## 3. Implementation Order

1. [ ] requirements.txt 수정
2. [ ] config.py embedder_model 변경
3. [ ] rag_service.py 임베딩 교체
4. [ ] main.py docstring 업데이트
5. [ ] Dockerfile 프리캐시 추가
6. [ ] embedding-model 폴더 삭제
7. [ ] 로컬 검증

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 0.1 | 2026-03-30 | Option A Minimal |
