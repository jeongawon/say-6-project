"""
Step 2: 추출된 판독문의 IMPRESSION을 SentenceTransformer (bge-small-en-v1.5)로 벡터화.

GPU 있으면 GPU, 없으면 CPU 풀코어.
show_progress_bar=True로 tqdm 진행바 출력.

입력: build_output/reports.jsonl
출력: build_output/embeddings.npy, build_output/metadata.jsonl
"""
import torch
from sentence_transformers import SentenceTransformer
import numpy as np
import json
import os
import time

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "build_output")


def embed_all(reports_path: str = None):
    if reports_path is None:
        reports_path = os.path.join(OUTPUT_DIR, "reports.jsonl")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}, CPU cores: {torch.get_num_threads()}")
    if device == "cpu":
        torch.set_num_threads(os.cpu_count())
        print(f"CPU threads 설정: {os.cpu_count()}")

    model = SentenceTransformer("BAAI/bge-small-en-v1.5", device=device)
    model.max_seq_length = 512

    # 데이터 로드 + 전처리
    records = []
    with open(reports_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))

    impressions = []
    for r in records:
        text = (r.get("impression") or "")[:300].strip()
        if len(text) < 3:
            text = "No impression available"
        impressions.append(text)

    print(f"총 {len(impressions):,}건, device={device}")

    # 임베딩
    start = time.time()
    embeddings = model.encode(
        impressions,
        batch_size=1024 if device == "cuda" else 256,
        show_progress_bar=True,
        normalize_embeddings=True,
    )
    elapsed = time.time() - start

    print(f"완료: {embeddings.shape} ({elapsed:.0f}초, {elapsed/60:.1f}분)")

    # 저장
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    emb_path = os.path.join(OUTPUT_DIR, "embeddings.npy")
    np.save(emb_path, embeddings)
    print(f"저장 완료: {emb_path}")

    # 메타데이터 저장
    meta_path = os.path.join(OUTPUT_DIR, "metadata.jsonl")
    with open(meta_path, "w", encoding="utf-8") as f:
        for record in records:
            meta = {
                "note_id": record["note_id"],
                "subject_id": record["subject_id"],
                "hadm_id": record["hadm_id"],
                "charttime": record["charttime"],
                "impression": record["impression"],
                "findings": record["findings"],
                "indication": record["indication"],
                "examination": record["examination"],
                "comparison": record["comparison"],
            }
            f.write(json.dumps(meta, ensure_ascii=False) + "\n")

    print(f"메타데이터 저장: {meta_path}")
    return emb_path, meta_path


if __name__ == "__main__":
    embed_all()
