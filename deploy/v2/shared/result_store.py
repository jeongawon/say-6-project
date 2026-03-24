"""
Claim-Check 패턴: Lambda 결과를 S3에 JSON으로 저장하고 URI만 반환.
Step Functions의 256KB 페이로드 제한을 우회.

인터페이스를 추상화하여 나중에 DynamoDB로 교체 가능.
"""

import json
import boto3
from abc import ABC, abstractmethod


class ResultStoreBase(ABC):
    """저장소 인터페이스 — 구현체만 교체하면 S3↔DynamoDB 전환 가능"""

    @abstractmethod
    def save(self, run_id: str, stage: str, data: dict) -> str:
        """결과 저장 후 URI 반환"""
        pass

    @abstractmethod
    def load(self, uri: str) -> dict:
        """URI에서 결과 로드"""
        pass


class S3ResultStore(ResultStoreBase):
    """S3 JSON 기반 구현"""

    def __init__(self, bucket: str, prefix: str = "runs/"):
        self.s3 = boto3.client("s3")
        self.bucket = bucket
        self.prefix = prefix

    def save(self, run_id: str, stage: str, data: dict) -> str:
        key = f"{self.prefix}{run_id}/{stage}.json"
        self.s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=json.dumps(data, ensure_ascii=False, default=str),
            ContentType="application/json",
        )
        uri = f"s3://{self.bucket}/{key}"
        print(f"[ResultStore] 저장: {uri} ({len(json.dumps(data)) / 1024:.1f}KB)")
        return uri

    def load(self, uri: str) -> dict:
        # "s3://bucket/key" 파싱
        parts = uri.replace("s3://", "").split("/", 1)
        bucket = parts[0]
        key = parts[1]

        obj = self.s3.get_object(Bucket=bucket, Key=key)
        data = json.loads(obj["Body"].read())
        print(f"[ResultStore] 로드: {uri}")
        return data


def get_result_store(config) -> ResultStoreBase:
    """현재는 S3, 나중에 환경변수로 DynamoDB 전환 가능"""
    return S3ResultStore(bucket=config.S3_BUCKET, prefix=config.RESULT_PREFIX)
