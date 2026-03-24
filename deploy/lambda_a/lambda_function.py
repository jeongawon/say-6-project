"""
Lambda A — Vision Inference Handler (No S3 Write).

HTTP 호출로 추론 결과를 직접 JSON 응답으로 반환.
S3는 모델 다운로드(읽기)만 사용. 결과 저장(쓰기) 없음.

이벤트 형식:
{
    "task": "seg" | "densenet" | "yolo" | "preprocess",
    "image_base64": "base64-string",
    "run_id": "uuid-string",
    "patient_info": { ... }
}
"""

import io
import json
import time
import base64
import traceback

import boto3
from PIL import Image

from config import Config
from model_loader import get_model
from inference_seg import run_segmentation
from inference_densenet import run_densenet
from inference_yolo import run_yolov8

# ── 글로벌 초기화 ─────────────────────────────────────────────
config = Config()
s3_client = boto3.client("s3")

TASK_DISPATCH = {
    "seg": run_segmentation,
    "densenet": run_densenet,
    "yolo": run_yolov8,
}


def load_image_from_base64(image_b64: str) -> Image.Image:
    """base64 → RGB PIL Image."""
    image_bytes = base64.b64decode(image_b64)
    image = Image.open(io.BytesIO(image_bytes))
    if image.mode != "RGB":
        image = image.convert("RGB")
    return image


def lambda_handler(event, context):
    # Function URL 이벤트 지원
    if "body" in event and isinstance(event.get("body"), str):
        event = json.loads(event["body"])

    print(f"[LambdaA] task={event.get('task')}, run_id={event.get('run_id')}")

    try:
        task = event.get("task")
        run_id = event.get("run_id", "unknown")

        if not task:
            raise ValueError("'task' 파라미터가 필요합니다")

        # ── preprocess: base64 검증만 하고 그대로 반환 ──
        if task == "preprocess":
            image_b64 = event.get("image_base64", "")
            img = load_image_from_base64(image_b64)
            print(f"[Preprocess] 원본: {img.size}, mode={img.mode}")

            # 큰 이미지 축소 (Lambda 응답 6MB 제한 대응)
            max_dim = 1024
            if max(img.size) > max_dim:
                ratio = max_dim / max(img.size)
                new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
                img = img.resize(new_size, Image.BILINEAR)
                print(f"[Preprocess] 리사이즈: {img.size}")

            # JPEG로 재인코딩 (PNG보다 훨씬 작음)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            normalized_b64 = base64.b64encode(buf.getvalue()).decode()
            print(f"[Preprocess] base64 크기: {len(normalized_b64) / 1024:.0f}KB")

            return {
                "status": "ok",
                "task": "preprocess",
                "run_id": run_id,
                "image_base64": normalized_b64,
                "image_size": list(img.size),
                "patient_info": event.get("patient_info", {}),
            }

        # ── 추론 태스크: base64에서 직접 로드 → 결과 직접 반환 ──
        if task not in TASK_DISPATCH:
            raise ValueError(f"알 수 없는 태스크: {task}")

        image_b64 = event.get("image_base64", "")
        if not image_b64:
            raise ValueError("'image_base64' 파라미터가 필요합니다")

        t_total = time.time()

        # 1) 모델 로드
        t_model = time.time()
        session = get_model(task, config)
        model_load_time = round(time.time() - t_model, 4)

        # 2) 이미지 로드 (base64에서)
        pil_image = load_image_from_base64(image_b64)

        # 3) 추론 실행
        inference_fn = TASK_DISPATCH[task]
        result = inference_fn(session, pil_image)

        total_time = round(time.time() - t_total, 4)

        result["_meta"] = {
            "task": task,
            "run_id": run_id,
            "model_load_time": model_load_time,
            "total_time": total_time,
        }
        result["status"] = "ok"
        result["task"] = task
        result["run_id"] = run_id

        print(f"[LambdaA] {task} 완료: {total_time}s")
        return result

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        print(f"[LambdaA] 오류: {error_msg}\n{traceback.format_exc()}")
        return {
            "status": "failed",
            "task": event.get("task", "unknown"),
            "run_id": event.get("run_id", "unknown"),
            "message": error_msg,
        }
