#!/bin/bash
# ECG 모달 EKS 배포 스크립트

ACCOUNT_ID=905418313170
REGION=ap-northeast-2
ECR_REPO=ecg-modal
IMAGE_TAG=latest
ECR_URI=$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$ECR_REPO:$IMAGE_TAG

echo "=== 1. ECR 로그인 ==="
aws ecr get-login-password --region $REGION | \
  docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com

echo "=== 2. ECR 레포지토리 생성 (없으면) ==="
aws ecr create-repository --repository-name $ECR_REPO --region $REGION 2>/dev/null || true

echo "=== 3. Docker 이미지 빌드 ==="
docker build -t $ECR_REPO:$IMAGE_TAG ./ecg-svc

echo "=== 4. ECR 푸시 ==="
docker tag $ECR_REPO:$IMAGE_TAG $ECR_URI
docker push $ECR_URI

echo "=== 5. EKS 배포 ==="
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/ingress.yaml

echo "=== 6. 배포 상태 확인 ==="
kubectl rollout status deployment/ecg-modal

echo "=== 완료 ==="
kubectl get pods -l app=ecg-modal
kubectl get service ecg-modal-service
