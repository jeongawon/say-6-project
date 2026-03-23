"""
Step 2 (SageMaker Notebook): ml.g5.xlarge에서 GPU 임베딩.
Lifecycle config → S3에서 스크립트 다운 → 실행 → 결과 S3 업로드 → 자동 중지.

비용: ~$1.41/hr × ~5분 = ~$0.12
"""
import boto3
import base64
import time
import os

BUCKET = "pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an"
ROLE = "arn:aws:iam::666803869796:role/service-role/SageMaker-ExecutionRole-20250722T101368"
REGION = "ap-northeast-2"
INSTANCE_NAME = "rag-embedding-runner"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "build_output")

# 단순한 lifecycle config — S3에서 스크립트 다운받아 실행
ON_START_SCRIPT = f"""#!/bin/bash
BUCKET="{BUCKET}"

# 스크립트 다운로드
aws s3 cp s3://$BUCKET/rag/build/step2_gpu_embed.py /tmp/step2_gpu_embed.py
aws s3 cp s3://$BUCKET/rag/build/step2_run_on_notebook.sh /tmp/step2_run_on_notebook.sh
chmod +x /tmp/step2_run_on_notebook.sh

# 백그라운드 실행 (5분 타임아웃 회피)
nohup /tmp/step2_run_on_notebook.sh > /home/ec2-user/SageMaker/nohup.log 2>&1 &
echo "Background job started"
"""


def run():
    sm = boto3.client("sagemaker", region_name=REGION)
    s3 = boto3.client("s3", region_name=REGION)

    # 1. 스크립트 S3 업로드
    script_dir = os.path.dirname(__file__)
    for fname in ["step2_gpu_embed.py", "step2_run_on_notebook.sh"]:
        local = os.path.join(script_dir, fname)
        key = f"rag/build/{fname}"
        s3.upload_file(local, BUCKET, key)
        print(f"S3 업로드: {fname} → s3://{BUCKET}/{key}")

    # 2. Lifecycle config 생성 (타임스탬프로 유니크 이름)
    config_name = f"rag-embed-{int(time.time())}"
    encoded = base64.b64encode(ON_START_SCRIPT.encode()).decode()

    sm.create_notebook_instance_lifecycle_config(
        NotebookInstanceLifecycleConfigName=config_name,
        OnStart=[{"Content": encoded}],
    )
    print(f"Lifecycle config 생성: {config_name}")

    # 3. 기존 인스턴스 처리
    try:
        resp = sm.describe_notebook_instance(NotebookInstanceName=INSTANCE_NAME)
        status = resp["NotebookInstanceStatus"]
        print(f"기존 인스턴스: {INSTANCE_NAME} (상태: {status})")

        if status == "InService":
            print("중지 후 재시작...")
            sm.stop_notebook_instance(NotebookInstanceName=INSTANCE_NAME)
            _wait_status(sm, "Stopped")

        if status in ("Stopped", "InService"):
            sm.update_notebook_instance(
                NotebookInstanceName=INSTANCE_NAME,
                LifecycleConfigName=config_name,
            )
            time.sleep(3)
            sm.start_notebook_instance(NotebookInstanceName=INSTANCE_NAME)
            print("인스턴스 시작...")
        elif status == "Pending":
            _wait_status(sm, "InService")
    except sm.exceptions.ClientError:
        print(f"노트북 인스턴스 생성: {INSTANCE_NAME} (ml.g5.xlarge)")
        sm.create_notebook_instance(
            NotebookInstanceName=INSTANCE_NAME,
            InstanceType="ml.g5.xlarge",
            RoleArn=ROLE,
            VolumeSizeInGB=50,
            LifecycleConfigName=config_name,
        )

    # 4. InService 대기
    _wait_status(sm, "InService")
    print("인스턴스 실행 중! 백그라운드 임베딩 진행 중...")

    # 5. DONE 마커 대기
    # 먼저 이전 DONE 삭제
    try:
        s3.delete_object(Bucket=BUCKET, Key="rag/build/output/DONE")
    except:
        pass

    print("\n임베딩 완료 대기...")
    start = time.time()
    while True:
        try:
            s3.head_object(Bucket=BUCKET, Key="rag/build/output/DONE")
            break
        except s3.exceptions.ClientError:
            elapsed = time.time() - start
            print(f"  대기 중... ({elapsed:.0f}초)", end="\r")
            time.sleep(10)

    elapsed = time.time() - start
    print(f"\n임베딩 완료! ({elapsed:.0f}초)")

    # 6. 결과 다운로드
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    emb_path = os.path.join(OUTPUT_DIR, "embeddings.npy")
    meta_path = os.path.join(OUTPUT_DIR, "metadata.jsonl")

    print("결과 다운로드...")
    s3.download_file(BUCKET, "rag/build/output/embeddings.npy", emb_path)
    print(f"  {emb_path}")
    s3.download_file(BUCKET, "rag/build/output/metadata.jsonl", meta_path)
    print(f"  {meta_path}")

    print("\n완료! 인스턴스는 자동으로 중지됩니다.")


def _wait_status(sm, target, timeout=600):
    start = time.time()
    while True:
        resp = sm.describe_notebook_instance(NotebookInstanceName=INSTANCE_NAME)
        status = resp["NotebookInstanceStatus"]
        elapsed = time.time() - start
        if status == target:
            return
        if elapsed > timeout:
            raise TimeoutError(f"{timeout}초 초과 — 현재: {status}")
        print(f"  상태: {status} → {target} ({elapsed:.0f}초)", end="\r")
        time.sleep(15)


if __name__ == "__main__":
    run()
