"""
Step 5.5: ChromaDB 임베딩 QC (Quality Check)
- DB 무결성, 벡터 품질, 다중 도메인 검색 테스트
- 결과: data/qc_report.json + 콘솔 요약
"""

import json
import os
import random
import time
from collections import Counter
from datetime import datetime

import boto3
import chromadb
import numpy as np
from botocore.exceptions import ClientError

# ──────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────
DB_DIR = "./local_rag_db"
COLLECTION_NAME = "medical_rag_collection"
EMBED_MODEL_ID = "amazon.titan-embed-text-v2:0"
EMBED_DIMENSIONS = 512
REPORT_PATH = "data/qc_report.json"
PAGE_SIZE = 5000  # 페이징 단위 (메모리 방어)
VECTOR_SAMPLE_SIZE = 100

SEARCH_QUERIES = {
    "호흡기": "Patient with severe pneumonia and consolidation in the right lower lobe",
    "심혈관": "Acute myocardial infarction with ST-segment elevation",
    "신경계": "Acute cerebral infarction with left hemiplegia",
    "외과": "Status post appendectomy, recovering well",
}


# ──────────────────────────────────────────────
# 유틸리티
# ──────────────────────────────────────────────
bedrock = boto3.client("bedrock-runtime")


def embed_text(text: str) -> list[float]:
    body = json.dumps({"inputText": text, "dimensions": EMBED_DIMENSIONS})
    for attempt in range(1, 4):
        try:
            resp = bedrock.invoke_model(
                modelId=EMBED_MODEL_ID,
                contentType="application/json",
                accept="application/json",
                body=body,
            )
            return json.loads(resp["body"].read())["embedding"]
        except ClientError:
            time.sleep(2 ** attempt)
    raise RuntimeError("임베딩 API 호출 실패")


# ──────────────────────────────────────────────
# 0단계: 리포트 초기화
# ──────────────────────────────────────────────
def init_report() -> dict:
    return {
        "qc_version": "1.0",
        "started_at": datetime.now().isoformat(),
        "completed_at": None,
        "step1_integrity": {},
        "step2_vector_quality": {},
        "step3_search_tests": {},
        "summary": {},
    }


# ──────────────────────────────────────────────
# 1단계: 데이터 무결성 & 커버리지
# ──────────────────────────────────────────────
def step1_integrity(collection, report: dict):
    print("[1단계] 데이터 무결성 & 커버리지 검사...")

    total = collection.count()
    chunk_type_counter = Counter()
    hadm_ids = set()
    sample_doc = None

    # 페이징으로 전체 메타데이터 순회
    offset = 0
    while offset < total:
        batch = collection.get(
            offset=offset,
            limit=PAGE_SIZE,
            include=["metadatas", "documents"],
        )
        for i, meta in enumerate(batch["metadatas"]):
            chunk_type_counter[meta.get("chunk_type", "unknown")] += 1
            hadm_ids.add(meta.get("hadm_id", ""))

            # 첫 번째 문서를 샘플로 저장
            if sample_doc is None:
                sample_doc = {
                    "id": batch["ids"][i],
                    "document_preview": batch["documents"][i][:300],
                    "metadata": meta,
                }

        offset += PAGE_SIZE

    result = {
        "total_documents": total,
        "chunk_type_distribution": dict(chunk_type_counter),
        "unique_hadm_ids": len(hadm_ids),
        "expected_hadm_ids": 10000,
        "hadm_coverage_pct": round(len(hadm_ids) / 10000 * 100, 2),
        "sample_document": sample_doc,
    }

    report["step1_integrity"] = result

    print(f"  총 문서: {total:,}건")
    for ct, cnt in chunk_type_counter.most_common():
        print(f"    {ct}: {cnt:,}건")
    print(f"  고유 hadm_id: {len(hadm_ids):,} / 10,000 ({result['hadm_coverage_pct']}%)")


# ──────────────────────────────────────────────
# 2단계: 벡터 품질 검사
# ──────────────────────────────────────────────
def step2_vector_quality(collection, report: dict):
    print("[2단계] 벡터 품질 검사...")

    total = collection.count()

    # 랜덤 오프셋으로 100건 샘플링
    max_offset = max(0, total - VECTOR_SAMPLE_SIZE)
    rand_offset = random.randint(0, max_offset)

    batch = collection.get(
        offset=rand_offset,
        limit=VECTOR_SAMPLE_SIZE,
        include=["embeddings"],
    )

    vectors = np.array(batch["embeddings"])
    n, dim = vectors.shape

    norms = np.linalg.norm(vectors, axis=1)
    zero_count = int(np.sum(norms < 1e-6))
    nan_count = int(np.sum(np.isnan(vectors).any(axis=1)))

    result = {
        "sampled": n,
        "dimensions": dim,
        "norm_mean": round(float(norms.mean()), 6),
        "norm_std": round(float(norms.std()), 6),
        "norm_min": round(float(norms.min()), 6),
        "norm_max": round(float(norms.max()), 6),
        "zero_vectors": zero_count,
        "nan_vectors": nan_count,
        "status": "정상" if (zero_count == 0 and nan_count == 0) else "불량",
    }

    report["step2_vector_quality"] = result

    print(f"  샘플: {n}건 (차원: {dim})")
    print(f"  L2 norm — 평균: {result['norm_mean']}, 표준편차: {result['norm_std']}")
    print(f"  Zero 벡터: {zero_count}건, NaN 벡터: {nan_count}건")
    print(f"  판정: {result['status']}")


# ──────────────────────────────────────────────
# 3단계: 다중 도메인 검색 테스트
# ──────────────────────────────────────────────
def step3_search_tests(collection, report: dict):
    print("[3단계] 다중 도메인 검색 테스트...")

    search_results = {}

    for domain, query in SEARCH_QUERIES.items():
        print(f"\n  [{domain}] \"{query[:60]}...\"")

        query_vec = embed_text(query)
        results = collection.query(
            query_embeddings=[query_vec],
            n_results=3,
            include=["documents", "metadatas", "distances"],
        )

        top3 = []
        for i in range(len(results["ids"][0])):
            similarity = round(1 - results["distances"][0][i], 4)
            meta = results["metadatas"][0][i]
            doc_preview = results["documents"][0][i][:200]

            top3.append({
                "rank": i + 1,
                "similarity": similarity,
                "chunk_type": meta.get("chunk_type", "?"),
                "hadm_id": meta.get("hadm_id", "?"),
                "document_preview": doc_preview,
            })

            print(f"    [{i+1}] sim={similarity:.4f} | "
                  f"type={meta.get('chunk_type','?')} | "
                  f"hadm={meta.get('hadm_id','?')}")
            print(f"        {doc_preview[:100]}...")

        # chunk_type 분포
        type_dist = Counter(r["chunk_type"] for r in top3)

        search_results[domain] = {
            "query": query,
            "top3": top3,
            "top3_chunk_types": dict(type_dist),
            "avg_similarity": round(
                sum(r["similarity"] for r in top3) / len(top3), 4
            ),
        }

    report["step3_search_tests"] = search_results


# ──────────────────────────────────────────────
# 4단계: 리포트 저장
# ──────────────────────────────────────────────
def step4_export(report: dict):
    # 요약 생성
    s1 = report["step1_integrity"]
    s2 = report["step2_vector_quality"]
    s3 = report["step3_search_tests"]

    avg_sim_all = round(
        sum(s3[d]["avg_similarity"] for d in s3) / len(s3), 4
    ) if s3 else 0

    report["summary"] = {
        "total_documents": s1.get("total_documents", 0),
        "hadm_coverage_pct": s1.get("hadm_coverage_pct", 0),
        "vector_status": s2.get("status", "미검사"),
        "search_avg_similarity": avg_sim_all,
        "overall": "PASS" if (
            s1.get("hadm_coverage_pct", 0) >= 99.0
            and s2.get("status") == "정상"
            and avg_sim_all > 0.2
        ) else "FAIL",
    }

    report["completed_at"] = datetime.now().isoformat()

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=4)

    print(f"\n[4단계] QC 리포트 저장 완료 → {REPORT_PATH}")


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  Step 5.5: ChromaDB 임베딩 QC")
    print("=" * 60)

    report = init_report()

    try:
        client = chromadb.PersistentClient(path=DB_DIR)
        collection = client.get_collection(name=COLLECTION_NAME)
    except Exception as e:
        print(f"[에러] DB 연결 실패: {e}")
        return

    step1_integrity(collection, report)
    step2_vector_quality(collection, report)

    try:
        step3_search_tests(collection, report)
    except Exception as e:
        print(f"[경고] 검색 테스트 실패 (AWS 자격 증명 확인): {e}")
        report["step3_search_tests"] = {"error": str(e)}

    step4_export(report)

    # 콘솔 요약
    s = report["summary"]
    print()
    print("=" * 60)
    print("  QC 검증 완료: 핵심 요약")
    print("=" * 60)
    print(f"  총 문서: {s['total_documents']:,}건")
    print(f"  hadm_id 커버리지: {s['hadm_coverage_pct']}%")
    print(f"  벡터 상태: {s['vector_status']}")
    print(f"  검색 평균 유사도: {s['search_avg_similarity']}")
    print(f"  최종 판정: {s['overall']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
