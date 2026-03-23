"""
통합 오케스트레이터 배포 스크립트 - 로컬 CLI에서 실행

배포 순서:
1. ECR 리포지토리 생성 (chest-modal-integrated)
2. Docker 이미지 빌드 (~760MB, requests만 포함)
3. ECR 로그인 + 푸시
4. Lambda 함수 생성/업데이트 (512MB, 300s timeout)
5. Function URL 생성 + 테스트

GPU/PyTorch 불필요 -> 이미지 작고, cold start 빠르고, 메모리 적게 씀.
각 Layer Lambda를 HTTP로 호출하는 오케스트레이터.

사용법:
  python deploy_integrated.py              # 전체 배포
  python deploy_integrated.py --step url   # Function URL만 확인
"""
import boto3
import json
import os
import subprocess
import sys
import time

# ============================================================
# 설정
# ============================================================
REGION = 'ap-northeast-2'
ACCOUNT_ID = '666803869796'
WORK_BUCKET = 'pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an'

ECR_REPO = 'chest-modal-integrated'
LAMBDA_NAME = 'chest-modal-integrated'
LAMBDA_ROLE = 'arn:aws:iam::666803869796:role/say-2-lambda-bedrock-role'
LAMBDA_MEMORY = 512    # MB - HTTP 호출만이라 512MB 충분
LAMBDA_TIMEOUT = 300   # seconds - 6개 Layer 순차 호출 대기
LAMBDA_STORAGE = 512   # MB (/tmp)

# 각 Layer 엔드포인트 (Lambda 환경변수로 주입)
LAYER_ENDPOINTS = {
    'LAYER1_URL': 'https://jwhljyevn3hm44nhvs5zcdstmi0tmuvi.lambda-url.ap-northeast-2.on.aws/',
    'LAYER2_URL': 'https://pk67s3qrp3b3xluqkcp6neqly40kduol.lambda-url.ap-northeast-2.on.aws/',
    'LAYER2B_URL': 'https://yoaval7laoc4ngnkr7uod7dufm0nmxib.lambda-url.ap-northeast-2.on.aws/',
    'LAYER3_URL': 'https://ihq6gjldxbulfke5xd2xexnoqe0vyrxt.lambda-url.ap-northeast-2.on.aws/',
    'LAYER5_URL': 'https://rn32hjcarfgqhopm266iidoeey0lkbkt.lambda-url.ap-northeast-2.on.aws/',
    'LAYER6_URL': 'https://ofii46d5p6446ceahn3ucb5f2a0xcvej.lambda-url.ap-northeast-2.on.aws/',
}

ecr = boto3.client('ecr', region_name=REGION)
lam = boto3.client('lambda', region_name=REGION)

BUILD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chest_modal_orchestrator')


def run(cmd, check=True):
    print(f'  $ {cmd}')
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout[-500:])
    if result.returncode != 0 and check:
        print(f'  ERROR: {result.stderr[-500:]}')
    return result


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
    print(f'  빌드 중... (~1분, requests만 포함)')
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
    }
    env_vars.update(LAYER_ENDPOINTS)

    try:
        lam.get_function(FunctionName=LAMBDA_NAME)
        # 업데이트
        lam.update_function_code(
            FunctionName=LAMBDA_NAME,
            ImageUri=image_uri,
        )
        print('  코드 업데이트 중... (활성화 대기)')
        for _ in range(20):
            resp = lam.get_function(FunctionName=LAMBDA_NAME)
            if resp['Configuration']['LastUpdateStatus'] == 'Successful':
                break
            time.sleep(3)
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
            Architectures=['x86_64'],
            Tags={'project': 'pre-project-6team'},
        )
        print(f'  생성 완료')

    # 활성화 대기
    print('  Lambda 활성화 대기...')
    state = 'Pending'
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

    try:
        resp = lam.get_function_url_config(FunctionName=LAMBDA_NAME)
        url = resp['FunctionUrl']
        print(f'  이미 존재: {url}')
    except lam.exceptions.ResourceNotFoundException:
        resp = lam.create_function_url_config(
            FunctionName=LAMBDA_NAME,
            AuthType='NONE',
            Cors={
                'AllowOrigins': ['*'],
                'AllowMethods': ['GET', 'POST'],
                'AllowHeaders': ['Content-Type'],
            }
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
# Step 5: 빠른 헬스 체크
# ============================================================
def health_check(url):
    print(f'\n[Step 5] 헬스 체크')
    import requests

    try:
        # GET → 테스트 페이지 반환 확인
        resp = requests.get(url, timeout=30)
        if resp.status_code == 200 and 'text/html' in resp.headers.get('Content-Type', ''):
            print(f'  GET 테스트 페이지: OK ({len(resp.text)} bytes)')
        else:
            print(f'  GET 응답: {resp.status_code}')

        # POST list_test_cases → 5개 케이스 반환 확인
        resp = requests.post(url, json={"action": "list_test_cases"}, timeout=30)
        data = resp.json()
        cases = data.get("test_cases", {})
        print(f'  POST list_test_cases: {len(cases)}개 케이스 ({list(cases.keys())})')

    except Exception as e:
        print(f'  헬스 체크 실패 (cold start 중일 수 있음): {e}')
        print(f'  30초 후 브라우저에서 직접 확인하세요: {url}')


# ============================================================
# 실행
# ============================================================
def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--step', type=str, default=None,
                        help='특정 단계만 실행: ecr, build, lambda, url, test')
    args = parser.parse_args()

    print('=' * 60)
    print(' 통합 오케스트레이터 배포 (chest-modal-integrated)')
    print(' (순수 Python + requests, GPU 불필요)')
    print(f' 6개 Layer를 HTTP로 호출하는 오케스트레이터')
    print('=' * 60)

    if args.step == 'url':
        url = setup_function_url()
        print(f'\n  URL: {url}')
        return
    elif args.step == 'test':
        url = setup_function_url()
        health_check(url)
        return

    # 전체 배포
    ecr_uri = setup_ecr()
    image_uri = build_and_push(ecr_uri)
    setup_lambda(image_uri)
    url = setup_function_url()
    health_check(url)

    print('\n' + '=' * 60)
    print(' 배포 완료!')
    print('=' * 60)
    print(f'  Function URL: {url}')
    print(f'  브라우저에서 위 URL로 접속하면 통합 테스트 페이지가 뜹니다.')
    print()
    print('  통합 오케스트레이터 특징:')
    print('    - 이미지 ~760MB (Python 3.12 base + requests)')
    print('    - Cold start ~3초')
    print(f'    - 메모리 {LAMBDA_MEMORY}MB, 타임아웃 {LAMBDA_TIMEOUT}초')
    print('    - 6개 Layer를 HTTP로 순차/병렬 호출')
    print('    - 비용: Lambda 실행 ~$0.04/call (주로 대기 시간)')
    print('=' * 60)


if __name__ == '__main__':
    main()
