"""
Step 5: 로컬 테스트용 모듈화 임베딩 & ChromaDB 적재 스크립트
- 입력: data/step4_integrated_knowledge.jsonl
- 출력: ./local_rag_db (ChromaDB 영구 저장)
- 임베딩: AWS Bedrock amazon.titan-embed-text-v2:0 (512차원)
"""

import argparse
import json
import os
import time
from abc import ABC, abstractmethod

import boto3
import chromadb
from botocore.exceptions import ClientError
from tqdm import tqdm

# ──────────────────────────────────────────────
# 설정값
# ──────────────────────────────────────────────
INPUT_FILE = "data/step4_integrated_knowledge.jsonl"
DB_DIR = "./local_rag_db"
CHECKPOINT_FILE = os.path.join(DB_DIR, "checkpoint.json")
COLLECTION_NAME = "medical_rag_collection"
EMBED_MODEL_ID = "amazon.titan-embed-text-v2:0"
EMBED_DIMENSIONS = 512
MAX_TEXT_CHARS = 8000          # Titan v2 토큰 제한 방어용 문자 상한
BATCH_SIZE = 100               # ChromaDB 배치 업로드 단위
MAX_RETRIES = 6                # API 재시도 최대 횟수
BASE_BACKOFF = 1.0             # 지수 백오프 초기 대기(초)


# ──────────────────────────────────────────────
# 0단계: 체크포인트 시스템
# ──────────────────────────────────────────────
def load_checkpoint() -> set:
    """이미 처리 완료된 hadm_id 집합을 로드한다."""
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r") as f:
            data = json.load(f)
        print(f"[체크포인트] 기존 완료 건수: {len(data['done_hadm_ids'])}건 로드됨")
        return set(data["done_hadm_ids"])
    return set()


def save_checkpoint(done_ids: set):
    """처리 완료된 hadm_id 집합을 디스크에 저장한다."""
    os.makedirs(DB_DIR, exist_ok=True)
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump({"done_hadm_ids": sorted(done_ids)}, f)


# ──────────────────────────────────────────────
# 1단계: 데이터 평탄화 (Flattening)
# ──────────────────────────────────────────────
def extract_text_recursive(value) -> str:
    """
    ml_features 직렬화 규칙:
    - str → 그대로 반환
    - list → 쉼표로 연결 (빈 리스트 무시)
    - dict → 재귀적으로 값(Value)만 추출하여 공백으로 연결
    - 빈 문자열 무시
    """
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [extract_text_recursive(item) for item in value]
        return ", ".join(p for p in parts if p)
    if isinstance(value, dict):
        parts = [extract_text_recursive(v) for v in value.values()]
        return " ".join(p for p in parts if p)
    # 숫자 등 기타 타입
    return str(value).strip() if value is not None else ""


def flatten_record(record: dict) -> list[dict]:
    """
    한 건의 레코드를 퇴원 요약지 + 영상의학 조각 리스트로 평탄화한다.
    반환: [{"id": ..., "text": ..., "metadata": {...}}, ...]
    """
    join = record["join_keys"]
    subject_id = join["subject_id"]
    hadm_id = join["hadm_id"]
    chunks = []

    # (1) 퇴원 요약지 조각
    ml = record.get("ml_features", {})
    text_parts = [extract_text_recursive(v) for v in ml.values()]
    discharge_text = " ".join(p for p in text_parts if p)

    if discharge_text:
        chunks.append({
            "id": f"{hadm_id}_discharge",
            "text": discharge_text,
            "metadata": {
                "chunk_type": "discharge_summary",
                "subject_id": subject_id,
                "hadm_id": hadm_id,
            },
        })

    # (2) 영상의학 조각
    rad_history = record.get("radiology_history", [])
    if not rad_history:
        print(f"  [INFO] hadm_id={hadm_id}: radiology_history 비어있음 → 영상의학 조각 스킵")
    else:
        for idx, rad in enumerate(rad_history):
            emb_text = rad.get("embedding_text", "")
            if not emb_text:
                continue
            meta = rad.get("metadata", {})
            chunks.append({
                "id": f"{hadm_id}_rad_{idx}",
                "text": emb_text,
                "metadata": {
                    "chunk_type": "radiology",
                    "subject_id": subject_id,
                    "hadm_id": hadm_id,
                    **{k: str(v) for k, v in meta.items()},
                },
            })

    return chunks


# ──────────────────────────────────────────────
# 2단계: 모듈형 DB 아키텍처
# ──────────────────────────────────────────────
class BaseVectorDB(ABC):
    """벡터 DB 추상 인터페이스 — 향후 클라우드 전환 시 이 클래스를 상속하여 교체"""

    @abstractmethod
    def upsert_batch(self, ids: list[str], embeddings: list[list[float]],
                     documents: list[str], metadatas: list[dict]):
        ...

    @abstractmethod
    def count(self) -> int:
        ...


class ChromaDBConnector(BaseVectorDB):
    """로컬 ChromaDB 영구 저장 커넥터"""

    def __init__(self, persist_dir: str, collection_name: str):
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert_batch(self, ids, embeddings, documents, metadatas):
        self.collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

    def count(self) -> int:
        return self.collection.count()


# ──────────────────────────────────────────────
# 추후 클라우드 전환 시 여기에 OpenSearchConnector를
# 구현하여 갈아끼우면 됩니다.
# ──────────────────────────────────────────────
# class OpenSearchConnector(BaseVectorDB):
#     def __init__(self, host, index_name, ...):
#         ...
#     def upsert_batch(self, ids, embeddings, documents, metadatas):
#         ...
#     def count(self) -> int:
#         ...
# ──────────────────────────────────────────────


# ──────────────────────────────────────────────
# 3단계: 임베딩 생성 (Titan v2, 512차원)
# ──────────────────────────────────────────────
class TitanEmbedder:
    """AWS Bedrock Titan Embed v2 래퍼 — 지수 백오프 & truncation 내장"""

    def __init__(self):
        self.client = boto3.client("bedrock-runtime")

    def embed(self, text: str) -> list[float]:
        # 토큰 초과 방어: 8,000자 truncation
        if len(text) > MAX_TEXT_CHARS:
            text = text[:MAX_TEXT_CHARS]

        body = json.dumps({
            "inputText": text,
            "dimensions": EMBED_DIMENSIONS,
        })

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self.client.invoke_model(
                    modelId=EMBED_MODEL_ID,
                    contentType="application/json",
                    accept="application/json",
                    body=body,
                )
                result = json.loads(resp["body"].read())
                return result["embedding"]

            except ClientError as e:
                error_code = e.response["Error"]["Code"]
                if error_code in ("ThrottlingException", "TooManyRequestsException",
                                  "ServiceUnavailableException"):
                    wait = BASE_BACKOFF * (2 ** (attempt - 1))
                    print(f"  [RETRY {attempt}/{MAX_RETRIES}] {error_code} → {wait:.1f}초 대기")
                    time.sleep(wait)
                else:
                    raise  # 재시도 불가능한 에러는 즉시 전파

        raise RuntimeError(f"API 호출 {MAX_RETRIES}회 재시도 후에도 실패")


# ──────────────────────────────────────────────
# 4단계: 메인 파이프라인
# ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Step 5: 임베딩 생성 & ChromaDB 적재")
    parser.add_argument("--limit", type=int, default=0,
                        help="처리할 최대 레코드 수 (0=전체, 예: --limit 200)")
    parser.add_argument("--hadm-list", type=str, default=None,
                        help="특정 hadm_id만 처리할 JSONL 파일 경로 (join_keys.hadm_id 기준 필터)")
    args = parser.parse_args()
    record_limit = args.limit

    # hadm_id 필터 로드
    target_hadm_ids = None
    if args.hadm_list:
        target_hadm_ids = set()
        with open(args.hadm_list, "r") as f:
            for line in f:
                rec = json.loads(line)
                target_hadm_ids.add(rec["join_keys"]["hadm_id"])
        print(f"[필터] {args.hadm_list} → {len(target_hadm_ids)}개 hadm_id 로드")

    print("=" * 60)
    print("Step 5: 임베딩 생성 & ChromaDB 적재")
    if record_limit:
        print(f"  ⚠ 샘플 모드: 최대 {record_limit}건만 처리")
    if target_hadm_ids:
        print(f"  🎯 타겟 모드: {len(target_hadm_ids)}개 hadm_id만 처리")
    print("=" * 60)

    # 체크포인트 로드
    done_ids = load_checkpoint()

    # 입력 파일 전체 줄 수 (tqdm 용)
    with open(INPUT_FILE, "r") as f:
        total_lines = sum(1 for _ in f)
    if target_hadm_ids:
        effective_total = len(target_hadm_ids)
    elif record_limit:
        effective_total = min(total_lines, record_limit)
    else:
        effective_total = total_lines
    print(f"[입력] 전체 레코드: {total_lines}건 → 처리 대상: {effective_total}건")

    # DB & 임베더 초기화
    db = ChromaDBConnector(persist_dir=DB_DIR, collection_name=COLLECTION_NAME)
    embedder = TitanEmbedder()

    # 배치 버퍼
    batch_ids = []
    batch_embeddings = []
    batch_documents = []
    batch_metadatas = []
    batch_hadm_ids = set()  # 현재 배치에 포함된 hadm_id 추적

    skipped = 0
    embedded_count = 0

    def flush_batch():
        """배치를 DB에 업로드하고 체크포인트를 갱신한다."""
        nonlocal batch_ids, batch_embeddings, batch_documents, batch_metadatas
        nonlocal batch_hadm_ids, done_ids

        if not batch_ids:
            return

        db.upsert_batch(batch_ids, batch_embeddings, batch_documents, batch_metadatas)
        done_ids.update(batch_hadm_ids)
        save_checkpoint(done_ids)

        batch_ids = []
        batch_embeddings = []
        batch_documents = []
        batch_metadatas = []
        batch_hadm_ids = set()

    processed_records = 0

    with open(INPUT_FILE, "r") as f:
        for line in tqdm(f, total=effective_total, desc="임베딩 진행"):
            record = json.loads(line)
            hadm_id = record["join_keys"]["hadm_id"]

            # 체크포인트: 이미 처리된 건 스킵
            if hadm_id in done_ids:
                skipped += 1
                continue

            # hadm_id 필터: 타겟 목록에 없으면 스킵
            if target_hadm_ids and hadm_id not in target_hadm_ids:
                continue

            # limit 도달 체크
            if record_limit and processed_records >= record_limit:
                break

            # 평탄화
            chunks = flatten_record(record)

            # 각 조각에 대해 임베딩 생성 → 배치 버퍼에 추가
            for chunk in chunks:
                vector = embedder.embed(chunk["text"])
                batch_ids.append(chunk["id"])
                batch_embeddings.append(vector)
                batch_documents.append(chunk["text"])
                batch_metadatas.append(chunk["metadata"])
                batch_hadm_ids.add(hadm_id)
                embedded_count += 1

                # 배치 크기 도달 시 flush
                if len(batch_ids) >= BATCH_SIZE:
                    flush_batch()

            processed_records += 1

    # 잔여 배치 flush
    flush_batch()

    print()
    print("=" * 60)
    print(f"[완료] 임베딩 생성 & 적재: {embedded_count}건")
    print(f"[스킵] 체크포인트 기존 완료: {skipped}건")
    print(f"[DB] 총 저장 문서 수: {db.count()}건")
    print("=" * 60)


if __name__ == "__main__":
    main()
