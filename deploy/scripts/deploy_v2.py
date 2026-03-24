"""
Dr. AI Radiologist v2 — Python 배포 스크립트 (boto3)
v1 deploy_layer*.py와 동일 방식.

사용법: python deploy_v2.py
"""
import boto3
import json
import os
import subprocess
import time
import sys

# ============================================================
# 설정
# ============================================================
REGION = "ap-northeast-2"
ACCOUNT_ID = "666803869796"
S3_BUCKET = f"pre-project-practice-hyunwoo-{ACCOUNT_ID}-{REGION}-an"

PROJECT = "dr-ai-radiologist"
LAMBDA_ROLE = f"arn:aws:iam::{ACCOUNT_ID}:role/say-2-lambda-bedrock-role"
SFN_ROLE = f"arn:aws:iam::{ACCOUNT_ID}:role/service-role/StepFunctions-HelloWorldStateMachine-role-8f67rqw9n"

# SKKU_TagEnforcementPolicy 필수 태그: project = "pre-*team"
TAGS = {"project": "pre-6team"}

REPO_PREFIX = f"{ACCOUNT_ID}.dkr.ecr.{REGION}.amazonaws.com"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
V2_DIR = os.path.dirname(SCRIPT_DIR)

ecr = boto3.client("ecr", region_name=REGION)
lam = boto3.client("lambda", region_name=REGION)
sfn = boto3.client("stepfunctions", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)
apigw = boto3.client("apigateway", region_name=REGION)


def run(cmd, check=True):
    print(f"  $ {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout[-500:])
    if result.returncode != 0:
        print(f"  STDERR: {result.stderr[-500:]}")
        if check:
            raise RuntimeError(f"Command failed: {cmd}")
    return result


def wait_lambda_active(func_name, max_wait=120):
    print(f"  Lambda 활성화 대기: {func_name}")
    for _ in range(max_wait // 5):
        resp = lam.get_function(FunctionName=func_name)
        state = resp["Configuration"]["State"]
        if state == "Active":
            last_status = resp["Configuration"].get("LastUpdateStatus", "")
            if last_status in ("", "Successful"):
                print(f"  State: Active")
                return
        time.sleep(5)
    print(f"  경고: 타임아웃. 현재 상태: {state}")


# ============================================================
# Step 1: ECR 로그인 + 리포지토리
# ============================================================
def step1_ecr():
    print("\n[1/7] ECR 로그인 + 리포지토리")

    run(f"aws ecr get-login-password --region {REGION} | docker login --username AWS --password-stdin {REPO_PREFIX}")

    for repo_name in [f"{PROJECT}-lambda-a", f"{PROJECT}-lambda-b"]:
        try:
            ecr.describe_repositories(repositoryNames=[repo_name])
            print(f"  리포지토리 존재: {repo_name}")
        except ecr.exceptions.RepositoryNotFoundException:
            ecr.create_repository(repositoryName=repo_name)
            print(f"  리포지토리 생성: {repo_name}")


# ============================================================
# Step 2: Lambda A (Vision Inference)
# ============================================================
def step2_lambda_a():
    print("\n[2/7] Lambda A (Vision Inference)")

    func_name = f"{PROJECT}-vision-inference"
    ecr_uri = f"{REPO_PREFIX}/{PROJECT}-lambda-a"
    tag = f"{ecr_uri}:latest"

    # Docker 빌드 + 푸시
    print("  Docker 빌드...")
    run(f"docker build --provenance=false --platform linux/amd64 -t {tag} -f {V2_DIR}/lambda_a/Dockerfile {V2_DIR}")
    print("  ECR 푸시...")
    run(f"docker push {tag}")

    # Lambda 생성/업데이트
    try:
        lam.get_function(FunctionName=func_name)
        print(f"  Lambda 업데이트: {func_name}")
        lam.update_function_code(FunctionName=func_name, ImageUri=tag)
        wait_lambda_active(func_name)
        lam.update_function_configuration(
            FunctionName=func_name,
            MemorySize=4096,
            Timeout=120,
            Environment={"Variables": {
                "S3_BUCKET": S3_BUCKET,
                "AWS_REGION_OVERRIDE": REGION,
            }},
        )
    except lam.exceptions.ResourceNotFoundException:
        print(f"  Lambda 생성: {func_name}")
        lam.create_function(
            FunctionName=func_name,
            Role=LAMBDA_ROLE,
            PackageType="Image",
            Code={"ImageUri": tag},
            MemorySize=4096,
            Timeout=120,
            Environment={"Variables": {
                "S3_BUCKET": S3_BUCKET,
                "AWS_REGION_OVERRIDE": REGION,
            }},
            Tags=TAGS,
        )
    wait_lambda_active(func_name)
    print(f"  완료: {func_name}")


# ============================================================
# Step 3: Lambda B (Analysis & Report)
# ============================================================
def step3_lambda_b():
    print("\n[3/7] Lambda B (Analysis & Report)")

    func_name = f"{PROJECT}-analysis-report"
    ecr_uri = f"{REPO_PREFIX}/{PROJECT}-lambda-b"
    tag = f"{ecr_uri}:latest"

    print("  Docker 빌드...")
    run(f"docker build --provenance=false --platform linux/amd64 -t {tag} -f {V2_DIR}/lambda_b/Dockerfile {V2_DIR}")
    print("  ECR 푸시...")
    run(f"docker push {tag}")

    try:
        lam.get_function(FunctionName=func_name)
        print(f"  Lambda 업데이트: {func_name}")
        lam.update_function_code(FunctionName=func_name, ImageUri=tag)
        wait_lambda_active(func_name)
        lam.update_function_configuration(
            FunctionName=func_name,
            MemorySize=2048,
            Timeout=180,
            Environment={"Variables": {
                "S3_BUCKET": S3_BUCKET,
                "AWS_REGION_OVERRIDE": REGION,
            }},
        )
    except lam.exceptions.ResourceNotFoundException:
        print(f"  Lambda 생성: {func_name}")
        lam.create_function(
            FunctionName=func_name,
            Role=LAMBDA_ROLE,
            PackageType="Image",
            Code={"ImageUri": tag},
            MemorySize=2048,
            Timeout=180,
            Environment={"Variables": {
                "S3_BUCKET": S3_BUCKET,
                "AWS_REGION_OVERRIDE": REGION,
            }},
            Tags=TAGS,
        )
    wait_lambda_active(func_name)
    print(f"  완료: {func_name}")


# ============================================================
# Step 4: Step Functions
# ============================================================
def step4_step_functions():
    print("\n[4/7] Step Functions 상태 머신")

    sm_name = f"{PROJECT}-pipeline-v2"
    sm_arn = f"arn:aws:states:{REGION}:{ACCOUNT_ID}:stateMachine:{sm_name}"
    lambda_a_arn = f"arn:aws:lambda:{REGION}:{ACCOUNT_ID}:function:{PROJECT}-vision-inference"
    lambda_b_arn = f"arn:aws:lambda:{REGION}:{ACCOUNT_ID}:function:{PROJECT}-analysis-report"

    # ASL 로드 + ARN 치환
    asl_path = os.path.join(V2_DIR, "step_functions", "state_machine.json")
    with open(asl_path) as f:
        asl = f.read()
    asl = asl.replace("${LambdaAArn}", lambda_a_arn)
    asl = asl.replace("${LambdaBArn}", lambda_b_arn)

    try:
        sfn.describe_state_machine(stateMachineArn=sm_arn)
        print(f"  상태 머신 업데이트: {sm_name}")
        sfn.update_state_machine(
            stateMachineArn=sm_arn,
            definition=asl,
            roleArn=SFN_ROLE,
        )
    except sfn.exceptions.StateMachineDoesNotExist:
        print(f"  상태 머신 생성 (STANDARD): {sm_name}")
        sfn.create_state_machine(
            name=sm_name,
            definition=asl,
            roleArn=SFN_ROLE,
            type="STANDARD",
            tags=[{"key": "name", "value": "say2-preproject-6team-hyunwoo"}],
        )

    print(f"  완료: {sm_arn}")


# ============================================================
# Step 5: Gateway Lambda (API Handler)
# ============================================================
def step5_gateway_lambda():
    print("\n[5/7] Gateway Lambda")

    func_name = f"{PROJECT}-v2-gateway"
    sm_arn = f"arn:aws:states:{REGION}:{ACCOUNT_ID}:stateMachine:{PROJECT}-pipeline-v2"

    # ZIP 패키징
    src_dir = os.path.join(V2_DIR, "api-gateway", "status-lambda")
    zip_path = f"/tmp/{func_name}.zip"
    run(f"cd {src_dir} && zip -j {zip_path} status_handler.py")

    with open(zip_path, "rb") as f:
        zip_bytes = f.read()

    try:
        lam.get_function(FunctionName=func_name)
        print(f"  Lambda 업데이트: {func_name}")
        lam.update_function_code(FunctionName=func_name, ZipFile=zip_bytes)
        wait_lambda_active(func_name)
        lam.update_function_configuration(
            FunctionName=func_name,
            Timeout=30,
            MemorySize=256,
            Environment={"Variables": {
                "S3_BUCKET": S3_BUCKET,
                "STATE_MACHINE_ARN": sm_arn,
            }},
        )
    except lam.exceptions.ResourceNotFoundException:
        print(f"  Lambda 생성: {func_name}")
        lam.create_function(
            FunctionName=func_name,
            Role=LAMBDA_ROLE,
            Runtime="python3.12",
            Handler="status_handler.lambda_handler",
            Code={"ZipFile": zip_bytes},
            Timeout=30,
            MemorySize=256,
            Environment={"Variables": {
                "S3_BUCKET": S3_BUCKET,
                "STATE_MACHINE_ARN": sm_arn,
            }},
            Tags=TAGS,
        )
    wait_lambda_active(func_name)
    print(f"  완료: {func_name}")


# ============================================================
# Step 6: API Gateway
# ============================================================
def step6_api_gateway():
    print("\n[6/7] API Gateway")

    api_name = f"{PROJECT}-v2-api"
    stage = "test"
    gw_lambda_name = f"{PROJECT}-v2-gateway"
    gw_lambda_arn = f"arn:aws:lambda:{REGION}:{ACCOUNT_ID}:function:{gw_lambda_name}"

    # API 생성/재사용
    apis = apigw.get_rest_apis()
    api_id = None
    for api in apis["items"]:
        if api["name"] == api_name:
            api_id = api["id"]
            break

    if api_id:
        print(f"  기존 API 재사용: {api_id}")
    else:
        resp = apigw.create_rest_api(
            name=api_name,
            description="Dr. AI Radiologist v2 API (Async Polling)",
            endpointConfiguration={"types": ["REGIONAL"]},
            tags=TAGS,
        )
        api_id = resp["id"]
        print(f"  API 생성: {api_id}")

    # 리소스 가져오기
    resources = apigw.get_resources(restApiId=api_id)
    root_id = None
    analyze_id = None
    status_id = None
    for r in resources["items"]:
        if r["path"] == "/":
            root_id = r["id"]
        elif r["path"] == "/analyze":
            analyze_id = r["id"]
        elif r["path"] == "/analyze/status":
            status_id = r["id"]

    # /analyze 리소스
    if not analyze_id:
        resp = apigw.create_resource(restApiId=api_id, parentId=root_id, pathPart="analyze")
        analyze_id = resp["id"]
        print(f"  /analyze 생성: {analyze_id}")

    # /analyze/status 리소스
    if not status_id:
        resp = apigw.create_resource(restApiId=api_id, parentId=analyze_id, pathPart="status")
        status_id = resp["id"]
        print(f"  /analyze/status 생성: {status_id}")

    # Lambda Proxy 설정 함수
    def setup_method(resource_id, method, path):
        try:
            apigw.delete_method(restApiId=api_id, resourceId=resource_id, httpMethod=method)
        except Exception:
            pass
        apigw.put_method(
            restApiId=api_id, resourceId=resource_id,
            httpMethod=method, authorizationType="NONE",
        )
        apigw.put_integration(
            restApiId=api_id, resourceId=resource_id,
            httpMethod=method, type="AWS_PROXY",
            integrationHttpMethod="POST",
            uri=f"arn:aws:apigateway:{REGION}:lambda:path/2015-03-31/functions/{gw_lambda_arn}/invocations",
        )
        print(f"  {method} {path} -> Lambda Proxy")

    # OPTIONS CORS Mock 설정 함수
    def setup_options(resource_id, path):
        try:
            apigw.delete_method(restApiId=api_id, resourceId=resource_id, httpMethod="OPTIONS")
        except Exception:
            pass
        apigw.put_method(
            restApiId=api_id, resourceId=resource_id,
            httpMethod="OPTIONS", authorizationType="NONE",
        )
        apigw.put_integration(
            restApiId=api_id, resourceId=resource_id,
            httpMethod="OPTIONS", type="MOCK",
            requestTemplates={"application/json": '{"statusCode": 200}'},
        )
        apigw.put_method_response(
            restApiId=api_id, resourceId=resource_id,
            httpMethod="OPTIONS", statusCode="200",
            responseParameters={
                "method.response.header.Access-Control-Allow-Origin": False,
                "method.response.header.Access-Control-Allow-Methods": False,
                "method.response.header.Access-Control-Allow-Headers": False,
            },
            responseModels={"application/json": "Empty"},
        )
        apigw.put_integration_response(
            restApiId=api_id, resourceId=resource_id,
            httpMethod="OPTIONS", statusCode="200",
            responseParameters={
                "method.response.header.Access-Control-Allow-Origin": "'*'",
                "method.response.header.Access-Control-Allow-Methods": "'POST,GET,OPTIONS'",
                "method.response.header.Access-Control-Allow-Headers": "'Content-Type'",
            },
            responseTemplates={"application/json": ""},
        )
        print(f"  OPTIONS {path} (CORS Mock)")

    setup_method(analyze_id, "POST", "/analyze")
    setup_method(status_id, "GET", "/analyze/status")
    setup_options(analyze_id, "/analyze")
    setup_options(status_id, "/analyze/status")

    # Lambda 호출 권한
    ts = str(int(time.time()))
    for stmt, source in [
        (f"apigw-post-{ts}", f"arn:aws:execute-api:{REGION}:{ACCOUNT_ID}:{api_id}/*/POST/analyze"),
        (f"apigw-get-{ts}", f"arn:aws:execute-api:{REGION}:{ACCOUNT_ID}:{api_id}/*/GET/analyze/status"),
    ]:
        try:
            lam.add_permission(
                FunctionName=gw_lambda_name,
                StatementId=stmt,
                Action="lambda:InvokeFunction",
                Principal="apigateway.amazonaws.com",
                SourceArn=source,
            )
        except lam.exceptions.ResourceConflictException:
            pass

    # 배포
    apigw.create_deployment(
        restApiId=api_id, stageName=stage,
        description=f"v2 deployment {time.strftime('%Y%m%d-%H%M%S')}",
    )

    api_url = f"https://{api_id}.execute-api.{REGION}.amazonaws.com/{stage}"
    print(f"\n  API URL: {api_url}")
    print(f"  POST {api_url}/analyze")
    print(f"  GET  {api_url}/analyze/status?id={{executionArn}}")

    with open(f"/tmp/{PROJECT}-api-url.txt", "w") as f:
        f.write(api_url)

    return api_url


# ============================================================
# Step 7: S3 Lifecycle
# ============================================================
def step7_lifecycle():
    print("\n[7/7] S3 Lifecycle Rule")

    s3.put_bucket_lifecycle_configuration(
        Bucket=S3_BUCKET,
        LifecycleConfiguration={
            "Rules": [{
                "ID": "expire-runs-after-7-days",
                "Filter": {"Prefix": "runs/"},
                "Status": "Enabled",
                "Expiration": {"Days": 7},
            }]
        },
    )
    print("  runs/ -> 7일 만료 설정 완료")


# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print(" Dr. AI Radiologist v2 — 배포 (boto3)")
    print(f" Account: {ACCOUNT_ID}  Region: {REGION}")
    print("=" * 60)

    step1_ecr()
    step2_lambda_a()
    step3_lambda_b()
    step4_step_functions()
    step5_gateway_lambda()
    api_url = step6_api_gateway()
    step7_lifecycle()

    print("\n" + "=" * 60)
    print(" 배포 완료!")
    print("=" * 60)
    print(f"  Lambda A  : {PROJECT}-vision-inference")
    print(f"  Lambda B  : {PROJECT}-analysis-report")
    print(f"  Gateway   : {PROJECT}-v2-gateway")
    print(f"  SFN       : {PROJECT}-pipeline-v2")
    print(f"  API       : {api_url}")
    print(f"  S3        : {S3_BUCKET}")
    print("=" * 60)
