"""
통합 오케스트레이터 Lambda 핸들러

GET  -> 테스트 페이지 (index.html)
POST -> 통합 파이프라인 API

POST actions:
  - "run"             -> 전체 파이프라인 실행 (기본)
  - "list_test_cases" -> 5개 테스트 케이스 목록 반환
  - "test_case"       -> 특정 테스트 케이스로 파이프라인 실행
"""
import os
import json
import base64
import traceback

import boto3

from orchestrator import ChestModalOrchestrator
from input_parser import parse_input
from output_formatter import OutputFormatter
from test_cases import TEST_CASES
import config

# 글로벌 싱글턴
orchestrator = ChestModalOrchestrator()
s3_client = boto3.client("s3", region_name="ap-northeast-2")


def serve_html():
    """테스트 페이지 HTML 반환"""
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "text/html; charset=utf-8"},
        "body": html,
    }


def _ok(data):
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
        "body": json.dumps(data, ensure_ascii=False, default=str),
    }


def _error(code, message, **kwargs):
    body = {"error": message}
    body.update(kwargs)
    return {
        "statusCode": code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, ensure_ascii=False),
    }


def _load_s3_image(s3_key: str) -> str:
    """S3에서 이미지 로드 → base64 인코딩"""
    resp = s3_client.get_object(Bucket=config.WORK_BUCKET, Key=s3_key)
    image_bytes = resp["Body"].read()
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


def handler(event, context):
    """Lambda 핸들러"""
    method = event.get("requestContext", {}).get("http", {}).get("method", "POST")

    # OPTIONS (CORS preflight)
    if method == "OPTIONS":
        return {
            "statusCode": 200,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            },
            "body": "",
        }

    # GET → 테스트 페이지
    if method == "GET":
        return serve_html()

    # POST → API
    try:
        body = event
        if isinstance(event.get("body"), str):
            body = json.loads(event["body"])
        elif isinstance(event.get("body"), dict):
            body = event["body"]

        action = body.get("action", "run")

        # ---- Presigned URL 생성 ----
        if action == "presigned_url":
            s3_key = body.get("s3_key", "")
            if not s3_key:
                return _error(400, "s3_key is required")
            url = s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": config.WORK_BUCKET, "Key": s3_key},
                ExpiresIn=300,
            )
            return _ok({"url": url, "s3_key": s3_key})

        # ---- 테스트 케이스 목록 ----
        if action == "list_test_cases":
            cases = {}
            for k, v in TEST_CASES.items():
                cases[k] = {
                    "name": v["name"],
                    "description": v["description"],
                    "expected_risk": v["expected_risk"],
                }
            return _ok({"test_cases": cases})

        # ---- 테스트 케이스 실행 ----
        if action == "test_case":
            case_id = body.get("test_case", "chf")
            if case_id not in TEST_CASES:
                return _error(400, f"Unknown test case: {case_id}",
                              available=list(TEST_CASES.keys()))

            tc = TEST_CASES[case_id]
            # S3에서 이미지 로드
            image_b64 = _load_s3_image(tc["s3_key"])

            run_body = {
                "image_base64": image_b64,
                "patient_info": tc["patient_info"],
                "prior_results": tc.get("prior_results", []),
                "options": body.get("options", {}),
            }
            parsed = parse_input(run_body)
            result = orchestrator.run(parsed)
            result["test_case"] = {
                "id": case_id,
                "name": tc["name"],
                "expected_risk": tc["expected_risk"],
            }
            return _ok(result)

        # ---- 전체 파이프라인 실행 (기본) ----
        if action == "run":
            parsed = parse_input(body)
            result = orchestrator.run(parsed)
            fmt = body.get("format", "default")
            if fmt == "summary":
                result = OutputFormatter.summary_only(result)
            return _ok(result)

        return _error(400, f"Unknown action: {action}",
                      available=["run", "list_test_cases", "test_case"])

    except ValueError as e:
        return _error(400, str(e))
    except Exception as e:
        print(traceback.format_exc())
        return _error(500, str(e))
