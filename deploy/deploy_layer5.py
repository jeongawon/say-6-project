"""
Layer 5 RAG 배포 스크립트 — 로컬 CLI에서 실행

배포 순서:
1. 소스 코드를 Docker 빌드 디렉토리에 복사
2. ECR 리포지토리 생성
3. Docker 이미지 빌드 + 푸시  (~250MB, faiss-cpu 포함)
4. Lambda 함수 생성 (컨테이너 이미지)
5. Lambda Function URL 활성화

초기에는 USE_MOCK=true로 배포 (FAISS 인덱스 없이 mock 데이터로 동작).
인덱스 구축 후 USE_MOCK=false로 환경변수만 변경하면 live 모드 전환.

사용법:
  python deploy_layer5.py              # 전체 배포
  python deploy_layer5.py --step url   # Function URL만 확인
"""
import boto3
import json
import os
import shutil
import subprocess
import sys
import time

# ============================================================
# 설정
# ============================================================
REGION = "ap-northeast-2"
ACCOUNT_ID = "666803869796"
WORK_BUCKET = "pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an"

ECR_REPO = "layer5-rag"
LAMBDA_NAME = "layer5-rag"
LAMBDA_ROLE = "arn:aws:iam::666803869796:role/say-2-lambda-bedrock-role"
LAMBDA_MEMORY = 1024  # MB — FAISS 인덱스 로드용
LAMBDA_TIMEOUT = 30
LAMBDA_STORAGE = 512  # MB (/tmp) — 인덱스 다운로드용

ecr = boto3.client("ecr", region_name=REGION)
lam = boto3.client("lambda", region_name=REGION)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "layer5_rag")


def run(cmd, check=True):
    print(f"  $ {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout[-500:])
    if result.returncode != 0 and check:
        print(f"  ERROR: {result.stderr[-500:]}")
    return result


# ============================================================
# Step 0: 소스 코드를 빌드 디렉토리에 복사
# ============================================================
def prepare_source():
    """layer5_rag/ 패키지를 Docker 빌드 컨텍스트에 복사"""
    print("\n[Step 0] 소스 코드 준비")

    src = os.path.join(PROJECT_ROOT, "layer5_rag")
    dst = os.path.join(BUILD_DIR, "layer5_rag")
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(
        src, dst,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests", "build_output", "build_index"),
    )
    print(f"  layer5_rag/ -> {dst}")

    count = sum(len(files) for _, _, files in os.walk(dst))
    print(f"  총 {count}개 파일 준비 완료")


# ============================================================
# Step 1: ECR 리포지토리
# ============================================================
def setup_ecr():
    print(f"\n[Step 1] ECR 리포지토리: {ECR_REPO}")
    try:
        ecr.describe_repositories(repositoryNames=[ECR_REPO])
        print("  이미 존재")
    except ecr.exceptions.RepositoryNotFoundException:
        ecr.create_repository(repositoryName=ECR_REPO)
        print("  생성 완료")
    return f"{ACCOUNT_ID}.dkr.ecr.{REGION}.amazonaws.com/{ECR_REPO}"


# ============================================================
# Step 2: Docker 빌드 + ECR 푸시
# ============================================================
def build_and_push(ecr_uri):
    print("\n[Step 2] Docker 빌드 + 푸시")
    run(
        f"aws ecr get-login-password --region {REGION} | "
        f"docker login --username AWS --password-stdin "
        f"{ACCOUNT_ID}.dkr.ecr.{REGION}.amazonaws.com"
    )

    tag = f"{ecr_uri}:latest"
    print("  빌드 중... (~2분, faiss-cpu 포함)")
    run(f"docker build --provenance=false --platform linux/amd64 -t {tag} {BUILD_DIR}")

    print("  푸시 중...")
    run(f"docker push {tag}")
    print(f"  완료: {tag}")
    return tag


# ============================================================
# Step 3: Lambda 함수 생성/업데이트
# ============================================================
def setup_lambda(image_uri):
    print(f"\n[Step 3] Lambda 함수: {LAMBDA_NAME}")

    env_vars = {
        "WORK_BUCKET": WORK_BUCKET,
        "USE_MOCK": "true",  # 초기에는 mock 모드
    }

    try:
        lam.get_function(FunctionName=LAMBDA_NAME)
        lam.update_function_code(
            FunctionName=LAMBDA_NAME,
            ImageUri=image_uri,
        )
        time.sleep(5)
        lam.update_function_configuration(
            FunctionName=LAMBDA_NAME,
            MemorySize=LAMBDA_MEMORY,
            Timeout=LAMBDA_TIMEOUT,
            EphemeralStorage={"Size": LAMBDA_STORAGE},
            Environment={"Variables": env_vars},
        )
        print("  업데이트 완료")
    except lam.exceptions.ResourceNotFoundException:
        lam.create_function(
            FunctionName=LAMBDA_NAME,
            Role=LAMBDA_ROLE,
            PackageType="Image",
            Code={"ImageUri": image_uri},
            MemorySize=LAMBDA_MEMORY,
            Timeout=LAMBDA_TIMEOUT,
            EphemeralStorage={"Size": LAMBDA_STORAGE},
            Environment={"Variables": env_vars},
            Tags={"project": "pre-project-6team"},
        )
        print("  생성 완료")

    # 활성화 대기
    print("  Lambda 활성화 대기...")
    for _ in range(30):
        resp = lam.get_function(FunctionName=LAMBDA_NAME)
        state = resp["Configuration"]["State"]
        if state == "Active":
            break
        time.sleep(5)
    print(f"  State: {state}")


# ============================================================
# Step 4: Lambda Function URL
# ============================================================
def setup_function_url():
    print(f"\n[Step 4] Function URL")

    cors_config = {
        "AllowOrigins": ["*"],
        "AllowMethods": ["GET", "POST"],
        "AllowHeaders": ["Content-Type"],
    }

    try:
        resp = lam.get_function_url_config(FunctionName=LAMBDA_NAME)
        url = resp["FunctionUrl"]
        print(f"  이미 존재: {url}")
        # CORS 강제 업데이트
        lam.update_function_url_config(
            FunctionName=LAMBDA_NAME,
            Cors=cors_config,
        )
        print(f"  CORS 업데이트 완료")
    except lam.exceptions.ResourceNotFoundException:
        resp = lam.create_function_url_config(
            FunctionName=LAMBDA_NAME,
            AuthType="NONE",
            Cors=cors_config,
        )
        url = resp["FunctionUrl"]

        try:
            lam.add_permission(
                FunctionName=LAMBDA_NAME,
                StatementId="FunctionURLAllowPublicAccess",
                Action="lambda:InvokeFunctionUrl",
                Principal="*",
                FunctionUrlAuthType="NONE",
            )
        except lam.exceptions.ResourceConflictException:
            pass

        print(f"  Function URL: {url}")

    return url


# ============================================================
# 정리
# ============================================================
def cleanup():
    d = os.path.join(BUILD_DIR, "layer5_rag")
    if os.path.exists(d):
        shutil.rmtree(d)
    print("  빌드 임시 파일 정리 완료")


# ============================================================
# 실행
# ============================================================
def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--step", type=str, default=None,
        help="특정 단계만 실행: source, ecr, build, lambda, url",
    )
    args = parser.parse_args()

    print("=" * 60)
    print(" Layer 5 RAG 배포")
    print(" (FAISS + Titan Embeddings, ~250MB 이미지)")
    print("=" * 60)

    if args.step == "url":
        url = setup_function_url()
        print(f"\n  URL: {url}")
        return
    elif args.step == "source":
        prepare_source()
        return

    prepare_source()
    ecr_uri = setup_ecr()
    image_uri = build_and_push(ecr_uri)
    setup_lambda(image_uri)
    url = setup_function_url()
    cleanup()

    print("\n" + "=" * 60)
    print(" 배포 완료!")
    print("=" * 60)
    print(f"  Function URL: {url}")
    print(f"  모드: MOCK (인덱스 구축 후 USE_MOCK=false로 전환)")
    print()
    print("  Layer 5 특징:")
    print("    - 이미지 ~250MB (faiss-cpu 포함)")
    print("    - Mock 모드: 10건의 가상 판독문으로 즉시 테스트")
    print("    - Live 모드: FAISS 인덱스(~200MB) S3에서 로드")
    print("    - 비용: 호출당 ~$0.0003 (Titan 임베딩 포함)")
    print("=" * 60)


if __name__ == "__main__":
    main()
