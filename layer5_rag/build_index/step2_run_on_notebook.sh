#!/bin/bash
set -e

BUCKET="pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an"
NOTEBOOK_NAME="rag-embedding-runner"
REGION="ap-northeast-2"
LOG="/home/ec2-user/SageMaker/embedding.log"

echo "=== RAG Embedding Start ===" | tee $LOG

# 1. pip install
echo "Installing sentence-transformers..." | tee -a $LOG
pip install sentence-transformers >> $LOG 2>&1
echo "Install done" | tee -a $LOG

# 2. Download data
echo "Downloading reports.jsonl..." | tee -a $LOG
aws s3 cp s3://$BUCKET/rag/build/reports.jsonl /tmp/reports.jsonl >> $LOG 2>&1
echo "Download done" | tee -a $LOG

# 3. Run embedding
echo "Running embedding..." | tee -a $LOG
python3 /tmp/step2_gpu_embed.py >> $LOG 2>&1
echo "Embedding done" | tee -a $LOG

# 4. Upload results
echo "Uploading to S3..." | tee -a $LOG
aws s3 cp /tmp/embeddings.npy s3://$BUCKET/rag/build/output/embeddings.npy >> $LOG 2>&1
aws s3 cp /tmp/metadata.jsonl s3://$BUCKET/rag/build/output/metadata.jsonl >> $LOG 2>&1
echo "Upload done" | tee -a $LOG

# 5. Done marker
echo "done" | aws s3 cp - s3://$BUCKET/rag/build/output/DONE >> $LOG 2>&1
echo "=== ALL DONE ===" | tee -a $LOG

# 6. Stop instance
aws sagemaker stop-notebook-instance --notebook-instance-name $NOTEBOOK_NAME --region $REGION >> $LOG 2>&1
