"""
FAISS 검색 서비스 — v2 rag_service.py에서 마이그레이션.
S3 의존성 제거 -> 로컬 파일 경로 사용 (K8s PVC / initContainer).
fastembed(bge-small-en-v1.5)로 쿼리 임베딩.

[핵심 흐름]
1. load()          → 서버 시작 시 FAISS 인덱스 + SentenceTransformer 로드
2. search()        → 쿼리 텍스트 → 임베딩 → FAISS 검색 → Top-K 결과 반환
3. format_for_report() → 검색 결과를 report-svc 프롬프트용 텍스트로 변환

[팀원E 수정 포인트]
- _load_index(): FAISS 인덱스 파일 경로 및 메타데이터 로딩 로직
- search(): 검색 결과 필터링, 반환 필드 커스텀
- format_for_report(): 검색 결과 → 리포트용 텍스트 변환 포맷
"""
import json
import logging
import os

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from config import settings
from query_builder import build_query

logger = logging.getLogger("rag-svc")


class RAGService:
    """FAISS 인덱스 + SentenceTransformer 기반 유사 케이스 검색."""

    def __init__(self):
        # FAISS 인덱스 객체 (faiss.IndexFlatIP — Inner Product 기반 유사도)
        self.index: faiss.Index | None = None
        # 벡터별 메타데이터 리스트 (note_id, impression 등)
        self.metadata: list[dict] = []
        # SentenceTransformer 임베딩 모델 인스턴스
        self.embedder: SentenceTransformer | None = None
        # 초기화 완료 플래그 — readyz 프로브에서 사용
        self._ready = False

    # ------------------------------------------------------------------
    # Lifecycle — 서버 시작/종료 시 호출
    # ------------------------------------------------------------------
    def load(self) -> None:
        """startup 시 호출 — FAISS 인덱스 + 임베더 로드."""
        self._load_index()     # FAISS 인덱스 + 메타데이터 파일 로드
        self._load_embedder()  # SentenceTransformer 모델 로드
        self._ready = True
        logger.info("RAGService 초기화 완료")

    @property
    def ready(self) -> bool:
        """서비스 준비 상태 반환 — readyz 프로브에서 체크."""
        return self._ready

    # ------------------------------------------------------------------
    # Index loading — FAISS 인덱스 및 메타데이터 로드
    # ------------------------------------------------------------------
    def _load_index(self) -> None:
        """로컬 파일 시스템에서 FAISS 인덱스 + 메타데이터 로드."""
        # 인덱스 파일 경로: {model_dir}/{index_filename}
        index_path = os.path.join(settings.model_dir, settings.index_filename)
        # 메타데이터 파일 경로: {model_dir}/{metadata_filename}
        metadata_path = os.path.join(settings.model_dir, settings.metadata_filename)

        # 인덱스 파일이 없으면 빈 인덱스로 시작 (에러 없이 동작)
        if not os.path.exists(index_path):
            logger.warning("FAISS 인덱스 파일 없음: %s — 빈 인덱스로 시작", index_path)
            # IndexFlatIP: Inner Product 기반 유사도 (코사인 유사도와 동일 — 정규화된 벡터 사용 시)
            self.index = faiss.IndexFlatIP(settings.embedding_dimension)
            self.metadata = []
            return

        # FAISS 인덱스 바이너리 파일 로드
        logger.info("FAISS 인덱스 로딩: %s", index_path)
        self.index = faiss.read_index(index_path)

        # 메타데이터 JSONL 파일 로드 (한 줄에 하나의 JSON 객체)
        if os.path.exists(metadata_path):
            self.metadata = []
            with open(metadata_path, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped:
                        self.metadata.append(json.loads(stripped))
            logger.info(
                "인덱스 로드 완료: %d개 벡터, %d건 메타데이터",
                self.index.ntotal,
                len(self.metadata),
            )
        else:
            logger.warning("메타데이터 파일 없음: %s", metadata_path)
            self.metadata = []

    def _load_embedder(self) -> None:
        """SentenceTransformer 임베더 로드."""
        logger.info("임베더 로딩: %s", settings.embedder_model)
        # HuggingFace 모델 다운로드 후 로드 (최초 실행 시 다운로드 발생)
        self.embedder = SentenceTransformer(settings.embedder_model)
        logger.info("임베더 로드 완료")

    # ------------------------------------------------------------------
    # Search — 핵심 검색 로직
    # ------------------------------------------------------------------
    def search(self, query: str, modal: str, top_k: int | None = None) -> dict:
        """
        쿼리 텍스트 -> 임베딩 -> FAISS 검색 -> Top-K 반환.

        Args:
            query: 검색 쿼리 텍스트 (소견, 진단명 등)
            modal: 모달 유형 (chest, ecg, blood)
            top_k: 반환할 결과 수 (None이면 config의 default_top_k 사용)

        Returns:
            {"results": [...], "query_used": str, "total_results": int}
        """
        if top_k is None:
            top_k = settings.default_top_k

        # 1단계: 모달별 쿼리 최적화 (query_builder에서 모달에 맞게 변환)
        query_text = build_query(query, modal)

        # 2단계: 쿼리 텍스트를 벡터로 임베딩
        query_vector = self._embed_query(query_text)

        # 3단계: FAISS 인덱스에서 유사 벡터 검색
        if self.index is None or self.index.ntotal == 0:
            # 인덱스가 비어있으면 빈 결과 반환
            return {"results": [], "query_used": query_text, "total_results": 0}

        # FAISS search: (쿼리벡터, K) -> (유사도 점수 배열, 인덱스 배열)
        distances, indices = self.index.search(
            query_vector.reshape(1, -1), min(top_k, self.index.ntotal)
        )

        # 4단계: 검색 결과를 메타데이터와 매핑하여 응답 구성
        results = []
        for rank, (dist, idx) in enumerate(zip(distances[0], indices[0])):
            # idx == -1: FAISS에서 결과 없음, idx >= len(metadata): 메타데이터 범위 초과
            if idx == -1 or idx >= len(self.metadata):
                continue
            meta = self.metadata[idx]

            # 검색 결과 항목 구성 — MIMIC-IV Note 기반 필드
            result = {
                "rank": rank + 1,                              # 순위 (1부터 시작)
                "similarity": round(float(dist), 4),           # 유사도 점수 (Inner Product)
                "note_id": meta.get("note_id", ""),            # MIMIC-IV 노트 ID
                "subject_id": meta.get("subject_id", ""),      # MIMIC-IV 환자 ID
                "charttime": meta.get("charttime"),            # 판독 시간
                "impression": meta.get("impression", ""),      # 판독 인상 (핵심 소견)
                "findings": meta.get("findings"),              # 상세 소견
                "indication": meta.get("indication"),          # 촬영 사유
                "examination": meta.get("examination"),        # 검사 유형
                "comparison": meta.get("comparison"),          # 비교 판독 정보
                "source": meta.get("source", "MIMIC-IV Note (radiology.csv)"),  # 데이터 출처
            }
            results.append(result)

        return {
            "results": results,
            "query_used": query_text,
            "total_results": len(results),
        }

    def _embed_query(self, text: str) -> np.ndarray:
        """SentenceTransformer로 쿼리 텍스트를 벡터로 변환."""
        # normalize_embeddings=True: 코사인 유사도 = Inner Product (정규화된 벡터)
        embedding = self.embedder.encode(text, normalize_embeddings=True)
        return np.array(embedding, dtype=np.float32)

    # ------------------------------------------------------------------
    # Formatting helper — report-svc 등에서 사용 가능
    # ------------------------------------------------------------------
    def format_for_report(self, search_results: list[dict]) -> str:
        """
        검색 결과를 리포트 프롬프트용 텍스트로 포맷팅.

        report-svc의 시스템 프롬프트에 RAG 근거로 삽입할 때 사용.
        유사 케이스의 IMPRESSION, FINDINGS, INDICATION을 텍스트로 변환합니다.
        """
        if not search_results:
            return "[RAG 유사 케이스 없음]"

        lines = [
            "[RAG 유사 케이스 - 참고용]",
            "아래는 유사한 소견을 가진 과거 전문의 판독문입니다. "
            "표현 방식과 소견 구조를 참고하세요.\n",
        ]

        for ev in search_results:
            lines.append(
                f"[유사 케이스 {ev['rank']}] (유사도: {ev['similarity']:.2f})"
            )
            if ev.get("indication"):
                lines.append(f"  INDICATION: {ev['indication']}")
            if ev.get("findings"):
                lines.append(f"  FINDINGS: {ev['findings']}")
            lines.append(f"  IMPRESSION: {ev['impression']}")
            lines.append("")

        return "\n".join(lines)
