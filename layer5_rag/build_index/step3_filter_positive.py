"""
Step 3a: 양성 소견 필터링.

880K embeddings + metadata에서 RAG 가치 높은 판독문만 추출.
재임베딩 없이 인덱스로 필터링만 수행.

필터 전략: 급성/신규 소견 + CheXpert 질환 2개 이상
  - MIMIC은 ICU 데이터라 대부분 비정상 → 단순 양성 필터로는 50만+
  - 급성(acute/new/worsening) + 복합 질환(2개+) = ~120K (목표 범위)
  - 이 조합이 RAG 레퍼런스로 가장 가치 높은 판독문
"""
import json
import re
import numpy as np
import os
import time

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "build_output")

# CheXpert 12 핵심 질환 (No Finding, Support Devices 제외)
DISEASE_KEYWORDS = [
    'atelectasis', 'cardiomegaly', 'consolidation', 'edema',
    'pleural effusion', 'pneumonia', 'pneumothorax', 'fracture',
    'infiltrate', 'nodule', 'mass', 'opacity',
]

# 급성/신규/악화 키워드
ACUTE_KEYWORDS = [
    r'new ',
    r'acute ',
    r'worsening',
    r'worsen',
    r'increas',
    r'develop',
    r'progressive',
    r'emergent',
    r'urgent',
    r'interval (?:develop|worsen|increase)',
    r'new(?:ly)? (?:develop|appear|seen|identified|noted)',
]


def is_valuable_report(impression: str) -> bool:
    """
    True = RAG에 포함할 가치 있는 판독문.
    조건: 급성/신규 키워드 + CheXpert 질환 2개 이상.
    """
    if not impression or len(impression.strip()) < 10:
        return False

    text = impression.lower().strip()

    # 질환 2개 이상?
    matched_diseases = sum(1 for kw in DISEASE_KEYWORDS if kw in text)
    if matched_diseases < 2:
        return False

    # 급성/신규 키워드?
    has_acute = any(re.search(kw, text) for kw in ACUTE_KEYWORDS)
    return has_acute


def run():
    meta_path = os.path.join(OUTPUT_DIR, "metadata.jsonl")
    emb_path = os.path.join(OUTPUT_DIR, "embeddings.npy")

    # 메타데이터 로드
    print("메타데이터 로드 중...")
    records = []
    with open(meta_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    print(f"  총 {len(records):,}건")

    # 필터링
    print("필터링 중 (급성 + 질환2개+)...")
    start = time.time()
    positive_indices = []
    for i, rec in enumerate(records):
        imp = rec.get("impression", "")
        if is_valuable_report(imp):
            positive_indices.append(i)
        if (i + 1) % 100000 == 0:
            pct = (i + 1) / len(records) * 100
            print(f"  {i+1:,}/{len(records):,} ({pct:.0f}%) — 통과: {len(positive_indices):,}")

    elapsed = time.time() - start
    print(f"\n필터링 완료: {len(positive_indices):,}/{len(records):,} "
          f"({len(positive_indices)/len(records)*100:.1f}%) — {elapsed:.1f}초")

    # 범위 체크
    if len(positive_indices) < 30000:
        print("WARNING: 3만 미만 — 필터가 너무 aggressive할 수 있음")
    elif len(positive_indices) > 200000:
        print("WARNING: 20만 초과 — Lambda /tmp에 안 들어갈 수 있음")
    else:
        print(f"OK: 목표 범위 50K~150K 내")

    # 임베딩 필터링
    print("\n임베딩 필터링 중...")
    embeddings = np.load(emb_path)
    print(f"  원본: {embeddings.shape}")

    idx_array = np.array(positive_indices)
    filtered_emb = embeddings[idx_array]
    print(f"  필터링: {filtered_emb.shape}")

    # 필터링된 메타데이터
    filtered_meta = [records[i] for i in positive_indices]

    # 저장
    filtered_emb_path = os.path.join(OUTPUT_DIR, "embeddings_filtered.npy")
    filtered_meta_path = os.path.join(OUTPUT_DIR, "metadata_filtered.jsonl")

    np.save(filtered_emb_path, filtered_emb)
    print(f"\n저장: {filtered_emb_path} ({filtered_emb.shape})")

    with open(filtered_meta_path, "w", encoding="utf-8") as f:
        for rec in filtered_meta:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"저장: {filtered_meta_path} ({len(filtered_meta):,}건)")

    emb_mb = os.path.getsize(filtered_emb_path) / 1024 / 1024
    meta_mb = os.path.getsize(filtered_meta_path) / 1024 / 1024
    print(f"\n크기: embeddings {emb_mb:.0f}MB, metadata {meta_mb:.0f}MB")

    # 예상 FAISS 인덱스 크기
    idx_est = len(positive_indices) * 384 * 4 / 1024 / 1024
    total_est = idx_est + meta_mb
    print(f"예상 FAISS 인덱스: ~{idx_est:.0f}MB, 총 합계: ~{total_est:.0f}MB")
    if total_est < 500:
        print("Lambda 1GB /tmp으로 충분!")

    return filtered_emb_path, filtered_meta_path, len(positive_indices)


if __name__ == "__main__":
    run()
