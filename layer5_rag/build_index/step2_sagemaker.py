"""
Step 2 (SageMaker): Processing Job으로 880K 임베딩.
ml.g5.12xlarge (A10G x4, 96GB VRAM) — 2~3분 완료 예상.
비용: ~$0.35 (시간당 $7.09 × ~3분)

로컬에서 실행 — Job 제출 + 완료 대기 + 결과 다운로드.
"""
import boto3
import sagemaker
from sagemaker.processing import ScriptProcessor, ProcessingInput, ProcessingOutput
import os
import time

BUCKET = "pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an"
ROLE = "arn:aws:iam::666803869796:role/service-role/SageMaker-ExecutionRole-20250722T101368"
REGION = "ap-northeast-2"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "build_output")


def run():
    s3 = boto3.client("s3", region_name=REGION)

    # 1. reports.jsonl S3 업로드
    reports_path = os.path.join(OUTPUT_DIR, "reports.jsonl")
    print(f"S3 업로드: {reports_path} → s3://{BUCKET}/rag/build/reports.jsonl")
    start = time.time()
    s3.upload_file(reports_path, BUCKET, "rag/build/reports.jsonl")
    print(f"S3 업로드 완료 ({time.time()-start:.0f}초)")

    # 2. 스크립트도 S3에 업로드
    script_path = os.path.join(os.path.dirname(__file__), "step2_processing_script.py")
    s3.upload_file(script_path, BUCKET, "rag/build/step2_processing_script.py")
    script_s3_uri = f"s3://{BUCKET}/rag/build/step2_processing_script.py"
    print(f"스크립트 업로드: {script_s3_uri}")

    # 3. Processing Job 실행
    print("\nSageMaker Processing Job 제출...")
    session = sagemaker.Session(boto_session=boto3.Session(region_name=REGION))

    processor = ScriptProcessor(
        image_uri="763104351884.dkr.ecr.ap-northeast-2.amazonaws.com/pytorch-training:2.1.0-gpu-py310-cu121-ubuntu20.04-sagemaker",
        role=ROLE,
        instance_count=1,
        instance_type="ml.g5.12xlarge",
        command=["python3"],
        base_job_name="rag-embedding",
        sagemaker_session=session,
    )

    processor.run(
        code=script_s3_uri,
        inputs=[
            ProcessingInput(
                source=f"s3://{BUCKET}/rag/build/reports.jsonl",
                destination="/opt/ml/processing/input",
            )
        ],
        outputs=[
            ProcessingOutput(
                source="/opt/ml/processing/output",
                destination=f"s3://{BUCKET}/rag/build/output",
            )
        ],
    )
    print("Job 완료!")

    # 3. 결과 다운로드
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    emb_path = os.path.join(OUTPUT_DIR, "embeddings.npy")
    meta_path = os.path.join(OUTPUT_DIR, "metadata.jsonl")

    print("\n결과 다운로드...")
    s3.download_file(BUCKET, "rag/build/output/embeddings.npy", emb_path)
    print(f"  {emb_path}")
    s3.download_file(BUCKET, "rag/build/output/metadata.jsonl", meta_path)
    print(f"  {meta_path}")
    print("다운로드 완료!")


if __name__ == "__main__":
    run()
