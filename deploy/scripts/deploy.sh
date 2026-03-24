#!/bin/bash
# Dr. AI Radiologist v2 — 배포 스크립트
# 사용법: cd deploy/v2 && bash scripts/deploy.sh
set -euo pipefail

###############################################################################
# 변수 설정
###############################################################################
ACCOUNT_ID="666803869796"
REGION="ap-northeast-2"
PROJECT="dr-ai-radiologist"
S3_BUCKET="pre-project-practice-hyunwoo-${ACCOUNT_ID}-${REGION}-an"

# ECR 리포지토리
REPO_PREFIX="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
REPO_LAMBDA_A="${REPO_PREFIX}/${PROJECT}-lambda-a"
REPO_LAMBDA_B="${REPO_PREFIX}/${PROJECT}-lambda-b"

# Lambda 함수 이름
FUNC_LAMBDA_A="${PROJECT}-vision-inference"
FUNC_LAMBDA_B="${PROJECT}-analysis-report"

# Step Functions
STATE_MACHINE_NAME="${PROJECT}-pipeline-v2"

# IAM 역할 (기존 v1 역할 재사용 — IAM 생성 권한 없음)
LAMBDA_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/say-2-lambda-bedrock-role"
SFN_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/service-role/StepFunctions-HelloWorldStateMachine-role-8f67rqw9n"

# 태그 (SKKU_TagEnforcementPolicy 필수)
REQUIRED_TAGS="project=say2-preproject-6team"

# 이미지 태그
IMAGE_TAG="latest"

# 프로젝트 루트 (deploy/v2 기준)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
V2_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "============================================================"
echo " Dr. AI Radiologist v2 — 배포 시작"
echo " Account: ${ACCOUNT_ID}  Region: ${REGION}"
echo "============================================================"

###############################################################################
# 1. ECR 로그인
###############################################################################
echo ""
echo "[1/7] ECR 로그인..."
aws ecr get-login-password --region "${REGION}" \
  | docker login --username AWS --password-stdin "${REPO_PREFIX}"
echo "  -> ECR 로그인 완료"

###############################################################################
# 2. ECR 리포지토리 생성 (없으면)
###############################################################################
echo ""
echo "[2/7] ECR 리포지토리 확인/생성..."

for REPO_NAME in "${PROJECT}-lambda-a" "${PROJECT}-lambda-b"; do
  if aws ecr describe-repositories \
      --repository-names "${REPO_NAME}" \
      --region "${REGION}" >/dev/null 2>&1; then
    echo "  -> 리포지토리 존재: ${REPO_NAME}"
  else
    echo "  -> 리포지토리 생성: ${REPO_NAME}"
    aws ecr create-repository \
      --repository-name "${REPO_NAME}" \
      --region "${REGION}" \
      --image-scanning-configuration scanOnPush=true
  fi
done

###############################################################################
# 3. Lambda A — Vision Inference (빌드 + 푸시 + 배포)
###############################################################################
echo ""
echo "[3/7] Lambda A (Vision Inference) 배포..."

echo "  -> Docker 빌드: Lambda A"
docker build \
  -t "${REPO_LAMBDA_A}:${IMAGE_TAG}" \
  -f "${V2_DIR}/lambda_a/Dockerfile" \
  "${V2_DIR}"

echo "  -> ECR 푸시: Lambda A"
docker push "${REPO_LAMBDA_A}:${IMAGE_TAG}"

LAMBDA_A_IMAGE_URI="${REPO_LAMBDA_A}:${IMAGE_TAG}"

# Lambda 함수 생성 또는 업데이트
if aws lambda get-function --function-name "${FUNC_LAMBDA_A}" --region "${REGION}" >/dev/null 2>&1; then
  echo "  -> Lambda A 업데이트 (update-function-code)..."
  aws lambda update-function-code \
    --function-name "${FUNC_LAMBDA_A}" \
    --image-uri "${LAMBDA_A_IMAGE_URI}" \
    --region "${REGION}"
else
  echo "  -> Lambda A 생성 (create-function)..."
  aws lambda create-function \
    --function-name "${FUNC_LAMBDA_A}" \
    --package-type Image \
    --code "ImageUri=${LAMBDA_A_IMAGE_URI}" \
    --role "${LAMBDA_ROLE_ARN}" \
    --timeout 120 \
    --memory-size 4096 \
    --environment "Variables={S3_BUCKET=${S3_BUCKET},AWS_REGION_OVERRIDE=${REGION}}" \
    --tags "${REQUIRED_TAGS}" \
    --region "${REGION}"
fi

echo "  -> Lambda A 배포 완료: ${FUNC_LAMBDA_A}"

###############################################################################
# 4. Lambda B — Analysis & Report (빌드 + 푸시 + 배포)
###############################################################################
echo ""
echo "[4/7] Lambda B (Analysis & Report) 배포..."

echo "  -> Docker 빌드: Lambda B"
docker build \
  -t "${REPO_LAMBDA_B}:${IMAGE_TAG}" \
  -f "${V2_DIR}/lambda_b/Dockerfile" \
  "${V2_DIR}"

echo "  -> ECR 푸시: Lambda B"
docker push "${REPO_LAMBDA_B}:${IMAGE_TAG}"

LAMBDA_B_IMAGE_URI="${REPO_LAMBDA_B}:${IMAGE_TAG}"

# Lambda 함수 생성 또는 업데이트
if aws lambda get-function --function-name "${FUNC_LAMBDA_B}" --region "${REGION}" >/dev/null 2>&1; then
  echo "  -> Lambda B 업데이트 (update-function-code)..."
  aws lambda update-function-code \
    --function-name "${FUNC_LAMBDA_B}" \
    --image-uri "${LAMBDA_B_IMAGE_URI}" \
    --region "${REGION}"
else
  echo "  -> Lambda B 생성 (create-function)..."
  aws lambda create-function \
    --function-name "${FUNC_LAMBDA_B}" \
    --package-type Image \
    --code "ImageUri=${LAMBDA_B_IMAGE_URI}" \
    --role "${LAMBDA_ROLE_ARN}" \
    --timeout 180 \
    --memory-size 2048 \
    --environment "Variables={S3_BUCKET=${S3_BUCKET},AWS_REGION_OVERRIDE=${REGION}}" \
    --tags "${REQUIRED_TAGS}" \
    --region "${REGION}"
fi

echo "  -> Lambda B 배포 완료: ${FUNC_LAMBDA_B}"

###############################################################################
# 5. Step Functions — State Machine (EXPRESS 타입)
###############################################################################
echo ""
echo "[5/7] Step Functions 상태 머신 배포..."

# Lambda ARN 구성
LAMBDA_A_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${FUNC_LAMBDA_A}"
LAMBDA_B_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${FUNC_LAMBDA_B}"

# ASL 템플릿에서 플레이스홀더를 실제 ARN으로 치환
ASL_TEMPLATE="${V2_DIR}/step_functions/state_machine.json"
ASL_RENDERED=$(sed \
  -e "s|\${LambdaAArn}|${LAMBDA_A_ARN}|g" \
  -e "s|\${LambdaBArn}|${LAMBDA_B_ARN}|g" \
  "${ASL_TEMPLATE}")

STATE_MACHINE_ARN="arn:aws:states:${REGION}:${ACCOUNT_ID}:stateMachine:${STATE_MACHINE_NAME}"

# 상태 머신 생성 또는 업데이트
if aws stepfunctions describe-state-machine \
    --state-machine-arn "${STATE_MACHINE_ARN}" \
    --region "${REGION}" >/dev/null 2>&1; then
  echo "  -> 상태 머신 업데이트: ${STATE_MACHINE_NAME}"
  aws stepfunctions update-state-machine \
    --state-machine-arn "${STATE_MACHINE_ARN}" \
    --definition "${ASL_RENDERED}" \
    --role-arn "${SFN_ROLE_ARN}" \
    --region "${REGION}"
else
  echo "  -> 상태 머신 생성 (EXPRESS): ${STATE_MACHINE_NAME}"
  aws stepfunctions create-state-machine \
    --name "${STATE_MACHINE_NAME}" \
    --definition "${ASL_RENDERED}" \
    --role-arn "${SFN_ROLE_ARN}" \
    --type EXPRESS \
    --tags "[{\"key\":\"project\",\"value\":\"say2-preproject-6team\"}]" \
    --region "${REGION}"
fi

echo "  -> Step Functions 배포 완료: ${STATE_MACHINE_NAME}"

###############################################################################
# 6. S3 Lifecycle Rule — runs/ 접두사 7일 만료
###############################################################################
echo ""
echo "[6/7] S3 Lifecycle Rule 설정 (runs/ 7일 만료)..."

LIFECYCLE_JSON=$(cat <<'LIFECYCLE_EOF'
{
  "Rules": [
    {
      "ID": "expire-runs-after-7-days",
      "Filter": {
        "Prefix": "runs/"
      },
      "Status": "Enabled",
      "Expiration": {
        "Days": 7
      }
    }
  ]
}
LIFECYCLE_EOF
)

aws s3api put-bucket-lifecycle-configuration \
  --bucket "${S3_BUCKET}" \
  --lifecycle-configuration "${LIFECYCLE_JSON}" \
  --region "${REGION}"

echo "  -> Lifecycle Rule 적용 완료: runs/ 접두사 → 7일 후 삭제"

###############################################################################
# 7. API Gateway + Status Lambda 배포
###############################################################################
echo ""
echo "[7/7] API Gateway + Status Lambda 배포..."

bash "${V2_DIR}/api-gateway/setup-api-gw.sh"

# API URL 읽기
API_URL=""
API_URL_FILE="/tmp/${PROJECT}-api-url.txt"
if [ -f "${API_URL_FILE}" ]; then
  API_URL=$(cat "${API_URL_FILE}")
fi

echo "  -> API Gateway 배포 완료"

###############################################################################
# 완료
###############################################################################
echo ""
echo "============================================================"
echo " 배포 완료!"
echo "============================================================"
echo "  Lambda A       : ${FUNC_LAMBDA_A}"
echo "  Lambda B       : ${FUNC_LAMBDA_B}"
echo "  State Machine  : ${STATE_MACHINE_ARN}"
echo "  S3 Bucket      : ${S3_BUCKET}"
echo "  Lifecycle      : runs/ → 7일 만료"
echo "  API Gateway    : ${API_URL}"
echo "============================================================"
