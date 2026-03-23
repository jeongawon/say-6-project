"""
Step 3: FAISS 인덱스 구축.

입력: build_output/embeddings.npy
출력: build_output/faiss_index.bin
"""
import faiss
import numpy as np
import os

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "build_output")


def build_index(embeddings_path: str = None, output_path: str = None):
    if embeddings_path is None:
        embeddings_path = os.path.join(OUTPUT_DIR, "embeddings.npy")
    if output_path is None:
        output_path = os.path.join(OUTPUT_DIR, "faiss_index.bin")

    embeddings = np.load(embeddings_path)
    dimension = embeddings.shape[1]  # 1024
    n_vectors = embeddings.shape[0]

    print(f"인덱스 구축: {n_vectors:,}개 벡터, {dimension}차원")

    # zero vector 제거 (임베딩 실패한 것들)
    norms = np.linalg.norm(embeddings, axis=1)
    valid_mask = norms > 0.01
    valid_count = valid_mask.sum()
    if valid_count < n_vectors:
        print(f"  zero vector {n_vectors - valid_count}개 제거 → {valid_count:,}개")
        embeddings = embeddings[valid_mask]
        n_vectors = valid_count

    # 100K 이하 → Flat (brute-force, 정확도 100%), 검색 ~5ms for 80K
    if n_vectors < 100000:
        index = faiss.IndexFlatIP(dimension)  # Inner Product (normalized → cosine)
        print(f"  IndexFlatIP (Flat, 정확도 100%)")
    else:
        # 100K 이상 → IVF 근사 검색
        nlist = int(np.sqrt(n_vectors))
        quantizer = faiss.IndexFlatIP(dimension)
        index = faiss.IndexIVFFlat(
            quantizer, dimension, nlist, faiss.METRIC_INNER_PRODUCT
        )
        index.train(embeddings)
        print(f"  IndexIVFFlat (nlist={nlist})")

    index.add(embeddings)
    faiss.write_index(index, output_path)

    file_size_mb = os.path.getsize(output_path) / 1024 / 1024
    print(f"인덱스 저장: {output_path}")
    print(f"  벡터 수: {index.ntotal:,}")
    print(f"  파일 크기: {file_size_mb:.1f} MB")

    return output_path


if __name__ == "__main__":
    build_index()
