"""
Layer 5 RAG 인덱스 구축 — 4단계 순차 실행.

1. Bucket 7에서 판독문 추출 (S3 Select)
2. IMPRESSION을 Titan으로 임베딩
3. FAISS 인덱스 구축
4. S3 업로드

사용법:
  python run_all.py                  # 전체 실행
  python run_all.py --from-step 2    # Step 2부터 (reports.jsonl 이미 있을 때)
  python run_all.py --from-step 3    # Step 3부터 (embeddings.npy 이미 있을 때)
"""
import argparse
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-step", type=int, default=1, help="시작 단계 (1-4)")
    args = parser.parse_args()

    start = time.time()

    if args.from_step <= 1:
        print("=" * 60)
        print(" Step 1: 판독문 추출 (S3 Select)")
        print("=" * 60)
        from step1_extract_reports import extract_with_pandas
        extract_with_pandas()

    if args.from_step <= 2:
        print("\n" + "=" * 60)
        print(" Step 2: IMPRESSION 임베딩 (FastEmbed bge-small-en-v1.5)")
        print("=" * 60)
        from step2_embed_impressions import embed_all
        embed_all()

    if args.from_step <= 3:
        print("\n" + "=" * 60)
        print(" Step 3: FAISS 인덱스 구축")
        print("=" * 60)
        from step3_build_faiss_index import build_index
        build_index()

    if args.from_step <= 4:
        print("\n" + "=" * 60)
        print(" Step 4: S3 업로드")
        print("=" * 60)
        from step4_upload_to_s3 import upload_to_s3
        upload_to_s3()

    elapsed = time.time() - start
    print(f"\n{'=' * 60}")
    print(f" 전체 완료! ({elapsed:.0f}초, {elapsed/60:.1f}분)")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
