import os


class Config:
    REGION = os.environ.get("AWS_REGION", "ap-northeast-2")
    S3_BUCKET = os.environ.get(
        "S3_BUCKET",
        "pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an",
    )

    # ONNX 모델 S3 경로
    MODELS = {
        "seg": "models/onnx/unet.onnx",
        "densenet": "models/onnx/densenet.onnx",
        "yolo": "models/onnx/yolov8.onnx",
    }

    # /tmp 캐시 경로
    TMP_DIR = "/tmp"

    # Claim-Check 결과 저장 경로 접두사
    RESULT_PREFIX = "runs/"
