"""Bedrock Agent 클라이언트 — Claude 호출 래퍼."""
from __future__ import annotations

import json
import logging
import boto3

from app.config import AWS_REGION, BEDROCK_MODEL_ID

logger = logging.getLogger(__name__)

_bedrock = None


def _get_client():
    global _bedrock
    if _bedrock is None:
        _bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    return _bedrock


def invoke(prompt: str, max_tokens: int = 1000, temperature: float = 0.3) -> str:
    """Bedrock Claude 호출 후 텍스트 반환."""
    client = _get_client()
    resp = client.invoke_model(
        modelId=BEDROCK_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }),
    )
    result = json.loads(resp["body"].read())
    return result["content"][0]["text"]
