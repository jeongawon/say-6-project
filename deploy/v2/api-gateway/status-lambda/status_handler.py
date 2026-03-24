"""
v2 Gateway Lambda — HTTP Direct (No S3 Write, No Step Functions).

모든 데이터를 HTTP 본문으로 전달. S3 쓰기 권한 불필요.
Gateway → Lambda A (Function URL, HTTP POST) × 4 호출
       → Lambda B (Function URL, HTTP POST) × 1 호출
       → 결과 조합 → 클라이언트 반환
"""

import json
import os
import traceback
import uuid
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import Request, urlopen
from urllib.error import HTTPError


LAMBDA_A_URL = os.environ.get(
    "LAMBDA_A_URL",
    "https://743w34pu4utb4m65aeixbwofxy0oqeqs.lambda-url.ap-northeast-2.on.aws/",
)
LAMBDA_B_URL = os.environ.get(
    "LAMBDA_B_URL",
    "https://yrier5hngki7h5boz6mennjbcu0psnyq.lambda-url.ap-northeast-2.on.aws/",
)
S3_BUCKET = os.environ.get(
    "S3_BUCKET",
    "pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an",
)


def lambda_handler(event, context):
    # Function URL 이벤트 파싱
    if "requestContext" in event and "http" in event.get("requestContext", {}):
        rc = event["requestContext"]["http"]
        method = rc.get("method", "")
        path = rc.get("path", "")
        body = event.get("body", "{}")
        if event.get("isBase64Encoded"):
            import base64
            body = base64.b64decode(body).decode()
    else:
        method = event.get("httpMethod", "")
        path = event.get("path", "")
        body = event.get("body", "{}")

    try:
        if method == "POST":
            return _handle_analyze(body)
        if method == "OPTIONS":
            return _response(200, {"message": "OK"})
        if method == "GET":
            return _response(200, {"service": "Dr. AI Radiologist v2", "usage": "POST with {image_base64, patient_info}"})
        return _response(400, {"error": f"Unsupported: {method} {path}"})
    except Exception as e:
        print(f"[Gateway] Error: {traceback.format_exc()}")
        return _response(500, {"error": str(e)})


def _handle_analyze(body_str):
    body = json.loads(body_str) if isinstance(body_str, str) else body_str
    run_id = f"v2-{uuid.uuid4().hex[:12]}"
    start_time = time.time()
    print(f"[Pipeline] 시작: run_id={run_id}")

    # ── 0. s3_key → image_base64 변환 (테스트 케이스용) ──
    image_b64_input = body.get("image_base64", "")
    if not image_b64_input and body.get("s3_key"):
        import boto3, base64
        s3 = boto3.client("s3")
        print(f"[Pipeline] S3 이미지 로드: {body['s3_key']}")
        obj = s3.get_object(Bucket=S3_BUCKET, Key=body["s3_key"])
        image_b64_input = base64.b64encode(obj["Body"].read()).decode()

    # ── 1. Preprocess ──
    print("[Pipeline] Step 1: Preprocess")
    pp = _http_post(LAMBDA_A_URL, {
        "task": "preprocess",
        "image_base64": image_b64_input,
        "patient_info": body.get("patient_info", {}),
        "run_id": run_id,
    })
    if pp.get("status") != "ok":
        raise RuntimeError(f"Preprocess failed: {pp.get('message', str(pp)[:300])}")

    image_b64 = pp["image_base64"]  # 정규화된 PNG base64
    patient_info = pp.get("patient_info", body.get("patient_info", {}))

    # ── 2. Parallel Inference (seg, densenet, yolo) ──
    print("[Pipeline] Step 2: Parallel Inference")
    inference = {}

    def run_task(task):
        return task, _http_post(LAMBDA_A_URL, {
            "task": task, "image_base64": image_b64, "run_id": run_id,
        })

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(run_task, t) for t in ["seg", "densenet", "yolo"]]
        for f in as_completed(futures):
            task, result = f.result()
            inference[task] = result
            print(f"[Pipeline]   {task}: {result.get('status')}")

    # ── 3. Analysis & Report (Lambda B) ──
    print("[Pipeline] Step 3: Analysis & Report")
    report_result = _http_post(LAMBDA_B_URL, {
        "run_id": run_id,
        "patient_info": patient_info,
        "parallel_results": {
            "seg": inference.get("seg", {}),
            "densenet": inference.get("densenet", {}),
            "yolo": inference.get("yolo", {"detections": [], "status": "failed"}),
        },
    })

    elapsed = round(time.time() - start_time, 2)
    print(f"[Pipeline] 완료: {elapsed}s")

    return _response(200, {
        "status": "SUCCEEDED",
        "run_id": run_id,
        "results": {
            "report": report_result.get("report"),
            "clinical_logic": report_result.get("clinical_logic"),
            "rag_evidence": report_result.get("rag_evidence"),
            "seg": inference.get("seg"),
            "densenet": inference.get("densenet"),
            "yolo": inference.get("yolo"),
        },
        "timing": {"totalSeconds": elapsed},
    })


def _http_post(url, payload, timeout=180):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        body = e.read().decode() if e.fp else ""
        raise RuntimeError(f"HTTP {e.code}: {body[:300]}")


def _response(status_code, body):
    # CORS 헤더는 Function URL이 자동 처리 — 중복 방지를 위해 여기선 제거
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
        },
        "body": json.dumps(body, ensure_ascii=False, default=str),
    }
