# Deployment Guide

## Git Repository Setup

### 1. GitHub에 새 레포지토리 생성

1. GitHub에서 새 레포지토리 생성: `emergency-multimodal-orchestrator`
2. 로컬 레포지토리와 연결:

```bash
cd emergency-multimodal-orchestrator

# 원격 저장소 추가
git remote add origin https://github.com/YOUR_USERNAME/emergency-multimodal-orchestrator.git

# 푸시
git push -u origin main
```

### 2. 브랜치 전략

```bash
# 개발 브랜치 생성
git checkout -b develop

# 기능 브랜치 생성
git checkout -b feature/modal-integration
git checkout -b feature/ml-decision-engine

# 푸시
git push -u origin develop
git push -u origin feature/modal-integration
```

## AWS Deployment

### Prerequisites

```bash
# AWS CLI 설정
aws configure

# SAM CLI 설치 확인
sam --version

# Bedrock 모델 접근 권한 확인
aws bedrock list-foundation-models --region us-east-1
```

### Step 1: 로컬 테스트

```bash
# 단위 테스트
python tests/local_test.py

# 전체 워크플로우 시뮬레이션
python tests/full_workflow_simulation.py
```

**예상 결과**:
```
Total: 5/5 tests passed
```

### Step 2: SAM 빌드 및 검증

```bash
# 템플릿 검증
sam validate --lint

# 빌드
sam build

# 로컬 테스트 (선택사항)
sam local invoke CaseInitFunction --event test_request.json
```

### Step 3: AWS 배포

```bash
# 배포 스크립트 실행
chmod +x deploy/scripts/deploy.sh
./deploy/scripts/deploy.sh
```

**또는 수동 배포**:

```bash
sam deploy \
  --stack-name emergency-orchestrator \
  --capabilities CAPABILITY_IAM \
  --region us-east-1 \
  --resolve-s3 \
  --no-fail-on-empty-changeset
```

### Step 4: 엔드포인트 확인

```bash
# API 엔드포인트 확인
aws cloudformation describe-stacks \
  --stack-name emergency-orchestrator \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiEndpoint`].OutputValue' \
  --output text

# 환경변수로 저장
export API_ENDPOINT=$(aws cloudformation describe-stacks \
  --stack-name emergency-orchestrator \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiEndpoint`].OutputValue' \
  --output text)

echo "API Endpoint: $API_ENDPOINT"
```

### Step 5: API 테스트

```bash
# 케이스 생성
curl -X POST $API_ENDPOINT/case \
  -H "Content-Type: application/json" \
  -d @test_request.json

# 응답 예시
{
  "case_id": "a1b2c3d4",
  "status": "processing",
  "execution_arn": "arn:aws:states:...",
  "message": "Case initiated. Use GET /case/{case_id} to check status."
}

# 결과 조회 (몇 초 후)
curl -X GET $API_ENDPOINT/case/a1b2c3d4
```

## Modal Integration

### CXR Modal 연동

```bash
# 1. CXR 서비스 배포 (별도 레포)
cd ../cxr-service
python deploy/scripts/deploy_v2.py

# 2. CXR 엔드포인트 확인
CXR_ENDPOINT=$(aws cloudformation describe-stacks \
  --stack-name cxr-service \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiEndpoint`].OutputValue' \
  --output text)

# 3. 오케스트레이터에 등록
aws ssm put-parameter \
  --name /emergency-orchestrator/cxr-endpoint \
  --value "$CXR_ENDPOINT" \
  --type String \
  --overwrite

# 4. Lambda 재배포 (환경변수 업데이트)
cd ../emergency-multimodal-orchestrator
sam build
sam deploy
```

### ECG Modal 연동

```bash
# 1. ECG 서비스 배포 (FastAPI)
cd ../ecg-svc

# Docker 빌드
docker build -t ecg-service .

# ECR 푸시
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin <account>.dkr.ecr.us-east-1.amazonaws.com

docker tag ecg-service:latest <account>.dkr.ecr.us-east-1.amazonaws.com/ecg-service:latest
docker push <account>.dkr.ecr.us-east-1.amazonaws.com/ecg-service:latest

# ECS/Fargate 배포 (또는 Lambda Container)
# ... (ECS 배포 스크립트)

# 2. ECG 엔드포인트 등록
ECG_ENDPOINT="http://your-ecg-service.com:8000"

aws ssm put-parameter \
  --name /emergency-orchestrator/ecg-endpoint \
  --value "$ECG_ENDPOINT" \
  --type String \
  --overwrite

# 3. Lambda 재배포
cd ../emergency-multimodal-orchestrator
sam build
sam deploy
```

## RAG Setup (Optional)

### MIMIC 데이터 인덱싱

```bash
# 1. MIMIC 데이터 다운로드 (PhysioNet 계정 필요)
# https://physionet.org/content/mimiciv/

# 2. RAG 인덱스 빌드
cd deploy/report_generator/rag

python index_builder.py \
  --mimic-note-path /path/to/mimic-note \
  --mimic-cxr-path /path/to/mimic-cxr \
  --output-dir ./indices

# 3. S3 업로드
RAG_BUCKET=$(aws cloudformation describe-stacks \
  --stack-name emergency-orchestrator \
  --query 'Stacks[0].Outputs[?OutputKey==`RagBucketName`].OutputValue' \
  --output text)

aws s3 cp ./indices/faiss_index.bin s3://$RAG_BUCKET/indices/
aws s3 cp ./indices/documents.json s3://$RAG_BUCKET/indices/
```

## Monitoring

### CloudWatch Logs

```bash
# Case Init Lambda 로그
aws logs tail /aws/lambda/emergency-case-init --follow

# Fusion Decision Lambda 로그
aws logs tail /aws/lambda/emergency-fusion-decision --follow

# Step Functions 실행 로그
aws stepfunctions list-executions \
  --state-machine-arn <STATE_MACHINE_ARN> \
  --max-results 10
```

### CloudWatch Metrics

```bash
# Lambda 실행 시간
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Duration \
  --dimensions Name=FunctionName,Value=emergency-fusion-decision \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-02T00:00:00Z \
  --period 3600 \
  --statistics Average,Maximum

# Step Functions 실행 성공률
aws cloudwatch get-metric-statistics \
  --namespace AWS/States \
  --metric-name ExecutionsFailed \
  --dimensions Name=StateMachineArn,Value=<STATE_MACHINE_ARN> \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-02T00:00:00Z \
  --period 3600 \
  --statistics Sum
```

## Cleanup

### 스택 삭제

```bash
# SAM 스택 삭제
sam delete --stack-name emergency-orchestrator

# 또는 CloudFormation으로
aws cloudformation delete-stack --stack-name emergency-orchestrator

# S3 버킷 비우기 (필요 시)
aws s3 rm s3://emergency-orchestrator-cases-<account-id> --recursive
aws s3 rm s3://emergency-orchestrator-rag-<account-id> --recursive
```

### SSM 파라미터 삭제

```bash
aws ssm delete-parameter --name /emergency-orchestrator/cxr-endpoint
aws ssm delete-parameter --name /emergency-orchestrator/ecg-endpoint
```

## Troubleshooting

### Lambda Timeout

**증상**: Lambda 함수가 타임아웃

**해결**:
```yaml
# template.yaml
FusionDecisionFunction:
  Properties:
    Timeout: 60  # 기본 60초에서 증가
```

### Bedrock 접근 권한 오류

**증상**: `AccessDeniedException: User is not authorized to perform: bedrock:InvokeModel`

**해결**:
```bash
# IAM 정책 확인
aws iam get-role-policy \
  --role-name emergency-orchestrator-BedrockReasoningFunctionRole-xxx \
  --policy-name BedrockPolicy

# 필요 시 정책 추가
```

### Step Functions 실행 실패

**증상**: Step Functions 실행이 실패

**해결**:
```bash
# 실행 히스토리 확인
aws stepfunctions get-execution-history \
  --execution-arn <EXECUTION_ARN> \
  --max-results 100

# 특정 단계 로그 확인
aws logs filter-log-events \
  --log-group-name /aws/lambda/emergency-fusion-decision \
  --start-time <timestamp>
```

### CXR/ECG Modal 연결 실패

**증상**: Modal connector에서 연결 오류

**해결**:
1. SSM 파라미터 확인:
```bash
aws ssm get-parameter --name /emergency-orchestrator/cxr-endpoint
```

2. 네트워크 연결 확인 (VPC 설정 필요 시)
3. API 엔드포인트 접근 가능 여부 확인

## Performance Optimization

### Lambda 동시성 설정

```bash
# 예약된 동시성 설정
aws lambda put-function-concurrency \
  --function-name emergency-fusion-decision \
  --reserved-concurrent-executions 10
```

### Step Functions Express Workflow

고빈도 실행 시 Express Workflow 고려:

```yaml
# template.yaml
OrchestrationStateMachine:
  Type: AWS::Serverless::StateMachine
  Properties:
    Type: EXPRESS  # Standard → Express
    Logging:
      Level: ALL
      IncludeExecutionData: true
```

## Security Best Practices

### 1. API Gateway 인증 추가

```yaml
# template.yaml
EmergencyApi:
  Type: AWS::Serverless::Api
  Properties:
    Auth:
      DefaultAuthorizer: AWS_IAM
      InvokeRole: CALLER_CREDENTIALS
```

### 2. S3 버킷 암호화

```yaml
CaseBucket:
  Type: AWS::S3::Bucket
  Properties:
    BucketEncryption:
      ServerSideEncryptionConfiguration:
        - ServerSideEncryptionByDefault:
            SSEAlgorithm: AES256
```

### 3. VPC 내 Lambda 배포

```yaml
FusionDecisionFunction:
  Properties:
    VpcConfig:
      SecurityGroupIds:
        - !Ref LambdaSecurityGroup
      SubnetIds:
        - !Ref PrivateSubnet1
        - !Ref PrivateSubnet2
```

## Next Steps

1. ✅ 로컬 테스트 완료
2. ✅ AWS 배포 완료
3. 🔄 CXR Modal 연동
4. 🔄 ECG Modal 연동
5. 📋 RAG 인덱스 구축
6. 📋 프로덕션 모니터링 설정
7. 📋 ML 모델 학습 및 교체

자세한 내용은 각 문서 참조:
- [ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [MODAL_INTEGRATION_CXR_ECG.md](docs/MODAL_INTEGRATION_CXR_ECG.md)
- [UPGRADE_GUIDE.md](docs/UPGRADE_GUIDE.md)
