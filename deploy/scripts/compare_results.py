"""
ONNX vs PyTorch 추론 결과 비교 스크립트.
동일한 이미지를 기존 Lambda(PyTorch)와 새 Lambda(ONNX)에 보내서 결과를 비교.

사용법:
    python compare_results.py \
        --old-endpoint "https://xxx.lambda-url.ap-northeast-2.on.aws" \
        --new-function "dr-ai-v2-lambda-a" \
        --image "s3://bucket/web/test-layer1/samples/sample_1.jpg"

    또는 로컬 이미지:
    python compare_results.py \
        --old-endpoint "https://xxx.lambda-url.ap-northeast-2.on.aws" \
        --new-function "dr-ai-v2-lambda-a" \
        --image "./test_image.jpg"
"""

import argparse
import json
import base64
import sys

import boto3
import numpy as np


def invoke_old_lambda(endpoint: str, image_base64: str) -> dict:
    """기존 Lambda (Function URL) 호출"""
    import urllib.request

    payload = json.dumps({"image_base64": image_base64}).encode()
    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def invoke_new_lambda(function_name: str, task: str, image_s3_uri: str) -> dict:
    """새 Lambda (ONNX) 호출"""
    client = boto3.client("lambda", region_name="ap-northeast-2")
    payload = {
        "task": task,
        "image_s3_uri": image_s3_uri,
        "run_id": "compare-test",
    }
    response = client.invoke(
        FunctionName=function_name,
        Payload=json.dumps(payload),
    )
    result = json.loads(response["Payload"].read())

    if result.get("status") == "ok":
        # Claim-Check에서 실제 결과 로드
        s3 = boto3.client("s3")
        uri = result["result_uri"]
        parts = uri.replace("s3://", "").split("/", 1)
        obj = s3.get_object(Bucket=parts[0], Key=parts[1])
        return json.loads(obj["Body"].read())
    else:
        print(f"[ERROR] Lambda 호출 실패: {result}")
        return {}


def compare_densenet(old_result: dict, new_result: dict):
    """DenseNet 14질환 확률 비교"""
    print("\n=== DenseNet-121 비교 (14질환) ===")
    print(f"{'질환':<30} {'PyTorch':>10} {'ONNX':>10} {'차이':>12} {'판정':>6}")
    print("-" * 72)

    old_preds = {p["disease"]: p["probability"] for p in old_result.get("predictions", [])}
    new_preds = {p["disease"]: p["probability"] for p in new_result.get("predictions", [])}

    all_pass = True
    for disease in old_preds:
        old_prob = old_preds.get(disease, 0)
        new_prob = new_preds.get(disease, 0)
        diff = abs(old_prob - new_prob)
        passed = diff <= 1e-5
        if not passed:
            all_pass = False
        status = "PASS" if passed else "FAIL"
        print(f"{disease:<30} {old_prob:>10.6f} {new_prob:>10.6f} {diff:>12.8f} {status:>6}")

    print("-" * 72)
    print(f"전체 판정: {'PASS (atol<=1e-5)' if all_pass else 'FAIL'}")
    return all_pass


def compare_segmentation(old_result: dict, new_result: dict):
    """세그멘테이션 계측값 비교"""
    print("\n=== Segmentation 비교 (계측값) ===")
    old_m = old_result.get("measurements", {})
    new_m = new_result.get("measurements", {})

    print(f"{'항목':<25} {'PyTorch':>10} {'ONNX':>10} {'차이':>12}")
    print("-" * 60)

    for key in old_m:
        old_val = old_m.get(key, 0)
        new_val = new_m.get(key, 0)
        if isinstance(old_val, (int, float)) and isinstance(new_val, (int, float)):
            diff = abs(old_val - new_val)
            print(f"{key:<25} {old_val:>10.4f} {new_val:>10.4f} {diff:>12.8f}")


def main():
    parser = argparse.ArgumentParser(description="ONNX vs PyTorch 결과 비교")
    parser.add_argument("--old-endpoint", required=True, help="기존 Lambda Function URL")
    parser.add_argument("--new-function", required=True, help="새 Lambda 함수 이름")
    parser.add_argument("--image", required=True, help="테스트 이미지 (S3 URI 또는 로컬 경로)")
    parser.add_argument("--task", default="densenet", choices=["seg", "densenet", "yolo"],
                        help="비교할 task (기본: densenet)")
    args = parser.parse_args()

    # 이미지 준비
    if args.image.startswith("s3://"):
        image_s3_uri = args.image
        # base64 변환 (기존 Lambda용)
        s3 = boto3.client("s3")
        parts = args.image.replace("s3://", "").split("/", 1)
        obj = s3.get_object(Bucket=parts[0], Key=parts[1])
        image_bytes = obj["Body"].read()
        image_base64 = base64.b64encode(image_bytes).decode()
    else:
        with open(args.image, "rb") as f:
            image_bytes = f.read()
        image_base64 = base64.b64encode(image_bytes).decode()
        # 로컬 이미지의 경우 S3에 업로드 필요
        print("[INFO] 로컬 이미지는 S3 URI가 필요합니다. --image에 S3 URI를 사용해주세요.")
        sys.exit(1)

    print(f"테스트 이미지: {args.image}")
    print(f"비교 대상: {args.task}")
    print("=" * 60)

    # 1. 기존 Lambda 호출
    print("\n[1/2] 기존 Lambda (PyTorch) 호출 중...")
    old_result = invoke_old_lambda(args.old_endpoint, image_base64)
    print(f"      응답 키: {list(old_result.keys())}")

    # 2. 새 Lambda 호출
    print(f"\n[2/2] 새 Lambda (ONNX) 호출 중... ({args.new_function})")
    new_result = invoke_new_lambda(args.new_function, args.task, image_s3_uri)
    print(f"      응답 키: {list(new_result.keys())}")

    # 3. 결과 비교
    if args.task == "densenet":
        compare_densenet(old_result, new_result)
    elif args.task == "seg":
        compare_segmentation(old_result, new_result)
    else:
        print("\n[INFO] YOLOv8 비교는 bbox 좌표 + confidence를 수동으로 확인하세요.")
        print(f"Old detections: {len(old_result.get('detections', []))}")
        print(f"New detections: {len(new_result.get('detections', []))}")


if __name__ == "__main__":
    main()
