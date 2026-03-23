"""SageMaker Processing Job 내부 실행 스크립트 — 멀티 GPU 임베딩."""
import subprocess
subprocess.run(["pip", "install", "sentence-transformers"], check=True)

import torch
from sentence_transformers import SentenceTransformer
import numpy as np
import json
import os

device = "cuda"
print(f"GPUs: {torch.cuda.device_count()}")

model = SentenceTransformer("BAAI/bge-small-en-v1.5", device=device)
model.max_seq_length = 512

# 멀티 GPU 사용
if torch.cuda.device_count() > 1:
    pool = model.start_multi_process_pool()

records = []
with open("/opt/ml/processing/input/reports.jsonl", "r") as f:
    for line in f:
        if line.strip():
            records.append(json.loads(line))

impressions = []
for r in records:
    text = (r.get("impression") or "")[:300].strip()
    if len(text) < 3:
        text = "No impression available"
    impressions.append(text)

print(f"총 {len(impressions):,}건, GPUs: {torch.cuda.device_count()}")

if torch.cuda.device_count() > 1:
    embeddings = model.encode_multi_process(
        impressions, pool, batch_size=1024, normalize_embeddings=True
    )
    model.stop_multi_process_pool(pool)
else:
    embeddings = model.encode(
        impressions, batch_size=2048,
        show_progress_bar=True, normalize_embeddings=True
    )

print(f"완료: {embeddings.shape}")

os.makedirs("/opt/ml/processing/output", exist_ok=True)
np.save("/opt/ml/processing/output/embeddings.npy", embeddings)

# 메타데이터
with open("/opt/ml/processing/output/metadata.jsonl", "w") as f:
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

print("저장 완료")
