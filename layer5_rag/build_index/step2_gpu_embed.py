"""GPU 임베딩 스크립트 — SageMaker 노트북 인스턴스에서 실행."""
import torch
from sentence_transformers import SentenceTransformer
import numpy as np
import json
import time

device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Device: {device}, GPUs: {torch.cuda.device_count()}")

model = SentenceTransformer("BAAI/bge-small-en-v1.5", device=device)
model.max_seq_length = 512

records = []
with open("/tmp/reports.jsonl", "r") as f:
    for line in f:
        if line.strip():
            records.append(json.loads(line))

impressions = []
for r in records:
    text = (r.get("impression") or "")[:300].strip()
    if len(text) < 3:
        text = "No impression available"
    impressions.append(text)

print(f"Total: {len(impressions):,}, device={device}")

start = time.time()
embeddings = model.encode(
    impressions, batch_size=1024,
    show_progress_bar=True, normalize_embeddings=True
)
elapsed = time.time() - start
print(f"Done: {embeddings.shape} ({elapsed:.0f}s, {elapsed/60:.1f}min)")

np.save("/tmp/embeddings.npy", embeddings)

with open("/tmp/metadata.jsonl", "w") as f:
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

print("Saved")
