"""
SageMaker endpoint 호출 클라이언트.

[이 파일이 하는 일]
K8s에 떠있는 ECG/CXR 모달 서비스를 호출할 때 씀.
config.py에 설정된 endpoint로 요청을 보내고 결과를 받아옴.

[사용처]
orders.py에서 의사가 승인하면 이 파일을 통해 모달 서비스 호출.
endpoint가 설정 안 돼있으면 orders.py에서 mock 결과를 대신 사용.
"""
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
