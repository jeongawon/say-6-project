#!/bin/bash
# Dr. AI Radiologist v2 — API Gateway + Gateway Lambda 설정 스크립트
# Lambda Proxy 통합 사용 — IAM 역할 생성 불필요 (기존 역할 재사용)
# chmod +x deploy/v2/api-gateway/setup-api-gw.sh
set -euo pipefail

###############################################################################
# 변수 설정
###############################################################################
ACCOUNT_ID="666803869796"
REGION="ap-northeast-2"
PROJECT="dr-ai-radiologist"
GATEWAY_LAMBDA_NAME="${PROJECT}-v2-gateway"
API_NAME="${PROJECT}-v2-api"
STAGE="test"
S3_BUCKET="pre-project-practice-hyunwoo-${ACCOUNT_ID}-${REGION}-an"
STATE_MACHINE_ARN="arn:aws:states:${REGION}:${ACCOUNT_ID}:stateMachine:${PROJECT}-pipeline-v2"

# 기존 v1 역할 재사용 (IAM 생성 권한 없음)
LAMBDA_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/say-2-lambda-bedrock-role"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LAMBDA_SRC_DIR="${SCRIPT_DIR}/status-lambda"

echo "============================================================"
echo " API Gateway + Gateway Lambda 배포"
echo " (Lambda Proxy 통합 — IAM 생성 불필요)"
echo "============================================================"

###############################################################################
# 1. Gateway Lambda 패키징 + 배포
###############################################################################
echo ""
echo "[1/5] Gateway Lambda 패키징 + 배포..."

TMPZIP="/tmp/${GATEWAY_LAMBDA_NAME}.zip"
rm -f "${TMPZIP}"
cd "${LAMBDA_SRC_DIR}"
zip -j "${TMPZIP}" status_handler.py
cd - >/dev/null

if aws lambda get-function --function-name "${GATEWAY_LAMBDA_NAME}" --region "${REGION}" >/dev/null 2>&1; then
  echo "  -> Lambda 업데이트: ${GATEWAY_LAMBDA_NAME}"
  aws lambda update-function-code \
    --function-name "${GATEWAY_LAMBDA_NAME}" \
    --zip-file "fileb://${TMPZIP}" \
    --region "${REGION}" >/dev/null

  # 업데이트 완료 대기
  aws lambda wait function-updated --function-name "${GATEWAY_LAMBDA_NAME}" --region "${REGION}" 2>/dev/null || sleep 5

  aws lambda update-function-configuration \
    --function-name "${GATEWAY_LAMBDA_NAME}" \
    --environment "Variables={S3_BUCKET=${S3_BUCKET},STATE_MACHINE_ARN=${STATE_MACHINE_ARN}}" \
    --timeout 30 \
    --memory-size 256 \
    --region "${REGION}" >/dev/null
else
  echo "  -> Lambda 생성: ${GATEWAY_LAMBDA_NAME}"
  aws lambda create-function \
    --function-name "${GATEWAY_LAMBDA_NAME}" \
    --runtime python3.12 \
    --handler status_handler.lambda_handler \
    --role "${LAMBDA_ROLE_ARN}" \
    --zip-file "fileb://${TMPZIP}" \
    --timeout 30 \
    --memory-size 256 \
    --environment "Variables={S3_BUCKET=${S3_BUCKET},STATE_MACHINE_ARN=${STATE_MACHINE_ARN}}" \
    --tags "project=say2-preproject-6team" \
    --region "${REGION}" >/dev/null

  echo "  -> Lambda 생성 대기..."
  aws lambda wait function-active --function-name "${GATEWAY_LAMBDA_NAME}" --region "${REGION}" 2>/dev/null || sleep 5
fi

GATEWAY_LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${GATEWAY_LAMBDA_NAME}"
echo "  -> Gateway Lambda ARN: ${GATEWAY_LAMBDA_ARN}"

###############################################################################
# 2. REST API 생성 (기존이면 재사용)
###############################################################################
echo ""
echo "[2/5] REST API 생성..."

EXISTING_API_ID=$(aws apigateway get-rest-apis --region "${REGION}" \
  --query "items[?name=='${API_NAME}'].id | [0]" --output text 2>/dev/null || true)

if [ -n "${EXISTING_API_ID}" ] && [ "${EXISTING_API_ID}" != "None" ]; then
  API_ID="${EXISTING_API_ID}"
  echo "  -> 기존 API 재사용: ${API_ID}"
else
  API_ID=$(aws apigateway create-rest-api \
    --name "${API_NAME}" \
    --description "Dr. AI Radiologist v2 API (Async Polling, Lambda Proxy)" \
    --endpoint-configuration types=REGIONAL \
    --region "${REGION}" \
    --query 'id' --output text)
  echo "  -> API 생성 완료: ${API_ID}"
fi

ROOT_ID=$(aws apigateway get-resources --rest-api-id "${API_ID}" --region "${REGION}" \
  --query "items[?path=='/'].id" --output text)

echo "  -> API ID: ${API_ID}, Root: ${ROOT_ID}"

###############################################################################
# 3. 리소스 생성 + 메서드 설정
###############################################################################
echo ""
echo "[3/5] 리소스 + 메서드 설정..."

# /analyze 리소스
ANALYZE_ID=$(aws apigateway get-resources --rest-api-id "${API_ID}" --region "${REGION}" \
  --query "items[?path=='/analyze'].id" --output text 2>/dev/null || true)

if [ -z "${ANALYZE_ID}" ] || [ "${ANALYZE_ID}" == "None" ]; then
  ANALYZE_ID=$(aws apigateway create-resource \
    --rest-api-id "${API_ID}" --parent-id "${ROOT_ID}" --path-part "analyze" \
    --region "${REGION}" --query 'id' --output text)
  echo "  -> /analyze 생성: ${ANALYZE_ID}"
else
  echo "  -> /analyze 존재: ${ANALYZE_ID}"
fi

# /analyze/status 리소스
STATUS_ID=$(aws apigateway get-resources --rest-api-id "${API_ID}" --region "${REGION}" \
  --query "items[?path=='/analyze/status'].id" --output text 2>/dev/null || true)

if [ -z "${STATUS_ID}" ] || [ "${STATUS_ID}" == "None" ]; then
  STATUS_ID=$(aws apigateway create-resource \
    --rest-api-id "${API_ID}" --parent-id "${ANALYZE_ID}" --path-part "status" \
    --region "${REGION}" --query 'id' --output text)
  echo "  -> /analyze/status 생성: ${STATUS_ID}"
else
  echo "  -> /analyze/status 존재: ${STATUS_ID}"
fi

# ── Helper: Lambda Proxy 메서드 설정 ──
setup_lambda_proxy() {
  local RESOURCE_ID=$1
  local HTTP_METHOD=$2
  local RESOURCE_PATH=$3

  aws apigateway delete-method \
    --rest-api-id "${API_ID}" --resource-id "${RESOURCE_ID}" \
    --http-method "${HTTP_METHOD}" --region "${REGION}" >/dev/null 2>&1 || true

  aws apigateway put-method \
    --rest-api-id "${API_ID}" --resource-id "${RESOURCE_ID}" \
    --http-method "${HTTP_METHOD}" --authorization-type NONE \
    --region "${REGION}" >/dev/null

  aws apigateway put-integration \
    --rest-api-id "${API_ID}" --resource-id "${RESOURCE_ID}" \
    --http-method "${HTTP_METHOD}" --type AWS_PROXY \
    --integration-http-method POST \
    --uri "arn:aws:apigateway:${REGION}:lambda:path/2015-03-31/functions/${GATEWAY_LAMBDA_ARN}/invocations" \
    --region "${REGION}" >/dev/null

  echo "  -> ${HTTP_METHOD} ${RESOURCE_PATH} → Lambda Proxy"
}

# ── Helper: OPTIONS CORS Mock ──
setup_options() {
  local RESOURCE_ID=$1
  local RESOURCE_PATH=$2

  aws apigateway delete-method \
    --rest-api-id "${API_ID}" --resource-id "${RESOURCE_ID}" \
    --http-method OPTIONS --region "${REGION}" >/dev/null 2>&1 || true

  aws apigateway put-method \
    --rest-api-id "${API_ID}" --resource-id "${RESOURCE_ID}" \
    --http-method OPTIONS --authorization-type NONE \
    --region "${REGION}" >/dev/null

  aws apigateway put-integration \
    --rest-api-id "${API_ID}" --resource-id "${RESOURCE_ID}" \
    --http-method OPTIONS --type MOCK \
    --request-templates '{"application/json": "{\"statusCode\": 200}"}' \
    --region "${REGION}" >/dev/null

  aws apigateway put-method-response \
    --rest-api-id "${API_ID}" --resource-id "${RESOURCE_ID}" \
    --http-method OPTIONS --status-code "200" \
    --response-parameters '{
      "method.response.header.Access-Control-Allow-Origin": false,
      "method.response.header.Access-Control-Allow-Methods": false,
      "method.response.header.Access-Control-Allow-Headers": false
    }' \
    --response-models '{"application/json": "Empty"}' \
    --region "${REGION}" >/dev/null

  aws apigateway put-integration-response \
    --rest-api-id "${API_ID}" --resource-id "${RESOURCE_ID}" \
    --http-method OPTIONS --status-code "200" \
    --response-parameters '{
      "method.response.header.Access-Control-Allow-Origin": "'"'"'*'"'"'",
      "method.response.header.Access-Control-Allow-Methods": "'"'"'POST,GET,OPTIONS'"'"'",
      "method.response.header.Access-Control-Allow-Headers": "'"'"'Content-Type'"'"'"
    }' \
    --response-templates '{"application/json": ""}' \
    --region "${REGION}" >/dev/null

  echo "  -> OPTIONS ${RESOURCE_PATH} (CORS Mock)"
}

# POST /analyze → Lambda Proxy
setup_lambda_proxy "${ANALYZE_ID}" "POST" "/analyze"

# GET /analyze/status → Lambda Proxy
setup_lambda_proxy "${STATUS_ID}" "GET" "/analyze/status"

# OPTIONS CORS
setup_options "${ANALYZE_ID}" "/analyze"
setup_options "${STATUS_ID}" "/analyze/status"

###############################################################################
# 4. Lambda 호출 권한 부여 (API Gateway → Lambda)
###############################################################################
echo ""
echo "[4/5] Lambda 호출 권한 부여..."

TIMESTAMP=$(date +%s)

aws lambda add-permission \
  --function-name "${GATEWAY_LAMBDA_NAME}" \
  --statement-id "apigw-post-analyze-${TIMESTAMP}" \
  --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:${REGION}:${ACCOUNT_ID}:${API_ID}/*/POST/analyze" \
  --region "${REGION}" >/dev/null 2>&1 || true

aws lambda add-permission \
  --function-name "${GATEWAY_LAMBDA_NAME}" \
  --statement-id "apigw-get-status-${TIMESTAMP}" \
  --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:${REGION}:${ACCOUNT_ID}:${API_ID}/*/GET/analyze/status" \
  --region "${REGION}" >/dev/null 2>&1 || true

echo "  -> Lambda 호출 권한 설정 완료"

###############################################################################
# 5. 스테이지 배포
###############################################################################
echo ""
echo "[5/5] API 배포 → 스테이지: ${STAGE}..."

aws apigateway create-deployment \
  --rest-api-id "${API_ID}" \
  --stage-name "${STAGE}" \
  --description "v2 deployment $(date +%Y%m%d-%H%M%S)" \
  --region "${REGION}" >/dev/null

API_URL="https://${API_ID}.execute-api.${REGION}.amazonaws.com/${STAGE}"

echo ""
echo "============================================================"
echo " API Gateway 배포 완료!"
echo "============================================================"
echo "  API ID       : ${API_ID}"
echo "  Stage        : ${STAGE}"
echo "  API URL      : ${API_URL}"
echo ""
echo "  POST ${API_URL}/analyze"
echo "       -> StartExecution (async)"
echo ""
echo "  GET  ${API_URL}/analyze/status?id={executionArn}"
echo "       -> DescribeExecution + S3 결과 수집"
echo "============================================================"

echo "${API_URL}" > "/tmp/${PROJECT}-api-url.txt"
