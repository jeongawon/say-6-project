"""
Layer 1 전처리 — 이미지 resize, normalize for ONNX UNet.

U-Net 모델 사양:
  - in_chans=1 (grayscale), img_size=(320, 320)
  - 내부 normalize: (x/255 - 0.5) * 2 → [-1, 1]
  - 입력: 0-255 float32 그대로 전달 (모델이 자체 normalize 수행)
"""

import numpy as np
from PIL import Image

INPUT_SIZE = (320, 320)  # H, W


def preprocess_for_segmentation(pil_image: Image.Image) -> np.ndarray:
    """
    PIL Image -> (1, 1, 320, 320) float32 array.

    모델 내부에서 (x/255 - 0.5) * 2 정규화를 수행하므로,
    여기서는 0-255 float32 그대로 전달.

    Args:
        pil_image: RGB PIL Image (원본 크기)

    Returns:
        (1, 1, 320, 320) float32 numpy array
    """
    img = pil_image.convert("L")
    img = img.resize((INPUT_SIZE[1], INPUT_SIZE[0]), Image.BILINEAR)
    arr = np.array(img, dtype=np.float32)  # (H, W), 0-255

    # (H, W) -> (1, H, W) -> (1, 1, H, W)
    arr = np.expand_dims(arr, axis=0)  # (1, H, W)
    arr = np.expand_dims(arr, axis=0)  # (1, 1, H, W)
    return arr.astype(np.float32)
