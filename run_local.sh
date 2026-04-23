#!/bin/bash
# ecg-svc 로컬 실행 (Docker)
# AWS 자격증명은 ~/.aws 마운트, 신호 파일은 processed/ 마운트

docker run --rm -d \
  --name ecg-svc \
  -p 8000:8000 \
  -v ~/.aws:/root/.aws:ro \
  -v "$(pwd)/processed":/data:ro \
  -e AWS_DEFAULT_REGION=ap-northeast-2 \
  -e S3_BUCKET=say2-6team \
  -e S3_MODEL_KEY=mimic/ecg/ecg_s6.onnx \
  -e S3_DATA_KEY=mimic/ecg/ecg_s6.onnx.data \
  -e MODEL_DIR=/tmp/models \
  ecg-modal:latest

echo "컨테이너 시작 중..."
echo "로그: docker logs -f ecg-svc"
echo "종료: docker stop ecg-svc"

# readiness 대기 (최대 90초)
for i in $(seq 1 18); do
  sleep 5
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/ready 2>/dev/null)
  if [ "$STATUS" = "200" ]; then
    echo "✅ 서비스 준비 완료 (http://localhost:8000)"
    exit 0
  fi
  echo "  대기 중... ($((i*5))s)"
done

echo "⚠️  90초 내 ready 응답 없음 — docker logs -f ecg-svc 확인"
