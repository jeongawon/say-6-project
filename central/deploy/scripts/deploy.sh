#!/bin/bash

# Emergency Multimodal Orchestrator Deployment Script

set -e

echo "=========================================="
echo "Emergency Multimodal Orchestrator Deploy"
echo "=========================================="

# Check prerequisites
echo "Checking prerequisites..."

if ! command -v sam &> /dev/null; then
    echo "ERROR: AWS SAM CLI not found. Please install: pip install aws-sam-cli"
    exit 1
fi

if ! command -v aws &> /dev/null; then
    echo "ERROR: AWS CLI not found. Please install AWS CLI"
    exit 1
fi

# Check AWS credentials
if ! aws sts get-caller-identity &> /dev/null; then
    echo "ERROR: AWS credentials not configured"
    exit 1
fi

echo "Prerequisites OK"

# Get AWS account ID and region
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=$(aws configure get region)
REGION=${REGION:-us-east-1}

echo "Account ID: $ACCOUNT_ID"
echo "Region: $REGION"

# Validate template
echo ""
echo "Validating SAM template..."
sam validate --lint

# Build
echo ""
echo "Building SAM application..."
sam build

# Deploy
echo ""
echo "Deploying to AWS..."
sam deploy \
    --stack-name emergency-orchestrator \
    --capabilities CAPABILITY_IAM \
    --region $REGION \
    --resolve-s3 \
    --no-fail-on-empty-changeset

# Get outputs
echo ""
echo "=========================================="
echo "Deployment Complete!"
echo "=========================================="
echo ""

API_ENDPOINT=$(aws cloudformation describe-stacks \
    --stack-name emergency-orchestrator \
    --query 'Stacks[0].Outputs[?OutputKey==`ApiEndpoint`].OutputValue' \
    --output text \
    --region $REGION)

CASE_BUCKET=$(aws cloudformation describe-stacks \
    --stack-name emergency-orchestrator \
    --query 'Stacks[0].Outputs[?OutputKey==`CaseBucketName`].OutputValue' \
    --output text \
    --region $REGION)

STATE_MACHINE=$(aws cloudformation describe-stacks \
    --stack-name emergency-orchestrator \
    --query 'Stacks[0].Outputs[?OutputKey==`StateMachineArn`].OutputValue' \
    --output text \
    --region $REGION)

echo "API Endpoint: $API_ENDPOINT"
echo "Case Bucket: $CASE_BUCKET"
echo "State Machine: $STATE_MACHINE"
echo ""
echo "Test with:"
echo "curl -X POST $API_ENDPOINT/case -H 'Content-Type: application/json' -d @test_request.json"
echo ""
echo "=========================================="
