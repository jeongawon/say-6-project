"""
Layer 6 Bedrock Report — 설정
"""
import os


class Config:
    REGION = os.environ.get("AWS_REGION", "ap-northeast-2")

    # Sonnet 4.6 단일 모델 (라우팅 없음)
    # 서울 리전에서 inference profile 사용
    MODEL_ID = os.environ.get(
        "BEDROCK_MODEL_ID",
        "global.anthropic.claude-sonnet-4-6"
    )

    # 소견서 생성 설정
    MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "4096"))
    TEMPERATURE = float(os.environ.get("TEMPERATURE", "0.2"))

    # 재시도 설정
    RETRY_COUNT = 1
    RETRY_TEMPERATURE = 0.0
