"""
DenseNet-121 성능평가 — SageMaker 노트북에서 이 파일 하나만 실행하면 됨.
Training Job 제출 → 완료 대기 → 결과 자동 출력.
"""
import time
import json
import boto3
import sagemaker
from sagemaker.pytorch import PyTorch

WORK_BUCKET = 'pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an'

# SageMaker 세션
sm_session = sagemaker.Session()
role = sagemaker.get_execution_role()

# 평가 스크립트 S3에서 로컬로
s3 = boto3.client('s3')
s3.download_file(WORK_BUCKET, 'scripts/eval_densenet.py', '/tmp/eval_densenet.py')

# Training Job으로 평가 실행 (CPU, 저비용)
estimator = PyTorch(
    entry_point='/tmp/eval_densenet.py',
    role=role,
    instance_count=1,
    instance_type='ml.m5.xlarge',
    framework_version='2.1.0',
    py_version='py310',
    volume_size=50,
    max_run=3600,
    hyperparameters={
        'batch-size': 64,
        'num-workers': 4,
    },
    output_path=f's3://{WORK_BUCKET}/output',
    base_job_name='densenet121-eval',
    tags=[{'Key': 'project', 'Value': 'pre-project-6team'}],
)

print("평가 Job 제출 중...")
estimator.fit(wait=True)

# 결과 다운로드
import tarfile, os
job_name = estimator.latest_training_job.name
output_path = f'output/{job_name}/output/model.tar.gz'
local_tar = '/tmp/eval_output.tar.gz'
s3.download_file(WORK_BUCKET, output_path, local_tar)

extract_dir = '/tmp/eval_results'
os.makedirs(extract_dir, exist_ok=True)
with tarfile.open(local_tar, 'r:gz') as tar:
    tar.extractall(extract_dir)

# 리포트 출력
report_path = os.path.join(extract_dir, 'eval_report.txt')
if os.path.exists(report_path):
    with open(report_path, 'r') as f:
        print(f.read())

results_path = os.path.join(extract_dir, 'eval_results.json')
if os.path.exists(results_path):
    with open(results_path, 'r') as f:
        results = json.load(f)
    # S3에도 JSON 직접 업로드 (쉽게 접근)
    s3.upload_file(results_path, WORK_BUCKET, 'output/densenet121-eval/eval_results.json')
    s3.upload_file(report_path, WORK_BUCKET, 'output/densenet121-eval/eval_report.txt')
    print(f"\n결과 저장: s3://{WORK_BUCKET}/output/densenet121-eval/")
