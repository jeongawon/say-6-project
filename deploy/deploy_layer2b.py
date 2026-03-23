"""
Layer 2b YOLOv8 Detection 배포 스크립트 — SageMaker 노트북에서 실행

배포 순서:
1. yolov8_vindr_best.pt 모델 S3 확인
2. ECR 리포지토리 생성
3. Docker 이미지 빌드 + 푸시
4. Lambda 함수 생성 (컨테이너 이미지)
5. Lambda Function URL 활성화
6. 샘플 이미지 S3 업로드

사용법:
  python deploy_layer2b.py              # 전체 배포
  python deploy_layer2b.py --step model # 모델만 확인
  python deploy_layer2b.py --step url   # Function URL만 확인
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

ECR_REPO = 'layer2b-yolov8'
LAMBDA_NAME = 'layer2b-yolov8'
LAMBDA_ROLE = 'arn:aws:iam::666803869796:role/say-2-lambda-bedrock-role'
LAMBDA_MEMORY = 3008   # MB
LAMBDA_TIMEOUT = 180   # seconds
LAMBDA_STORAGE = 2048  # MB (/tmp)

MODEL_S3_KEY = 'models/yolov8_vindr_best.pt'
SAMPLE_S3_PREFIX = 'web/test-layer2b/samples'

ecr = boto3.client('ecr', region_name=REGION)
lam = boto3.client('lambda', region_name=REGION)
s3 = boto3.client('s3', region_name=REGION)


def run(cmd, check=True):
    print(f'  $ {cmd}')
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout[-500:])
    if result.returncode != 0 and check:
        print(f'  ERROR: {result.stderr[-500:]}')
    return result


# ============================================================
# Step 0: 모델 확인
# ============================================================
def prepare_model():
    print('\n[Step 0] YOLOv8 모델 확인')
    try:
        resp = s3.head_object(Bucket=WORK_BUCKET, Key=MODEL_S3_KEY)
        size_mb = resp['ContentLength'] / 1024 / 1024
        print(f'  모델 존재: s3://{WORK_BUCKET}/{MODEL_S3_KEY} ({size_mb:.1f} MB)')
        return True
    except Exception:
        print(f'  모델 없음: s3://{WORK_BUCKET}/{MODEL_S3_KEY}')
        print(f'  YOLOv8 학습 완료 후 다시 실행하세요.')
        return False


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

    run(f'aws ecr get-login-password --region {REGION} | docker login --username AWS --password-stdin {ACCOUNT_ID}.dkr.ecr.{REGION}.amazonaws.com')

    build_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'layer2b_yolov8')

    tag = f'{ecr_uri}:latest'
    print(f'  빌드 중... (5-7분 소요, ultralytics 포함)')
    run(f'docker build -t {tag} {build_dir}')

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
        'MODEL_S3_KEY': MODEL_S3_KEY,
        'SAMPLE_S3_PREFIX': SAMPLE_S3_PREFIX,
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
                'AllowMethods': ['GET', 'POST', 'OPTIONS'],
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
# Step 5: 샘플 이미지 S3 업로드
# ============================================================
def upload_samples():
    print(f'\n[Step 5] 샘플 이미지')

    src_prefix = 'test-images/'
    dst_prefix = SAMPLE_S3_PREFIX + '/'

    resp = s3.list_objects_v2(Bucket=WORK_BUCKET, Prefix=dst_prefix, MaxKeys=1)
    if resp.get('Contents'):
        print(f'  이미 존재')
        return

    resp = s3.list_objects_v2(Bucket=WORK_BUCKET, Prefix=src_prefix)
    copied = 0
    for obj in resp.get('Contents', []):
        if obj['Key'].endswith(('.jpg', '.png', '.jpeg')) and obj['Size'] > 0:
            dst_key = dst_prefix + os.path.basename(obj['Key'])
            s3.copy_object(
                Bucket=WORK_BUCKET,
                CopySource={'Bucket': WORK_BUCKET, 'Key': obj['Key']},
                Key=dst_key
            )
            copied += 1
    print(f'  {copied}장 복사 완료')


# ============================================================
# 실행
# ============================================================
def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--step', type=str, default=None,
                        help='특정 단계만 실행: model, ecr, build, lambda, url, samples')
    args = parser.parse_args()

    print('=' * 60)
    print(' Layer 2b YOLOv8 Detection 배포')
    print('=' * 60)

    if args.step == 'model':
        prepare_model()
        return
    elif args.step == 'url':
        url = setup_function_url()
        print(f'\n  URL: {url}')
        return
    elif args.step == 'samples':
        upload_samples()
        return

    if not prepare_model():
        print('\n모델이 없어서 배포를 중단합니다.')
        sys.exit(1)

    ecr_uri = setup_ecr()
    image_uri = build_and_push(ecr_uri)
    setup_lambda(image_uri)
    url = setup_function_url()
    upload_samples()

    print('\n' + '=' * 60)
    print(' 배포 완료!')
    print('=' * 60)
    print(f'  Function URL: {url}')
    print(f'  모델: s3://{WORK_BUCKET}/{MODEL_S3_KEY}')
    print(f'  브라우저에서 위 URL로 접속하면 테스트 페이지가 뜹니다.')
    print('=' * 60)


if __name__ == '__main__':
    main()
