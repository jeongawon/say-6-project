"""
Step 6: RAG 오케스트레이터
- 사용자 입력 → Titan 임베딩 → ChromaDB 검색 → Claude 3 답변 생성
- 검색 시 discharge + radiology 다양성 보장
- 유사도 낮으면 fallback 응답
"""

import json
import time

import boto3
import chromadb
from botocore.exceptions import ClientError, NoCredentialsError

# ──────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────
DB_DIR = "./local_rag_db"
COLLECTION_NAME = "medical_rag_collection"
EMBED_MODEL_ID = "amazon.titan-embed-text-v2:0"
EMBED_DIMENSIONS = 512
LLM_MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"
LLM_MAX_TOKENS = 2048

TOP_K_FETCH = 20          # 검색 시 넉넉하게 가져올 수
TOP_K_FINAL = 3           # 최종 컨텍스트에 넣을 수
MIN_SIMILARITY = 0.15     # 이 이하면 fallback (cosine similarity 기준)

SYSTEM_PROMPT = (
    "당신은 전문적이고 친절한 AI 의료 보조입니다. "
    "제공된 [과거 유사 환자 사례]와 [새로운 환자 검사 결과]를 바탕으로 "
    "정확히 5가지 항목으로 번호를 매겨 종합 소견을 작성해야 합니다. "
    "도입부는 '새로운 환자의 검사 결과와 과거 유사 환자 사례를 종합하여 "
    "다음과 같은 소견을 제시드립니다:'로 시작하고, "
    "의학 약어가 등장하면 반드시 '약어 (풀네임: 한글 설명)' 형식으로 기재하십시오."
)

FALLBACK_RESPONSE = (
    "유사한 과거 환자 사례를 찾지 못했습니다. 추가 검사가 필요합니다."
)


# ──────────────────────────────────────────────
# 1단계: Retrieval
# ──────────────────────────────────────────────
class Retriever:
    """ChromaDB 검색 + 다양성 필터링"""

    def __init__(self):
        self.bedrock = boto3.client("bedrock-runtime")
        client = chromadb.PersistentClient(path=DB_DIR)
        self.collection = client.get_collection(name=COLLECTION_NAME)

    def _embed(self, text: str) -> list[float]:
        body = json.dumps({
            "inputText": text[:8000],
            "dimensions": EMBED_DIMENSIONS,
        })
        for attempt in range(1, 4):
            try:
                resp = self.bedrock.invoke_model(
                    modelId=EMBED_MODEL_ID,
                    contentType="application/json",
                    accept="application/json",
                    body=body,
                )
                return json.loads(resp["body"].read())["embedding"]
            except ClientError:
                time.sleep(2 ** attempt)
        raise RuntimeError("임베딩 API 호출 실패")

    def search(self, query: str) -> dict:
        """
        검색 후 다양성 필터링을 적용하여 최종 Top-3를 반환한다.
        반환: {"results": [...], "fallback": bool}
        """
        query_vec = self._embed(query)

        raw = self.collection.query(
            query_embeddings=[query_vec],
            n_results=TOP_K_FETCH,
            include=["documents", "metadatas", "distances"],
        )

        # cosine distance → similarity 변환
        candidates = []
        for i in range(len(raw["ids"][0])):
            similarity = 1 - raw["distances"][0][i]
            candidates.append({
                "id": raw["ids"][0][i],
                "document": raw["documents"][0][i],
                "metadata": raw["metadatas"][0][i],
                "similarity": round(similarity, 4),
            })

        # fallback 체크: 최고 유사도가 기준 미달
        if not candidates or candidates[0]["similarity"] < MIN_SIMILARITY:
            return {"results": [], "fallback": True}

        # 다양성 필터링: discharge 최소 1 + radiology 최소 1
        selected = self._diversity_filter(candidates)

        return {"results": selected, "fallback": False}

    def _diversity_filter(self, candidates: list[dict]) -> list[dict]:
        """discharge와 radiology를 각각 최소 1건 포함하여 Top-3 선정"""
        discharge = [c for c in candidates if c["metadata"].get("chunk_type") == "discharge_summary"]
        radiology = [c for c in candidates if c["metadata"].get("chunk_type") == "radiology"]

        selected = []

        # 각 타입에서 최고 유사도 1건씩 확보
        if discharge:
            selected.append(discharge[0])
        if radiology:
            selected.append(radiology[0])

        # 나머지 슬롯을 유사도 순으로 채움
        selected_ids = {s["id"] for s in selected}
        for c in candidates:
            if len(selected) >= TOP_K_FINAL:
                break
            if c["id"] not in selected_ids:
                selected.append(c)

        # 유사도 순 정렬
        selected.sort(key=lambda x: x["similarity"], reverse=True)
        return selected[:TOP_K_FINAL]


# ──────────────────────────────────────────────
# 2단계: Augmented (프롬프트 조립)
# ──────────────────────────────────────────────
def build_user_prompt(query: str, results: list[dict]) -> str:
    """검색 결과 + 사용자 입력을 하나의 프롬프트로 조립"""
    context_parts = []
    for i, r in enumerate(results, 1):
        meta = r["metadata"]
        chunk_type = meta.get("chunk_type", "unknown")
        hadm_id = meta.get("hadm_id", "?")
        sim = r["similarity"]
        doc = r["document"]

        context_parts.append(
            f"[사례 {i}] (유형: {chunk_type}, 입원번호: {hadm_id}, 유사도: {sim})\n{doc}"
        )

    context_block = "\n\n".join(context_parts)

    return (
        f"[과거 유사 환자 사례]\n{context_block}\n\n"
        f"[새로운 환자 검사 결과]\n{query}\n\n"
        f"위 정보를 바탕으로 종합 소견을 5가지 항목으로 작성해 주십시오."
    )


# ──────────────────────────────────────────────
# 3단계: Generation (Claude 3 Messages API)
# ──────────────────────────────────────────────
class Generator:
    """Claude 3 LLM 호출"""

    def __init__(self):
        self.bedrock = boto3.client("bedrock-runtime")

    def generate(self, user_prompt: str) -> str:
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": LLM_MAX_TOKENS,
            "system": SYSTEM_PROMPT,
            "messages": [
                {"role": "user", "content": user_prompt},
            ],
        })

        try:
            resp = self.bedrock.invoke_model(
                modelId=LLM_MODEL_ID,
                contentType="application/json",
                accept="application/json",
                body=body,
            )
            result = json.loads(resp["body"].read())
            return result["content"][0]["text"]

        except NoCredentialsError:
            return "[에러] AWS 자격 증명을 찾을 수 없습니다. aws configure를 확인하세요."
        except ClientError as e:
            return f"[에러] Claude API 호출 실패: {e.response['Error']['Code']}"


# ──────────────────────────────────────────────
# RAG 오케스트레이터
# ──────────────────────────────────────────────
def rag_query(query: str) -> str:
    """
    전체 RAG 파이프라인 실행:
    사용자 입력 → 검색 → 프롬프트 조립 → LLM 답변 생성
    """
    # 1. Retrieval
    retriever = Retriever()
    search_result = retriever.search(query)

    if search_result["fallback"]:
        return FALLBACK_RESPONSE

    results = search_result["results"]

    # 검색 결과 요약 출력
    print("-" * 50)
    print("[검색 결과]")
    for i, r in enumerate(results, 1):
        meta = r["metadata"]
        print(f"  [{i}] sim={r['similarity']:.4f} | "
              f"type={meta.get('chunk_type','?')} | "
              f"hadm={meta.get('hadm_id','?')}")
    print("-" * 50)

    # 2. Augmented
    user_prompt = build_user_prompt(query, results)

    # 3. Generation
    generator = Generator()
    answer = generator.generate(user_prompt)

    return answer


# ──────────────────────────────────────────────
# 4단계: 테스트 메인
# ──────────────────────────────────────────────
if __name__ == "__main__":
    test_query = (
        "CXR: Consolidation in the right lower lobe. "
        "Blood: WBC 18,500. "
        "ECG: Sinus Tachycardia 110 bpm."
    )

    print("=" * 60)
    print("  Step 6: RAG 오케스트레이터 테스트")
    print("=" * 60)
    print(f"\n[입력] {test_query}\n")

    try:
        answer = rag_query(test_query)
        print("\n[AI 소견]")
        print(answer)
    except NoCredentialsError:
        print("[에러] AWS 자격 증명을 찾을 수 없습니다.")
    except Exception as e:
        print(f"[에러] {e}")

    print("\n" + "=" * 60)
