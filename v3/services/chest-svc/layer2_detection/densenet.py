"""
Layer 2a — ONNX Runtime DenseNet-121 (14 disease probabilities).

CheXpert / CheXNet 스타일 14-질환 multi-label 분류.
ImageNet 정규화 적용, sigmoid 후 0.5 임계값으로 POS/NEG 판정.
"""

import os
import sys
import time

import numpy as np
from PIL import Image

# thresholds.py (chest-svc 루트) 임포트를 위한 경로 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from thresholds import DENSENET_THRESHOLDS as _IMPORTED_THRESHOLDS  # noqa: E402

# ── 14 질환 라벨 (CheXpert 표준 순서) ─────────────────────
DISEASE_NAMES = [
    "Atelectasis",
    "Cardiomegaly",
    "Consolidation",
    "Edema",
    "Enlarged_Cardiomediastinum",
    "Fracture",
    "Lung_Lesion",
    "Lung_Opacity",
    "No_Finding",
    "Pleural_Effusion",
    "Pleural_Other",
    "Pneumonia",
    "Pneumothorax",
    "Support_Devices",
]

INPUT_SIZE = (224, 224)  # H, W

# ImageNet 정규화 파라미터
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

# 판정 임계값 — thresholds.py에서 가져온 값 (UNDERSCORE → SPACE 변환 포함)
# thresholds.py는 UNDERSCORE 형식("Pleural_Effusion")을 사용하지만,
# densenet.py의 기존 인터페이스는 SPACE 형식("Pleural Effusion")을 사용.
# 하위 호환을 위해 양쪽 형식 모두 포함.
DISEASE_THRESHOLDS = {}
for _name, _val in _IMPORTED_THRESHOLDS.items():
    DISEASE_THRESHOLDS[_name] = _val                         # underscore 형식
    DISEASE_THRESHOLDS[_name.replace("_", " ")] = _val       # space 형식
THRESHOLD = 0.5  # fallback


# ── sigmoid ────────────────────────────────────────────────
def _sigmoid(x: np.ndarray) -> np.ndarray:
    """Numerically stable sigmoid."""
    pos_mask = x >= 0
    neg_mask = ~pos_mask

    result = np.empty_like(x, dtype=np.float64)
    # x >= 0: 1 / (1 + exp(-x))
    result[pos_mask] = 1.0 / (1.0 + np.exp(-x[pos_mask]))
    # x < 0: exp(x) / (1 + exp(x))  — overflow 방지
    exp_x = np.exp(x[neg_mask])
    result[neg_mask] = exp_x / (1.0 + exp_x)

    return result


# ── 전처리 ──────────────────────────────────────────────────
def _preprocess(pil_image: Image.Image) -> np.ndarray:
    """
    PIL Image -> (1, 3, 224, 224) float32 array.
    ImageNet mean/std 정규화 적용.
    """
    img = pil_image.resize((INPUT_SIZE[1], INPUT_SIZE[0]), Image.BILINEAR)
    arr = np.array(img, dtype=np.float32) / 255.0  # (H, W, 3), range [0, 1]

    # ImageNet 정규화: (x - mean) / std
    arr = (arr - IMAGENET_MEAN) / IMAGENET_STD

    # HWC -> CHW -> NCHW
    arr = arr.transpose(2, 0, 1)  # (3, H, W)
    arr = np.expand_dims(arr, axis=0)  # (1, 3, H, W)
    return arr.astype(np.float32)


# ── 메인 추론 함수 ──────────────────────────────────────────
def run_densenet(session, pil_image: Image.Image) -> dict:
    """
    DenseNet-121 multi-label 분류 추론.

    Args:
        session: ort.InferenceSession (DenseNet ONNX)
        pil_image: RGB PIL Image (원본 크기)

    Returns:
        {
            "predictions": [
                {"disease": str, "probability": float, "status": "pos"|"neg"},
                ...
            ],
            "processing_time": float,
        }
    """
    t0 = time.time()

    # 전처리
    input_array = _preprocess(pil_image)

    # 추론 — 출력은 raw logits (1, 14)
    outputs = session.run(None, {"image": input_array})
    logits = outputs[0]  # (1, 14)

    # sigmoid → 확률
    probs = _sigmoid(logits[0])  # (14,)

    # 결과 구성
    predictions = []
    for i, disease in enumerate(DISEASE_NAMES):
        prob = float(round(probs[i], 4))
        thresh = DISEASE_THRESHOLDS.get(disease, THRESHOLD)
        status = "pos" if prob >= thresh else "neg"
        predictions.append({
            "disease": disease,
            "probability": prob,
            "status": status,
        })

    elapsed = round(time.time() - t0, 4)

    return {
        "predictions": predictions,
        "processing_time": elapsed,
    }
