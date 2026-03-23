"""
Layer 2 Detection 배포 스크립트 — SageMaker 노트북에서 실행

배포 순서:
1. best_model.pth를 S3 models/ 경로에 업로드
2. ECR 리포지토리 생성
3. Docker 이미지 빌드 + 푸시
4. Lambda 함수 생성 (컨테이너 이미지)
5. Lambda Function URL 활성화
6. 샘플 이미지 S3 업로드

사용법:
  python deploy_layer2.py              # 전체 배포
  python deploy_layer2.py --step model # 모델만 업로드
  python deploy_layer2.py --step url   # Function URL만 확인
"""
import boto3
import json
import os
import subprocess
import sys
import time

# ============================================================
# 설정 (Layer 1과 동일 패턴)
# ============================================================
REGION = 'ap-northeast-2'
ACCOUNT_ID = '666803869796'
WORK_BUCKET = 'pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an'

ECR_REPO = 'layer2-detection'
LAMBDA_NAME = 'layer2-detection'
LAMBDA_ROLE = 'arn:aws:iam::666803869796:role/say-2-lambda-bedrock-role'
LAMBDA_MEMORY = 3008   # MB
LAMBDA_TIMEOUT = 180   # seconds (DenseNet cold start 여유)
LAMBDA_STORAGE = 2048  # MB (/tmp)

MODEL_S3_KEY = 'models/detection/densenet121.pth'
SAMPLE_S3_PREFIX = 'web/test-layer2/samples'

# 학습 완료 모델 위치
TRAINING_OUTPUT = 'output/densenet121-full-pa-v6-multigpu/output/model.tar.gz'
CHECKPOINT_PREFIX = 'checkpoints/densenet121-full-pa-v6-multigpu/'

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
# Step 0: 모델을 S3 models/ 경로에 준비
# ============================================================
def prepare_model():
    """학습 완료 모델 또는 체크포인트를 models/ 경로에 복사"""
    print('\n[Step 0] 모델 준비')

    # 이미 models/ 에 있는지 확인
    try:
        resp = s3.head_object(Bucket=WORK_BUCKET, Key=MODEL_S3_KEY)
        size_mb = resp['ContentLength'] / 1024 / 1024
        print(f'  이미 존재: s3://{WORK_BUCKET}/{MODEL_S3_KEY} ({size_mb:.1f} MB)')
        return True
    except Exception:
        pass

    # 학습 완료 모델 (model.tar.gz) 확인
    try:
        s3.head_object(Bucket=WORK_BUCKET, Key=TRAINING_OUTPUT)
        print('  model.tar.gz 발견! 압축 해제 후 업로드...')

        # 다운로드
        local_tar = '/tmp/model.tar.gz'
        s3.download_file(WORK_BUCKET, TRAINING_OUTPUT, local_tar)

        # 압축 해제
        import tarfile
        extract_dir = '/tmp/model_extracted'
        os.makedirs(extract_dir, exist_ok=True)
        with tarfile.open(local_tar, 'r:gz') as tar:
            tar.extractall(extract_dir)

        # best_model.pth 찾기
        model_path = None
        for fname in ['best_model.pth', 'model.pth']:
            candidate = os.path.join(extract_dir, fname)
            if os.path.exists(candidate):
                model_path = candidate
                break
        if model_path is None:
            for f in os.listdir(extract_dir):
                if f.endswith('.pth'):
                    model_path = os.path.join(extract_dir, f)
                    break

        if model_path:
            print(f'  업로드: {os.path.basename(model_path)} -> s3://{WORK_BUCKET}/{MODEL_S3_KEY}')
            s3.upload_file(model_path, WORK_BUCKET, MODEL_S3_KEY)
            print('  완료!')
            return True

    except Exception:
        pass

    # 체크포인트에서 가져오기
    print('  완료 모델 없음, 체크포인트 확인...')
    try:
        resp = s3.list_objects_v2(Bucket=WORK_BUCKET, Prefix=CHECKPOINT_PREFIX)
        pth_files = [o for o in resp.get('Contents', []) if o['Key'].endswith('.pth')]

        if pth_files:
            latest = sorted(pth_files, key=lambda x: x['LastModified'])[-1]
            size_mb = latest['Size'] / 1024 / 1024
            print(f'  체크포인트 복사: {os.path.basename(latest["Key"])} ({size_mb:.1f} MB)')
            s3.copy_object(
                Bucket=WORK_BUCKET,
                CopySource={'Bucket': WORK_BUCKET, 'Key': latest['Key']},
                Key=MODEL_S3_KEY
            )
            print(f'  -> s3://{WORK_BUCKET}/{MODEL_S3_KEY}')
            return True
    except Exception as e:
        print(f'  체크포인트 실패: {e}')

    print('  모델을 찾을 수 없습니다!')
    print(f'  학습 완료 후 다시 실행하세요.')
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

    # ECR 로그인
    run(f'aws ecr get-login-password --region {REGION} | docker login --username AWS --password-stdin {ACCOUNT_ID}.dkr.ecr.{REGION}.amazonaws.com')

    # 빌드 디렉토리
    build_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'layer2_detection')

    tag = f'{ecr_uri}:latest'
    print(f'  빌드 중... (3-5분 소요)')
    run(f'docker build --provenance=false -t {tag} {build_dir}')

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
        # 업데이트
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
    """test-images/ 에 있는 이미지를 web/test-layer2/samples/ 로 복사"""
    print(f'\n[Step 5] 샘플 이미지')

    src_prefix = 'test-images/'
    dst_prefix = SAMPLE_S3_PREFIX + '/'

    # 이미 있는지 확인
    resp = s3.list_objects_v2(Bucket=WORK_BUCKET, Prefix=dst_prefix, MaxKeys=1)
    if resp.get('Contents'):
        print(f'  이미 존재 ({len(resp["Contents"])}+ 파일)')
        return

    # test-images/ → web/test-layer2/samples/ 복사
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
    print(' Layer 2 Detection 배포')
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

    # 전체 배포
    if not prepare_model():
        print('\n모델이 없어서 배포를 중단합니다.')
        print('학습 완료 후 다시 실행하세요.')
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
