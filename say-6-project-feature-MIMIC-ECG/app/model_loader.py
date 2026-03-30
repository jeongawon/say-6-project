import os
import boto3
import onnxruntime as ort

_MODEL_S3_BUCKET = os.environ.get("MODEL_BUCKET", "say2-6team")
_MODEL_S3_KEY    = os.environ.get("MODEL_KEY", "models/ecg_resnet.onnx")
_MODEL_TMP_PATH  = "/tmp/ecg_resnet.onnx"

# 로컬 개발 경로 후보
_LOCAL_CANDIDATES = [
    os.environ.get("MODEL_PATH", ""),
    "/mnt/efs/models/ecg_resnet.onnx",
    "models/ecg_resnet.onnx",
    "ecg_resnet.onnx",
]

_session = None


def get_session() -> ort.InferenceSession:
    global _session
    if _session is None:
        _session = _load_session()
    return _session


def _load_session() -> ort.InferenceSession:
    # 1) 로컬 경로 우선 시도
    local_path = next(
        (p for p in _LOCAL_CANDIDATES if p and os.path.exists(p)), None
    )
    if local_path:
        model_path = local_path
    else:
        # 2) S3 → /tmp 다운로드 (Lambda 환경)
        if not os.path.exists(_MODEL_TMP_PATH):
            print(f"[model_loader] S3에서 모델 다운로드: s3://{_MODEL_S3_BUCKET}/{_MODEL_S3_KEY}")
            boto3.client("s3").download_file(_MODEL_S3_BUCKET, _MODEL_S3_KEY, _MODEL_TMP_PATH)
        model_path = _MODEL_TMP_PATH

    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    session = ort.InferenceSession(model_path, providers=providers)
    print(f"[model_loader] ONNX 모델 로드 완료: {model_path}")
    return session
