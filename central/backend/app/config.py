"""Application configuration — environment variables."""
import os


# FHIR Server
FHIR_BASE_URL = os.getenv("FHIR_BASE_URL", "http://localhost:8080/fhir")

# AWS
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.getenv(
    "BEDROCK_MODEL_ID",
    "anthropic.claude-3-5-sonnet-20241022-v2:0",
)

# SageMaker endpoints (모달별)
SAGEMAKER_CXR_ENDPOINT = os.getenv("SAGEMAKER_CXR_ENDPOINT", "")
SAGEMAKER_ECG_ENDPOINT = os.getenv("SAGEMAKER_ECG_ENDPOINT", "")

# S3
S3_ASSET_BUCKET = os.getenv("S3_ASSET_BUCKET", "dr-ai-assets")

# App
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "8000"))
