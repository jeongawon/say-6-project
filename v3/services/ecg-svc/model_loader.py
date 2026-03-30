"""ONNX 모델 로더 — K8s 볼륨 마운트 전용, S3 폴백 없음."""
import os
import onnxruntime as ort

_session: ort.InferenceSession | None = None


def load_model(model_path: str) -> ort.InferenceSession:
    global _session
    if _session is not None:
        return _session
    if not os.path.exists(model_path):
        raise FileNotFoundError(
            f"Model not found: {model_path}. 모델 볼륨이 마운트되었는지 확인하세요."
        )
    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    _session = ort.InferenceSession(model_path, providers=providers)
    return _session


def get_session() -> ort.InferenceSession | None:
    """캐시된 세션 반환. 모델 미로드 시 None 반환 (규칙 기반 폴백 허용)."""
    return _session
