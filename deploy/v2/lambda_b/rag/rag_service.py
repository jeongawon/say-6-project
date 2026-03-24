"""
Layer 5 RAG 검색 서비스.
IMPRESSION으로 검색하고, FINDINGS + INDICATION까지 포함하여 반환.

Lambda cold start 시 S3에서 FAISS 인덱스 + 메타데이터를 /tmp에 다운로드.
FastEmbed (bge-small-en-v1.5)로 쿼리 임베딩 — PyTorch 불필요.
"""
import boto3
import faiss
import numpy as np
import json
import os

from fastembed import TextEmbedding
from rag.query_builder import build_query


class RAGService:
    def __init__(self, config):
        self.s3 = boto3.client("s3", region_name=config.REGION)
        self.config = config
        self.index = None
        self.metadata = None
        self.embedder = TextEmbedding(model_name=config.EMBEDDING_MODEL)
        self._load_index()

    def _load_index(self):
        """Lambda 초기화 시 S3에서 FAISS 인덱스 + 메타데이터 로드."""
        index_path = "/tmp/faiss_index.bin"
        metadata_path = "/tmp/metadata.jsonl"

        if not os.path.exists(index_path):
            print("S3에서 FAISS 인덱스 다운로드 중...")
            self.s3.download_file(
                self.config.S3_BUCKET, self.config.FAISS_INDEX_KEY, index_path
            )

        if not os.path.exists(metadata_path):
            print("S3에서 메타데이터 다운로드 중...")
            self.s3.download_file(
                self.config.S3_BUCKET, self.config.METADATA_KEY, metadata_path
            )

        self.index = faiss.read_index(index_path)

        self.metadata = []
        with open(metadata_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    self.metadata.append(json.loads(line))

        print(f"인덱스 로드 완료: {self.index.ntotal:,}개 벡터, {len(self.metadata):,}건 메타데이터")

    def search(self, clinical_logic_result: dict, top_k: int = 3) -> dict:
        """Layer 3 결과 → 쿼리 생성 → FAISS 검색 → Top-K 반환."""
        query_text = build_query(clinical_logic_result)
        query_vector = self._embed_query(query_text)

        distances, indices = self.index.search(
            query_vector.reshape(1, -1), top_k
        )

        results = []
        for rank, (dist, idx) in enumerate(zip(distances[0], indices[0])):
            if idx == -1 or idx >= len(self.metadata):
                continue
            meta = self.metadata[idx]

            result = {
                "rank": rank + 1,
                "similarity": round(float(dist), 4),
                "note_id": meta["note_id"],
                "subject_id": meta["subject_id"],
                "charttime": meta.get("charttime"),
                "impression": meta["impression"],
                "findings": meta.get("findings"),
                "indication": meta.get("indication"),
                "examination": meta.get("examination"),
                "comparison": meta.get("comparison"),
                "source": "MIMIC-IV Note (radiology.csv)",
            }
            results.append(result)

        return {
            "rag_evidence": results,
            "query_used": query_text,
            "total_results": len(results),
            "includes_findings": True,
            "includes_indication": True,
        }

    def _embed_query(self, text: str) -> np.ndarray:
        """FastEmbed로 쿼리 임베딩."""
        embeddings = list(self.embedder.embed([text]))
        return np.array(embeddings[0], dtype=np.float32)

    def format_for_layer6(self, rag_result: dict) -> str:
        """RAG 검색 결과를 Layer 6 Bedrock 프롬프트에 삽입할 텍스트로 포맷팅."""
        if not rag_result.get("rag_evidence"):
            return "[RAG 유사 케이스 없음]"

        lines = [
            "[RAG 유사 케이스 — 참고용]",
            "아래는 유사한 소견을 가진 과거 전문의 판독문입니다. "
            "표현 방식과 소견 구조를 참고하세요.\n",
        ]

        for ev in rag_result["rag_evidence"]:
            lines.append(f"[유사 케이스 {ev['rank']}] (유사도: {ev['similarity']:.2f})")
            if ev.get("indication"):
                lines.append(f"▶ INDICATION: {ev['indication']}")
            if ev.get("findings"):
                lines.append(f"▶ FINDINGS: {ev['findings']}")
            lines.append(f"▶ IMPRESSION: {ev['impression']}")
            lines.append("")

        return "\n".join(lines)
