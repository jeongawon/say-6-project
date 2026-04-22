"""SageMaker endpoint 호출 클라이언트."""
from __future__ import annotations

import json
import logging
import boto3

from app.config import AWS_REGION

logger = logging.getLogger(__name__)

_sm_runtime = None


def _get_client():
    global _sm_runtime
    if _sm_runtime is None:
        _sm_runtime = boto3.client("sagemaker-runtime", region_name=AWS_REGION)
    return _sm_runtime


def invoke_endpoint(endpoint_name: str, payload: dict) -> dict:
    """SageMaker endpoint 호출 후 결과 반환."""
    client = _get_client()
    resp = client.invoke_endpoint(
        EndpointName=endpoint_name,
        ContentType="application/json",
        Body=json.dumps(payload),
    )
    return json.loads(resp["Body"].read())
