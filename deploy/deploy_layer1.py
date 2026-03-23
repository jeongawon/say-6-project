"""
Layer 1 Segmentation 배포 스크립트 — SageMaker 노트북에서 실행

배포 순서:
1. ECR 리포지토리 생성
2. Docker 이미지 빌드 + 푸시
3. Lambda 함수 생성 (컨테이너 이미지)
4. Lambda Function URL 활성화
5. 테스트 페이지 S3 업로드
6. CloudFront 배포

예상 비용: 프리티어 내 ~$0 (ECR 스토리지 ~$0.20/월)
"""
import boto3
import json
import os
import subprocess
import time

# ============================================================
# 설정
# ============================================================
REGION = 'ap-northeast-2'
ACCOUNT_ID = '666803869796'
WORK_BUCKET = 'pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an'

ECR_REPO = 'layer1-segmentation'
LAMBDA_NAME = 'layer1-segmentation'
LAMBDA_ROLE = 'arn:aws:iam::666803869796:role/say-2-lambda-bedrock-role'
LAMBDA_MEMORY = 3008  # MB
LAMBDA_TIMEOUT = 120  # seconds
LAMBDA_STORAGE = 2048  # MB (/tmp)

WEB_PREFIX = 'web/test-layer1'

ecr = boto3.client('ecr', region_name=REGION)
lam = boto3.client('lambda', region_name=REGION)
s3 = boto3.client('s3', region_name=REGION)
cf = boto3.client('cloudfront', region_name=REGION)
iam = boto3.client('iam', region_name=REGION)


def run(cmd, check=True):
    """쉘 명령 실행"""
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
    print('\n📦 Step 1: ECR 리포지토리')
    try:
        ecr.describe_repositories(repositoryNames=[ECR_REPO])
        print(f'  ✅ {ECR_REPO} 이미 존재')
    except ecr.exceptions.RepositoryNotFoundException:
        ecr.create_repository(repositoryName=ECR_REPO)
        print(f'  ✅ {ECR_REPO} 생성 완료')

    return f'{ACCOUNT_ID}.dkr.ecr.{REGION}.amazonaws.com/{ECR_REPO}'


# ============================================================
# Step 2: Docker 빌드 + ECR 푸시
# ============================================================
def build_and_push(ecr_uri):
    print('\n🐳 Step 2: Docker 빌드 + 푸시')

    # ECR 로그인
    token = ecr.get_authorization_token()
    endpoint = token['authorizationData'][0]['proxyEndpoint']
    run(f'aws ecr get-login-password --region {REGION} | docker login --username AWS --password-stdin {endpoint}')

    # 빌드 디렉토리로 이동
    build_dir = os.path.dirname(os.path.abspath(__file__)) + '/layer1_segmentation'

    # 빌드
    tag = f'{ecr_uri}:latest'
    print(f'  빌드 중... (3-5분 소요)')
    run(f'docker build -t {tag} {build_dir}')

    # 푸시
    print(f'  푸시 중...')
    run(f'docker push {tag}')
    print(f'  ✅ {tag}')

    return tag


# ============================================================
# Step 3: Lambda 함수 생성/업데이트
# ============================================================
def setup_lambda(image_uri):
    print('\n⚡ Step 3: Lambda 함수')

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
            Environment={'Variables': {
                'WORK_BUCKET': WORK_BUCKET,
                'MODEL_S3_PREFIX': 'models/segmentation/chest-x-ray-basic',
            }}
        )
        print(f'  ✅ {LAMBDA_NAME} 업데이트 완료')

    except lam.exceptions.ResourceNotFoundException:
        # 생성
        lam.create_function(
            FunctionName=LAMBDA_NAME,
            Role=LAMBDA_ROLE,
            PackageType='Image',
            Code={'ImageUri': image_uri},
            MemorySize=LAMBDA_MEMORY,
            Timeout=LAMBDA_TIMEOUT,
            EphemeralStorage={'Size': LAMBDA_STORAGE},
            Environment={'Variables': {
                'WORK_BUCKET': WORK_BUCKET,
                'MODEL_S3_PREFIX': 'models/segmentation/chest-x-ray-basic',
            }},
            Tags={'name': 'say2-preproject-6team-hyunwoo'}
        )
        print(f'  ✅ {LAMBDA_NAME} 생성 완료')

    # Lambda 활성화 대기
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
    print('\n🔗 Step 4: Lambda Function URL')

    try:
        resp = lam.get_function_url_config(FunctionName=LAMBDA_NAME)
        url = resp['FunctionUrl']
        print(f'  ✅ 이미 존재: {url}')
    except lam.exceptions.ResourceNotFoundException:
        # Function URL 생성
        resp = lam.create_function_url_config(
            FunctionName=LAMBDA_NAME,
            AuthType='NONE',
            Cors={
                'AllowOrigins': ['*'],
                'AllowMethods': ['POST', 'OPTIONS'],
                'AllowHeaders': ['Content-Type'],
            }
        )
        url = resp['FunctionUrl']

        # 퍼블릭 액세스 허용
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

        print(f'  ✅ Function URL: {url}')

    return url


# ============================================================
# Step 5: 테스트 페이지 S3 업로드
# ============================================================
def upload_test_page(lambda_url):
    print('\n📄 Step 5: 테스트 페이지 업로드')

    html_path = os.path.dirname(os.path.abspath(__file__)) + '/test_page/index.html'

    # HTML 업로드
    s3.upload_file(
        html_path, WORK_BUCKET,
        f'{WEB_PREFIX}/index.html',
        ExtraArgs={'ContentType': 'text/html; charset=utf-8'}
    )
    print(f'  ✅ s3://{WORK_BUCKET}/{WEB_PREFIX}/index.html')
    print(f'  Lambda URL: {lambda_url}')
    print(f'  (웹페이지에서 Lambda URL 입력 필요)')


# ============================================================
# Step 6: CloudFront 배포
# ============================================================
def setup_cloudfront():
    print('\n🌐 Step 6: CloudFront 배포')

    # 기존 배포 확인
    distributions = cf.list_distributions()
    existing = None
    for dist in distributions.get('DistributionList', {}).get('Items', []):
        for origin in dist.get('Origins', {}).get('Items', []):
            if WORK_BUCKET in origin.get('DomainName', ''):
                existing = dist
                break

    if existing:
        domain = existing['DomainName']
        print(f'  ✅ 기존 배포 사용: https://{domain}/{WEB_PREFIX}/index.html')
        return f'https://{domain}'

    # OAC 생성
    oac_name = f'{WORK_BUCKET}-oac'
    try:
        oac_resp = cf.create_origin_access_control(
            OriginAccessControlConfig={
                'Name': oac_name,
                'SigningProtocol': 'sigv4',
                'SigningBehavior': 'always',
                'OriginAccessControlOriginType': 's3',
            }
        )
        oac_id = oac_resp['OriginAccessControl']['Id']
    except Exception:
        # 이미 존재할 수 있음
        oacs = cf.list_origin_access_controls()
        oac_id = None
        for oac in oacs.get('OriginAccessControlList', {}).get('Items', []):
            if oac['Name'] == oac_name:
                oac_id = oac['Id']
                break
        if not oac_id:
            raise

    # CloudFront 배포 생성
    import string, random
    caller_ref = ''.join(random.choices(string.ascii_lowercase, k=12))

    resp = cf.create_distribution(
        DistributionConfig={
            'CallerReference': caller_ref,
            'Comment': 'Layer 1 Segmentation Test Page',
            'DefaultCacheBehavior': {
                'TargetOriginId': 's3-origin',
                'ViewerProtocolPolicy': 'redirect-to-https',
                'AllowedMethods': {'Quantity': 2, 'Items': ['GET', 'HEAD']},
                'ForwardedValues': {
                    'QueryString': False,
                    'Cookies': {'Forward': 'none'},
                },
                'MinTTL': 0,
                'DefaultTTL': 86400,
                'MaxTTL': 31536000,
                'Compress': True,
            },
            'Origins': {
                'Quantity': 1,
                'Items': [{
                    'Id': 's3-origin',
                    'DomainName': f'{WORK_BUCKET}.s3.{REGION}.amazonaws.com',
                    'OriginAccessControlId': oac_id,
                    'S3OriginConfig': {'OriginAccessIdentity': ''},
                }]
            },
            'Enabled': True,
            'DefaultRootObject': 'index.html',
            'PriceClass': 'PriceClass_200',
        }
    )

    dist_id = resp['Distribution']['Id']
    domain = resp['Distribution']['DomainName']

    # S3 버킷 정책 업데이트 (CloudFront 접근 허용)
    policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "AllowCloudFrontServicePrincipal",
            "Effect": "Allow",
            "Principal": {"Service": "cloudfront.amazonaws.com"},
            "Action": "s3:GetObject",
            "Resource": f"arn:aws:s3:::{WORK_BUCKET}/{WEB_PREFIX}/*",
            "Condition": {
                "StringEquals": {
                    "AWS:SourceArn": f"arn:aws:cloudfront::{ACCOUNT_ID}:distribution/{dist_id}"
                }
            }
        }]
    }

    try:
        s3.put_bucket_policy(Bucket=WORK_BUCKET, Policy=json.dumps(policy))
        print(f'  S3 버킷 정책 업데이트 완료')
    except Exception as e:
        print(f'  ⚠️ 버킷 정책 업데이트 실패: {e}')
        print(f'  수동으로 S3 퍼블릭 액세스 설정 필요할 수 있음')

    print(f'  ✅ CloudFront 배포 생성: https://{domain}')
    print(f'  ⏳ 배포 활성화까지 5-10분 소요')
    print(f'  테스트 URL: https://{domain}/{WEB_PREFIX}/index.html')

    return f'https://{domain}'


# ============================================================
# 실행
# ============================================================
if __name__ == '__main__':
    print('=' * 60)
    print('Layer 1 Segmentation 배포')
    print('=' * 60)

    ecr_uri = setup_ecr()
    image_uri = build_and_push(ecr_uri)
    setup_lambda(f'{image_uri}')
    lambda_url = setup_function_url()
    upload_test_page(lambda_url)

    print('\n' + '=' * 60)
    print('배포 완료!')
    print(f'  Lambda URL: {lambda_url}')
    print(f'  테스트 페이지: s3://{WORK_BUCKET}/{WEB_PREFIX}/index.html')
    print()
    print('CloudFront 배포도 하려면:')
    print('  setup_cloudfront() 함수 실행')
    print('  또는 S3 정적 웹호스팅으로도 테스트 가능')
    print('=' * 60)
