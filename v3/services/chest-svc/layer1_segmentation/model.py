"""
Layer 1 — ONNX Runtime UNet 세그멘테이션 추론 + CTR/CP angle/폐 면적비 측정.

세그멘테이션 클래스:
  0 — Background
  1 — Left Lung
  2 — Right Lung
  3 — Heart
  4 — Mediastinum (optional)
"""

import time
import base64
import io

import numpy as np
from PIL import Image

from .preprocessing import preprocess_for_segmentation

# ── 세그멘테이션 클래스 정의 ──────────────────────────────────
SEG_CLASSES = {
    0: "background",
    1: "left_lung",
    2: "right_lung",
    3: "heart",
    4: "mediastinum",
}


# ── 마스크 → base64 PNG ───────────────────────────────────
def _mask_to_base64(mask: np.ndarray) -> str:
    """(H, W) uint8 마스크를 반투명 RGBA PNG base64로 인코딩.
    배경(class 0)은 완전 투명, 장기 영역은 반투명 오버레이."""
    h, w = mask.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)

    # class 0: background → 완전 투명 (alpha=0)
    # class 1: left lung → 파랑 반투명
    rgba[mask == 1] = [0, 100, 255, 100]
    # class 2: right lung → 초록 반투명
    rgba[mask == 2] = [0, 200, 100, 100]
    # class 3: heart → 빨강 반투명
    rgba[mask == 3] = [255, 50, 50, 120]
    # class 4+: mediastinum 등 → 노랑 반투명
    rgba[mask >= 4] = [255, 255, 0, 80]

    img = Image.fromarray(rgba, mode="RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# ── CTR (Cardiothoracic Ratio) 계산 ─────────────────────────
def _compute_ctr(mask: np.ndarray) -> float:
    """
    CTR = heart_width / thorax_width

    heart_width: 심장 영역(class 3)의 최대 수평 폭.
    thorax_width: 양쪽 폐(class 1+2)의 최대 수평 폭.

    정상: < 0.5, 심비대: >= 0.5
    """
    heart_mask = (mask == 3)
    lung_mask = (mask == 1) | (mask == 2)

    if not heart_mask.any() or not lung_mask.any():
        return 0.0

    # 심장 — 각 행별 수평 폭, 최대값
    heart_rows = np.where(heart_mask.any(axis=1))[0]
    heart_widths = []
    for r in heart_rows:
        cols = np.where(heart_mask[r])[0]
        heart_widths.append(cols[-1] - cols[0])
    heart_width = max(heart_widths) if heart_widths else 0

    # 흉곽 — 양쪽 폐 전체의 최대 수평 범위
    lung_rows = np.where(lung_mask.any(axis=1))[0]
    thorax_widths = []
    for r in lung_rows:
        cols = np.where(lung_mask[r])[0]
        thorax_widths.append(cols[-1] - cols[0])
    thorax_width = max(thorax_widths) if thorax_widths else 1  # div-by-zero 방지

    ctr = float(heart_width) / float(thorax_width)
    return round(ctr, 4)


# ── CP angle (costophrenic angle) 계산 ──────────────────────
def _compute_cp_angle(mask: np.ndarray, lung_class: int) -> float:
    """
    Costophrenic angle 근사 계산.

    날카로운 CP angle (> ~30도): 정상
    무딘(blunted) CP angle (< ~30도): 흉수(pleural effusion) 의심

    Args:
        mask: 세그멘테이션 마스크 (H, W)
        lung_class: 1 (left lung) 또는 2 (right lung)

    Returns:
        CP angle in degrees (0~180). 폐 영역이 없으면 0.0.
    """
    lung_mask = (mask == lung_class)

    if not lung_mask.any():
        return 0.0

    rows = np.where(lung_mask.any(axis=1))[0]
    bottom_row = rows[-1]

    # 최하단 부근(하위 10% 행)
    lower_region_start = max(rows[0], int(bottom_row - 0.1 * (bottom_row - rows[0])))
    lower_rows = rows[rows >= lower_region_start]

    if len(lower_rows) < 2:
        return 0.0

    # 각 행에서 폐 영역의 외측 가장자리 좌표 추출
    lateral_points = []
    for r in lower_rows:
        cols = np.where(lung_mask[r])[0]
        if len(cols) == 0:
            continue
        if lung_class == 1:
            lateral_points.append((r, cols[0]))
        else:
            lateral_points.append((r, cols[-1]))

    if len(lateral_points) < 2:
        return 0.0

    cp_point = lateral_points[-1]
    top_point = lateral_points[0]

    bottom_cols = np.where(lung_mask[bottom_row])[0]
    if len(bottom_cols) == 0:
        return 0.0

    if lung_class == 1:
        diaphragm_point = (bottom_row, bottom_cols[-1])
    else:
        diaphragm_point = (bottom_row, bottom_cols[0])

    vec_a = np.array([top_point[0] - cp_point[0], top_point[1] - cp_point[1]], dtype=np.float64)
    vec_b = np.array([diaphragm_point[0] - cp_point[0], diaphragm_point[1] - cp_point[1]], dtype=np.float64)

    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)

    if norm_a < 1e-6 or norm_b < 1e-6:
        return 0.0

    cos_angle = np.dot(vec_a, vec_b) / (norm_a * norm_b)
    cos_angle = np.clip(cos_angle, -1.0, 1.0)
    angle_deg = float(np.degrees(np.arccos(cos_angle)))

    return round(angle_deg, 2)


# ── 폐 면적비 ──────────────────────────────────────────────
def _compute_lung_area_ratio(mask: np.ndarray) -> float:
    """
    좌/우 폐 면적비.
    정상: left:right ~ 0.8~1.0 (우폐가 약간 더 큼).
    큰 차이 → 무기폐, 흉수, 기흉 등 의심.
    """
    left_area = int(np.sum(mask == 1))
    right_area = int(np.sum(mask == 2))

    if right_area == 0:
        return 0.0

    return round(float(left_area) / float(right_area), 4)


# ── 클래스별 면적(픽셀 수) ─────────────────────────────────
def _compute_class_areas(mask: np.ndarray) -> dict:
    """각 세그멘테이션 클래스의 픽셀 수를 반환."""
    areas = {}
    for cls_id, cls_name in SEG_CLASSES.items():
        areas[cls_name] = int(np.sum(mask == cls_id))
    return areas


# ── 메인 추론 함수 ──────────────────────────────────────────
def run_segmentation(session, pil_image: Image.Image) -> dict:
    """
    세그멘테이션 추론 + 임상 측정값 산출.

    Args:
        session: ort.InferenceSession (U-Net ONNX)
        pil_image: RGB PIL Image (원본 크기)

    Returns:
        {
            "mask_base64": str,
            "measurements": { ctr, ctr_status, cp_angle_left/right, lung_area_ratio, ... },
            "class_areas": {...},
            "view": str,
            "age_pred": float | None,
            "sex_pred": str,
            "processing_time": float,
        }
    """
    t0 = time.time()

    # 전처리
    input_array = preprocess_for_segmentation(pil_image)

    # 추론 — UNet ONNX 출력: [seg_mask, view_pred, age_pred, female_pred]
    outputs = session.run(None, {"image": input_array})
    logits = outputs[0]  # seg_mask: (1, 4, 320, 320)

    # 추가 출력 파싱
    view_logits = outputs[1] if len(outputs) > 1 else None   # (1, 3)
    age_pred = outputs[2] if len(outputs) > 2 else None      # (1, 1)
    female_pred = outputs[3] if len(outputs) > 3 else None   # (1, 1)

    # argmax → 마스크 (H, W)
    mask = np.argmax(logits[0], axis=0).astype(np.uint8)

    # 마스크 base64 인코딩
    mask_b64 = _mask_to_base64(mask)

    # 임상 측정값
    ctr = _compute_ctr(mask)
    cp_left = _compute_cp_angle(mask, lung_class=1)
    cp_right = _compute_cp_angle(mask, lung_class=2)
    lung_ratio = _compute_lung_area_ratio(mask)
    class_areas = _compute_class_areas(mask)

    elapsed = round(time.time() - t0, 4)

    # view 분류 (PA/AP/Lateral)
    view_labels = ["AP", "PA", "Lateral"]
    view = "unknown"
    if view_logits is not None:
        view_probs = np.exp(view_logits[0]) / np.sum(np.exp(view_logits[0]))
        view = view_labels[int(np.argmax(view_probs))]

    # 나이/성별 예측
    age = float(age_pred[0][0]) if age_pred is not None else None
    sex = "F" if (female_pred is not None and float(female_pred[0][0]) > 0.5) else "M"

    return {
        "mask_base64": mask_b64,
        "original_size": [pil_image.height, pil_image.width],  # [H, W] — SVG viewBox 용
        "measurements": {
            "ctr": ctr,
            "ctr_status": "normal" if ctr < 0.5 else "cardiomegaly",
            "cp_angle_left": cp_left,
            "cp_angle_right": cp_right,
            "lung_area_ratio": lung_ratio,
            "heart_width_px": int(class_areas.get("heart", 0) ** 0.5) if class_areas.get("heart", 0) > 0 else 0,
            "thorax_width_px": int((class_areas.get("left_lung", 0) + class_areas.get("right_lung", 0)) ** 0.5) if (class_areas.get("left_lung", 0) + class_areas.get("right_lung", 0)) > 0 else 0,
            "right_lung_area_px": class_areas.get("right_lung", 0),
            "left_lung_area_px": class_areas.get("left_lung", 0),
            "heart_area_px": class_areas.get("heart", 0),
        },
        "class_areas": class_areas,
        "view": view,
        "age_pred": round(age, 1) if age is not None else None,
        "sex_pred": sex,
        "processing_time": elapsed,
    }
