"""
Layer 6 RAG Placeholder - 나중에 PubMedBERT + FAISS RAG로 교체
인터페이스를 미리 정의해놓아서, 나중에 연결만 하면 됨.
"""


class RAGPlaceholder:
    """RAG 미연결 상태 - 빈 결과 반환"""

    def search_similar_cases(self, clinical_logic_result: dict) -> list:
        """
        Clinical Logic 결과를 임베딩 -> FAISS 검색 -> 유사 판독문 Top-3 반환

        Args:
            clinical_logic_result: Layer 3 Clinical Logic 출력

        Returns:
            list of dict:
            [
                {
                    "case_id": "s12345678",
                    "similarity": 0.91,
                    "impression": "Cardiomegaly with bilateral pleural effusion...",
                    "source": "MIMIC-IV Note"
                },
                ...
            ]

        현재는 빈 리스트 반환 (RAG 미연결)
        """
        return []


class RAGService:
    """나중에 구현할 실제 RAG 서비스"""

    def __init__(self):
        # self.embedder = PubMedBERTEmbedder()
        # self.index = FAISSIndex.load("mimic_iv_notes_index")
        pass

    def search_similar_cases(self, clinical_logic_result: dict) -> list:
        # 1. Clinical Logic 결과를 텍스트로 변환
        # query = self._build_query(clinical_logic_result)
        #
        # 2. PubMedBERT로 임베딩
        # embedding = self.embedder.encode(query)
        #
        # 3. FAISS 검색
        # results = self.index.search(embedding, top_k=3)
        #
        # 4. 결과 반환
        # return results
        raise NotImplementedError("RAG 서비스 미구현")
