"""
Layer 6 Bedrock Report 배포 스크립트 - 로컬 CLI에서 실행

배포 순서:
1. 소스 코드를 Docker 빌드 디렉토리에 복사
2. ECR 리포지토리 생성
3. Docker 이미지 빌드 + 푸시 (~150MB, 순수 Python + boto3)
4. Lambda 함수 생성 (컨테이너 이미지)
5. Lambda Function URL 활성화

GPU/PyTorch 불필요 -> 이미지 작고, cold start 빠르고, 메모리 적게 씀.
Bedrock InvokeModel 권한은 say-2-lambda-bedrock-role에 이미 포함.

사용법:
  python deploy_layer6.py              # 전체 배포
  python deploy_layer6.py --step url   # Function URL만 확인
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
REGION = 'ap-northeast-2'
ACCOUNT_ID = '666803869796'
WORK_BUCKET = 'pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an'

ECR_REPO = 'layer6-bedrock-report'
LAMBDA_NAME = 'layer6-bedrock-report'
LAMBDA_ROLE = 'arn:aws:iam::666803869796:role/say-2-lambda-bedrock-role'
LAMBDA_MEMORY = 256    # MB - Bedrock 호출만이라 256MB 충분
LAMBDA_TIMEOUT = 120   # seconds - Bedrock 응답 대기 포함 (cold start + 생성 시간)
LAMBDA_STORAGE = 512   # MB (/tmp)

# Bedrock 모델 설정
BEDROCK_MODEL_ID = 'global.anthropic.claude-sonnet-4-6'

ecr = boto3.client('ecr', region_name=REGION)
lam = boto3.client('lambda', region_name=REGION)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'layer6_bedrock_report')


def run(cmd, check=True):
    print(f'  $ {cmd}')
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout[-500:])
    if result.returncode != 0 and check:
        print(f'  ERROR: {result.stderr[-500:]}')
    return result


# ============================================================
# Step 0: 소스 코드를 빌드 디렉토리에 복사
# ============================================================
def prepare_source():
    """layer6_bedrock_report/ 패키지를 Docker 빌드 컨텍스트에 복사"""
    print('\n[Step 0] 소스 코드 준비')

    # layer6_bedrock_report 패키지 복사
    src = os.path.join(PROJECT_ROOT, 'layer6_bedrock_report')
    dst = os.path.join(BUILD_DIR, 'layer6_bedrock_report')
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(
        '__pycache__', '*.pyc', 'tests'))
    print(f'  layer6_bedrock_report/ -> {dst}')

    # 파일 수 확인
    count = sum(len(files) for _, _, files in os.walk(dst))
    print(f'  총 {count}개 파일 준비 완료')


# ============================================================
# Step 1: ECR 리포지토리
# ============================================================
def setup_ecr():
    print(f'\n[Step 1] ECR 리포지토리: {ECR_REPO}')
    try:
        ecr.describe_repositories(repositoryNames=[ECR_REPO])
        print(f'  이미 존재')
    except ecr.exceptions.RepositoryNotFoundException:
        ecr.create_repository(repositoryName=ECR_REPO)
        print(f'  생성 완료')

    return f'{ACCOUNT_ID}.dkr.ecr.{REGION}.amazonaws.com/{ECR_REPO}'


# ============================================================
# Step 2: Docker 빌드 + ECR 푸시
# ============================================================
def build_and_push(ecr_uri):
    print(f'\n[Step 2] Docker 빌드 + 푸시')

    # ECR 로그인
    run(f'aws ecr get-login-password --region {REGION} | docker login --username AWS --password-stdin {ACCOUNT_ID}.dkr.ecr.{REGION}.amazonaws.com')

    tag = f'{ecr_uri}:latest'
    print(f'  빌드 중... (~1분, PyTorch 없어서 빠름)')
    run(f'docker build --provenance=false -t {tag} {BUILD_DIR}')

    print(f'  푸시 중...')
    run(f'docker push {tag}')
    print(f'  완료: {tag}')

    return tag


# ============================================================
# Step 3: Lambda 함수 생성/업데이트
# ============================================================
def setup_lambda(image_uri):
    print(f'\n[Step 3] Lambda 함수: {LAMBDA_NAME}')

    env_vars = {
        'WORK_BUCKET': WORK_BUCKET,
        'BEDROCK_MODEL_ID': BEDROCK_MODEL_ID,
        'AWS_REGION_OVERRIDE': REGION,
    }

    try:
        lam.get_function(FunctionName=LAMBDA_NAME)
        # 업데이트
        lam.update_function_code(
            FunctionName=LAMBDA_NAME,
            ImageUri=image_uri,
        )
        print('  코드 업데이트 중...')
        time.sleep(5)
        lam.update_function_configuration(
            FunctionName=LAMBDA_NAME,
            MemorySize=LAMBDA_MEMORY,
            Timeout=LAMBDA_TIMEOUT,
            EphemeralStorage={'Size': LAMBDA_STORAGE},
            Environment={'Variables': env_vars},
        )
        print(f'  업데이트 완료')
    except lam.exceptions.ResourceNotFoundException:
        lam.create_function(
            FunctionName=LAMBDA_NAME,
            Role=LAMBDA_ROLE,
            PackageType='Image',
            Code={'ImageUri': image_uri},
            MemorySize=LAMBDA_MEMORY,
            Timeout=LAMBDA_TIMEOUT,
            EphemeralStorage={'Size': LAMBDA_STORAGE},
            Environment={'Variables': env_vars},
            Tags={'project': 'pre-project-6team'},
        )
        print(f'  생성 완료')

    # 활성화 대기
    print('  Lambda 활성화 대기...')
    for _ in range(30):
        resp = lam.get_function(FunctionName=LAMBDA_NAME)
        state = resp['Configuration']['State']
        if state == 'Active':
            break
        time.sleep(5)
    print(f'  State: {state}')


# ============================================================
# Step 4: Lambda Function URL
# ============================================================
def setup_function_url():
    print(f'\n[Step 4] Function URL')

    cors_config = {
        'AllowOrigins': ['*'],
        'AllowMethods': ['GET', 'POST'],
        'AllowHeaders': ['Content-Type'],
    }

    try:
        resp = lam.get_function_url_config(FunctionName=LAMBDA_NAME)
        url = resp['FunctionUrl']
        print(f'  이미 존재: {url}')
        # CORS 강제 업데이트
        lam.update_function_url_config(
            FunctionName=LAMBDA_NAME,
            Cors=cors_config,
        )
        print(f'  CORS 업데이트 완료')
    except lam.exceptions.ResourceNotFoundException:
        resp = lam.create_function_url_config(
            FunctionName=LAMBDA_NAME,
            AuthType='NONE',
            Cors=cors_config,
        )
        url = resp['FunctionUrl']

        try:
            lam.add_permission(
                FunctionName=LAMBDA_NAME,
                StatementId='FunctionURLAllowPublicAccess',
                Action='lambda:InvokeFunctionUrl',
                Principal='*',
                FunctionUrlAuthType='NONE',
            )
        except lam.exceptions.ResourceConflictException:
            pass

        print(f'  Function URL: {url}')

    return url


# ============================================================
# 정리
# ============================================================
def cleanup():
    """Docker 빌드 후 복사된 소스 코드 정리"""
    path = os.path.join(BUILD_DIR, 'layer6_bedrock_report')
    if os.path.exists(path):
        shutil.rmtree(path)
    print('  빌드 임시 파일 정리 완료')


# ============================================================
# 실행
# ============================================================
def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--step', type=str, default=None,
                        help='특정 단계만 실행: source, ecr, build, lambda, url')
    args = parser.parse_args()

    print('=' * 60)
    print(' Layer 6 Bedrock Report 배포')
    print(' (순수 Python + boto3, GPU 불필요, ~150MB 이미지)')
    print(f' Bedrock Model: {BEDROCK_MODEL_ID}')
    print('=' * 60)

    if args.step == 'url':
        url = setup_function_url()
        print(f'\n  URL: {url}')
        return
    elif args.step == 'source':
        prepare_source()
        return

    # 전체 배포
    prepare_source()
    ecr_uri = setup_ecr()
    image_uri = build_and_push(ecr_uri)
    setup_lambda(image_uri)
    url = setup_function_url()
    cleanup()

    print('\n' + '=' * 60)
    print(' 배포 완료!')
    print('=' * 60)
    print(f'  Function URL: {url}')
    print(f'  브라우저에서 위 URL로 접속하면 테스트 페이지가 뜹니다.')
    print()
    print('  Layer 6 특징:')
    print('    - 이미지 ~150MB (Layer 1/2의 1/10)')
    print('    - Cold start ~2초')
    print('    - 메모리 256MB')
    print(f'    - Bedrock Model: {BEDROCK_MODEL_ID}')
    print('    - 비용: Bedrock 호출당 ~$0.05 (입력+출력)')
    print('=' * 60)


if __name__ == '__main__':
    main()
