import os
from pathlib import Path

# S3
S3_BUCKET     = os.getenv("S3_BUCKET", "say2-6team")
S3_MODEL_KEY  = os.getenv("S3_MODEL_KEY", "mimic/ecg/ecg_s6.onnx")
S3_DATA_KEY   = os.getenv("S3_DATA_KEY",  "mimic/ecg/ecg_s6.onnx.data")

# 로컬 모델 캐시 경로
MODEL_DIR     = Path(os.getenv("MODEL_DIR", "/app/models"))
MODEL_PATH    = MODEL_DIR / "ecg_s6.onnx"

# 서버
HOST          = os.getenv("HOST", "0.0.0.0")
PORT          = int(os.getenv("PORT", 8000))
LOG_LEVEL     = os.getenv("LOG_LEVEL", "info")
