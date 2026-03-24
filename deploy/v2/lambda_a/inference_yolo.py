"""
YOLOv8 inference (L2b logic).

VinDr-CXR 19-class 물체 탐지.
Letterbox 전처리, confidence 필터링, NMS 적용.
"""

import time

import numpy as np
from PIL import Image


# ── VinDr-CXR 19 클래스 ──────────────────────────────────
VINDR_CLASSES = [
    "Aortic_enlargement",
    "Atelectasis",
    "Calcification",
    "Cardiomegaly",
    "Clavicle_fracture",
    "Consolidation",
    "Edema",
    "Emphysema",
    "Enlarged_PA",
    "ILD",
    "Infiltration",
    "Lung_Opacity",
    "Nodule/Mass",
    "Other_lesion",
    "Pleural_effusion",
    "Pleural_thickening",
    "Pneumothorax",
    "Pulmonary_fibrosis",
    "Rib_fracture",
]

INPUT_SIZE = 1024  # YOLOv8 정사각 입력 (ONNX export 시 imgsz=1024)
CONF_THRESHOLD = 0.25
IOU_THRESHOLD = 0.45


# ── Letterbox 전처리 ────────────────────────────────────────
def _letterbox(pil_image: Image.Image, target_size: int = INPUT_SIZE):
    """
    종횡비를 유지하며 target_size x target_size로 리사이즈 + 패딩.

    Returns:
        (input_array, scale, pad_x, pad_y)
        input_array: (1, 3, target_size, target_size) float32
        scale: 리사이즈 비율 (원본 → letterbox)
        pad_x, pad_y: 패딩 오프셋 (letterbox → 원본 좌표 역변환 시 사용)
    """
    w, h = pil_image.size

    # 긴 변에 맞추어 스케일 결정
    scale = target_size / max(w, h)
    new_w = int(w * scale)
    new_h = int(h * scale)

    # 리사이즈
    resized = pil_image.resize((new_w, new_h), Image.BILINEAR)

    # 패딩 (회색 = 114/255)
    pad_x = (target_size - new_w) // 2
    pad_y = (target_size - new_h) // 2

    canvas = Image.new("RGB", (target_size, target_size), (114, 114, 114))
    canvas.paste(resized, (pad_x, pad_y))

    # numpy 변환 + 정규화
    arr = np.array(canvas, dtype=np.float32) / 255.0  # (H, W, 3)
    arr = arr.transpose(2, 0, 1)  # (3, H, W)
    arr = np.expand_dims(arr, axis=0)  # (1, 3, H, W)

    return arr.astype(np.float32), scale, pad_x, pad_y


# ── NMS (Non-Maximum Suppression) ──────────────────────────
def _compute_iou(box: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    """
    단일 box와 여러 boxes 사이의 IoU 계산.

    Args:
        box: (4,) — [x1, y1, x2, y2]
        boxes: (N, 4) — [[x1, y1, x2, y2], ...]

    Returns:
        (N,) IoU 값
    """
    x1 = np.maximum(box[0], boxes[:, 0])
    y1 = np.maximum(box[1], boxes[:, 1])
    x2 = np.minimum(box[2], boxes[:, 2])
    y2 = np.minimum(box[3], boxes[:, 3])

    intersection = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)

    box_area = (box[2] - box[0]) * (box[3] - box[1])
    boxes_area = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])

    union = box_area + boxes_area - intersection
    return intersection / np.maximum(union, 1e-6)


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> np.ndarray:
    """
    Non-Maximum Suppression.

    Args:
        boxes: (N, 4) — [x1, y1, x2, y2]
        scores: (N,)
        iou_threshold: IoU 임계값

    Returns:
        keep 인덱스 배열
    """
    if len(boxes) == 0:
        return np.array([], dtype=np.int64)

    # 점수 내림차순 정렬
    order = scores.argsort()[::-1]

    keep = []
    while len(order) > 0:
        idx = order[0]
        keep.append(idx)

        if len(order) == 1:
            break

        # 현재 박스와 나머지의 IoU 계산
        ious = _compute_iou(boxes[idx], boxes[order[1:]])

        # IoU < threshold 인 것만 유지
        remaining = np.where(ious < iou_threshold)[0]
        order = order[remaining + 1]  # +1: order[1:]에서의 인덱스이므로

    return np.array(keep, dtype=np.int64)


# ── YOLOv8 출력 파싱 ────────────────────────────────────────
def _parse_yolov8_output(
    output: np.ndarray,
    scale: float,
    pad_x: int,
    pad_y: int,
    orig_w: int,
    orig_h: int,
    conf_threshold: float = CONF_THRESHOLD,
    iou_threshold: float = IOU_THRESHOLD,
) -> list[dict]:
    """
    YOLOv8 raw output을 파싱하여 탐지 결과 리스트로 변환.

    YOLOv8 출력 형식: (1, 4 + num_classes, num_anchors)
    - 처음 4행: cx, cy, w, h (letterbox 좌표계)
    - 나머지 행: 클래스별 confidence

    Args:
        output: (1, 4+C, N) raw 출력
        scale, pad_x, pad_y: letterbox 파라미터
        orig_w, orig_h: 원본 이미지 크기
        conf_threshold: confidence 필터 임계값
        iou_threshold: NMS IoU 임계값

    Returns:
        [{"class": str, "confidence": float, "bbox": {"x1":..., "y1":..., "x2":..., "y2":...}}, ...]
    """
    # (1, 4+C, N) → (N, 4+C)
    predictions = output[0].T  # (N, 4+C)

    num_classes = predictions.shape[1] - 4

    # 박스 좌표 (cx, cy, w, h) — letterbox 좌표계
    cx = predictions[:, 0]
    cy = predictions[:, 1]
    w = predictions[:, 2]
    h = predictions[:, 3]

    # 클래스별 confidence
    class_scores = predictions[:, 4:]  # (N, C)

    # 최대 confidence 클래스
    class_ids = np.argmax(class_scores, axis=1)  # (N,)
    max_scores = np.max(class_scores, axis=1)  # (N,)

    # confidence 필터
    mask = max_scores > conf_threshold
    if not mask.any():
        return []

    cx = cx[mask]
    cy = cy[mask]
    w = w[mask]
    h = h[mask]
    class_ids = class_ids[mask]
    max_scores = max_scores[mask]

    # cxcywh → xyxy (letterbox 좌표계)
    x1 = cx - w / 2
    y1 = cy - h / 2
    x2 = cx + w / 2
    y2 = cy + h / 2

    boxes = np.stack([x1, y1, x2, y2], axis=1)  # (M, 4)

    # letterbox 좌표 → 원본 이미지 좌표
    boxes[:, 0] = (boxes[:, 0] - pad_x) / scale
    boxes[:, 1] = (boxes[:, 1] - pad_y) / scale
    boxes[:, 2] = (boxes[:, 2] - pad_x) / scale
    boxes[:, 3] = (boxes[:, 3] - pad_y) / scale

    # 원본 이미지 범위로 클리핑
    boxes[:, 0] = np.clip(boxes[:, 0], 0, orig_w)
    boxes[:, 1] = np.clip(boxes[:, 1], 0, orig_h)
    boxes[:, 2] = np.clip(boxes[:, 2], 0, orig_w)
    boxes[:, 3] = np.clip(boxes[:, 3], 0, orig_h)

    # 클래스별 NMS
    final_detections = []
    unique_classes = np.unique(class_ids)

    for cls_id in unique_classes:
        cls_mask = class_ids == cls_id
        cls_boxes = boxes[cls_mask]
        cls_scores = max_scores[cls_mask]

        keep = _nms(cls_boxes, cls_scores, iou_threshold)

        for k in keep:
            # 유효 클래스 범위 확인
            if cls_id < len(VINDR_CLASSES):
                class_name = VINDR_CLASSES[cls_id]
            else:
                class_name = f"unknown_{cls_id}"

            final_detections.append({
                "class": class_name,
                "confidence": float(round(cls_scores[k], 4)),
                "bbox": {
                    "x1": float(round(cls_boxes[k, 0], 2)),
                    "y1": float(round(cls_boxes[k, 1], 2)),
                    "x2": float(round(cls_boxes[k, 2], 2)),
                    "y2": float(round(cls_boxes[k, 3], 2)),
                },
            })

    # confidence 내림차순 정렬
    final_detections.sort(key=lambda d: d["confidence"], reverse=True)

    return final_detections


# ── 메인 추론 함수 ──────────────────────────────────────────
def run_yolov8(session, pil_image: Image.Image) -> dict:
    """
    YOLOv8 물체 탐지 추론.

    Args:
        session: ort.InferenceSession (YOLOv8 ONNX)
        pil_image: RGB PIL Image (원본 크기)

    Returns:
        {
            "detections": [
                {
                    "class": str,
                    "confidence": float,
                    "bbox": {"x1": float, "y1": float, "x2": float, "y2": float},
                },
                ...
            ],
            "processing_time": float,
        }
    """
    t0 = time.time()

    orig_w, orig_h = pil_image.size

    # 전처리 (letterbox)
    input_array, scale, pad_x, pad_y = _letterbox(pil_image, INPUT_SIZE)

    # 추론
    outputs = session.run(None, {"images": input_array})
    raw_output = outputs[0]  # (1, 4+C, N)

    # 후처리 (파싱 + NMS)
    detections = _parse_yolov8_output(
        raw_output,
        scale=scale,
        pad_x=pad_x,
        pad_y=pad_y,
        orig_w=orig_w,
        orig_h=orig_h,
        conf_threshold=CONF_THRESHOLD,
        iou_threshold=IOU_THRESHOLD,
    )

    elapsed = round(time.time() - t0, 4)

    return {
        "detections": detections,
        "processing_time": elapsed,
    }
