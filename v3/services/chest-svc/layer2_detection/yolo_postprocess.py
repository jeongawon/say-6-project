"""
YOLO bbox 후처리 — 세그멘테이션 마스크 기반 해부학적 보정.

문제: VinDr-CXR YOLO 모델이 bbox 위치를 부정확하게 출력하는 경우가 있음.
      예) Cardiomegaly bbox가 심장이 아닌 횡격막/복부에 위치.

해결: 세그멘테이션 마스크(320x320)에서 해부학적 영역의 실제 bbox를 계산하고,
      YOLO detection과 매칭하여 보정.

클래스별 매핑:
  - Cardiomegaly, Enlarged_PA     → heart (class 3)
  - Pneumothorax, Emphysema       → 해당 폐 (class 1 or 2)
  - Pleural_effusion/thickening   → 해당 폐 하부
  - 폐 병변 (Consolidation 등)     → 폐 전체 (class 1+2)
  - 나머지                         → 보정 없이 유지
"""

import os
import sys

import numpy as np
from typing import Optional

# thresholds.py (chest-svc 루트) 임포트를 위한 경로 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from thresholds import CTR_SUPPLEMENT_PA, CTR_SUPPLEMENT_AP, YOLO_EDGE_MARGIN  # noqa: E402


# ── 클래스 → 해부학 영역 매핑 ──────────────────────────────
# heart: mask class 3, lung: mask class 1+2
_CLASS_ANATOMY_MAP = {
    # 심장 관련 → heart mask bbox로 보정
    "Cardiomegaly":         "heart",
    "Enlarged_PA":          "heart",
    "Aortic_enlargement":   "heart",
    # 기흉/폐기종 → 폐 영역 (IoU 기반 좌/우 결정)
    "Pneumothorax":         "lung",
    "Emphysema":            "lung",
    # 흉막 관련 → 폐 하부 영역
    "Pleural_effusion":     "lung_lower",
    "Pleural_thickening":   "lung_lower",
    # 폐 병변 → 폐 전체 영역 내에서 보정
    "Consolidation":        "lung",
    "Edema":                "lung",
    "Infiltration":         "lung",
    "Lung_Opacity":         "lung",
    "Nodule/Mass":          "lung",
    "ILD":                  "lung",
    "Pulmonary_fibrosis":   "lung",
    "Atelectasis":          "lung",
    "Calcification":        None,  # 위치 보정 안 함
    "Other_lesion":         None,
    "Clavicle_fracture":    None,
    "Rib_fracture":         None,
}


def _mask_bbox(mask: np.ndarray, classes: list[int]) -> Optional[list[int]]:
    """마스크에서 특정 클래스들의 합집합 bbox를 원본 이미지 좌표로 계산.
    mask: (320, 320) uint8 → 원본 좌표로 스케일링 필요."""
    combined = np.zeros_like(mask, dtype=bool)
    for c in classes:
        combined |= (mask == c)
    if not combined.any():
        return None
    rows = np.where(combined.any(axis=1))[0]
    cols = np.where(combined.any(axis=0))[0]
    return [int(cols[0]), int(rows[0]), int(cols[-1]), int(rows[-1])]


def _mask_bbox_lower_half(mask: np.ndarray, classes: list[int]) -> Optional[list[int]]:
    """마스크에서 특정 클래스들의 하반부 bbox 계산 (흉막삼출 등)."""
    combined = np.zeros_like(mask, dtype=bool)
    for c in classes:
        combined |= (mask == c)
    if not combined.any():
        return None
    rows = np.where(combined.any(axis=1))[0]
    mid_row = (rows[0] + rows[-1]) // 2
    lower = combined.copy()
    lower[:mid_row, :] = False
    if not lower.any():
        return None
    rows2 = np.where(lower.any(axis=1))[0]
    cols2 = np.where(lower.any(axis=0))[0]
    return [int(cols2[0]), int(rows2[0]), int(cols2[-1]), int(rows2[-1])]


def _iou(box_a: list, box_b: list) -> float:
    """두 bbox의 IoU."""
    x1 = max(box_a[0], box_b[0])
    y1 = max(box_a[1], box_b[1])
    x2 = min(box_a[2], box_b[2])
    y2 = min(box_a[3], box_b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = max(0, box_a[2] - box_a[0]) * max(0, box_a[3] - box_a[1])
    area_b = max(0, box_b[2] - box_b[0]) * max(0, box_b[3] - box_b[1])
    union = area_a + area_b - inter
    return inter / max(union, 1e-6)


def _center_in_box(bbox: list, region: list) -> bool:
    """YOLO bbox의 중심이 해부학 영역 내에 있는지 확인."""
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    return region[0] <= cx <= region[2] and region[1] <= cy <= region[3]


def postprocess_yolo_with_seg(
    yolo_detections: list[dict],
    seg_mask: np.ndarray,
    image_size: list[int],
    iou_threshold: float = 0.15,
) -> list[dict]:
    """
    YOLO bbox를 세그멘테이션 마스크 기반으로 후처리.

    보정 조건 (OR):
      1) IoU < iou_threshold (기본 0.15) — 해부학 영역과 겹침이 부족
      2) YOLO bbox 중심이 해부학 영역 밖 — 명백한 위치 오류

    Args:
        yolo_detections: [{"class_name", "confidence", "bbox":[x1,y1,x2,y2], ...}]
        seg_mask: (320, 320) uint8 세그멘테이션 마스크 (argmax 결과)
        image_size: [orig_w, orig_h] 원본 이미지 크기
        iou_threshold: YOLO bbox와 해부학 bbox의 최소 IoU (이하면 보정)

    Returns:
        보정된 yolo_detections (원본 리스트 수정하지 않음)
    """
    if not yolo_detections or seg_mask is None:
        return yolo_detections

    orig_w, orig_h = image_size
    mask_h, mask_w = seg_mask.shape

    # 마스크 좌표 → 원본 좌표 스케일 팩터
    sx = orig_w / mask_w
    sy = orig_h / mask_h

    # 해부학 영역별 bbox 캐시 (마스크 좌표)
    anatomy_cache = {}

    def get_anatomy_bbox(anatomy_type: str) -> Optional[list[int]]:
        if anatomy_type in anatomy_cache:
            return anatomy_cache[anatomy_type]

        if anatomy_type == "heart":
            bbox_m = _mask_bbox(seg_mask, [3])
        elif anatomy_type == "lung":
            bbox_m = _mask_bbox(seg_mask, [1, 2])
        elif anatomy_type == "lung_lower":
            bbox_m = _mask_bbox_lower_half(seg_mask, [1, 2])
        else:
            bbox_m = None

        if bbox_m is not None:
            # 마스크 좌표 → 원본 이미지 좌표로 변환
            bbox_orig = [
                round(bbox_m[0] * sx),
                round(bbox_m[1] * sy),
                round(bbox_m[2] * sx),
                round(bbox_m[3] * sy),
            ]
            anatomy_cache[anatomy_type] = bbox_orig
        else:
            anatomy_cache[anatomy_type] = None
        return anatomy_cache[anatomy_type]

    corrected = []
    for det in yolo_detections:
        new_det = dict(det)  # 복사
        cls_name = det.get("class_name", "")
        anatomy_type = _CLASS_ANATOMY_MAP.get(cls_name)

        if anatomy_type is None:
            corrected.append(new_det)
            continue

        anatomy_bbox = get_anatomy_bbox(anatomy_type)
        if anatomy_bbox is None:
            corrected.append(new_det)
            continue

        yolo_bbox = det["bbox"]
        overlap = _iou(yolo_bbox, anatomy_bbox)
        center_inside = _center_in_box(yolo_bbox, anatomy_bbox)

        # 보정 조건: IoU 부족 OR 중심이 영역 밖
        needs_correction = (overlap < iou_threshold) or (not center_inside)

        if needs_correction:
            new_det["bbox"] = anatomy_bbox
            new_det["bbox_corrected"] = True
            new_det["original_bbox"] = yolo_bbox
            new_det["correction_reason"] = (
                f"IoU={overlap:.2f}, center_inside={center_inside} → "
                f"corrected to {anatomy_type} mask bbox"
            )

        corrected.append(new_det)

    return corrected


# ── Phase 2: YOLO 후처리 보강 ──────────────────────────────


def supplement_cardiomegaly(
    detections: list[dict],
    seg_result: dict,
) -> list[dict]:
    """
    CTR 기반 Cardiomegaly 보충 탐지.

    문제: YOLO가 Cardiomegaly bbox를 놓치는 FN 케이스 (17건).
    해결: CTR >= 0.53이면서 YOLO에 Cardiomegaly 탐지가 없으면,
          심장 마스크(class_id=3)에서 bbox를 합성하여 추가.

    Args:
        detections: 현재 YOLO 탐지 결과 리스트
        seg_result: 세그멘테이션 결과 dict (measurements, mask_raw, original_size 포함)

    Returns:
        보충된 탐지 결과 리스트 (원본 수정하지 않음)
    """
    # CTR 값 확인
    measurements = seg_result.get("measurements", {})
    ctr = measurements.get("ctr", 0.0)

    # AP 뷰에서는 CTR이 ~0.05 과대추정되므로 보완 기준 상향
    view = seg_result.get("view", "PA")
    if view == "AP":
        supplement_threshold = CTR_SUPPLEMENT_AP   # AP 뷰 보정 (+0.02)
    else:
        supplement_threshold = CTR_SUPPLEMENT_PA   # PA 뷰 (현행)

    if ctr < supplement_threshold:
        return detections

    # 이미 Cardiomegaly 탐지가 있으면 보충 불필요
    has_cardiomegaly = any(
        d.get("class_name") == "Cardiomegaly" for d in detections
    )
    if has_cardiomegaly:
        return detections

    # 마스크에서 심장 bbox 계산 (class_id=3)
    # pipeline에서 "seg_mask_raw" 키로 저장됨
    mask_raw = seg_result.get("seg_mask_raw") or seg_result.get("mask_raw")
    if mask_raw is None:
        return detections

    heart_bbox_mask = _mask_bbox(mask_raw, [3])
    if heart_bbox_mask is None:
        return detections

    # 마스크 좌표 → 원본 이미지 좌표로 스케일링
    # original_size는 [H, W] 순서 (model.py에서 [pil_image.height, pil_image.width])
    original_size = seg_result.get("original_size", [0, 0])
    orig_h, orig_w = original_size[0], original_size[1]
    if orig_w == 0 or orig_h == 0:
        return detections

    mask_h, mask_w = mask_raw.shape
    sx = orig_w / mask_w
    sy = orig_h / mask_h

    heart_bbox = [
        round(heart_bbox_mask[0] * sx),
        round(heart_bbox_mask[1] * sy),
        round(heart_bbox_mask[2] * sx),
        round(heart_bbox_mask[3] * sy),
    ]

    # 합성 Cardiomegaly 탐지 추가
    evidence_note = f"CTR={ctr:.3f} >= {supplement_threshold} (view={view})"
    if view == "AP":
        evidence_note += " [AP correction: threshold +0.02]"

    synthetic_det = {
        "class_name": "Cardiomegaly",
        "confidence": float(round(min(0.99, ctr), 4)),
        "bbox": [float(v) for v in heart_bbox],
        "color": "#ef4444",
        "source": "ctr_supplement",
        "bbox_corrected": False,
        "evidence": evidence_note,
    }

    result = list(detections)
    result.append(synthetic_det)
    return result


def filter_edge_detections(
    detections: list[dict],
    image_size: list[int],
    margin_ratio: float = YOLO_EDGE_MARGIN,
) -> list[dict]:
    """
    이미지 가장자리에 위치한 Other_lesion 탐지를 필터링.

    문제: YOLO가 이미지 가장자리(collimation 영역 등)에서
          Other_lesion FP를 생성 (10건).
    해결: bbox 중심이 가장자리 margin 내에 있는 Other_lesion을 제거.
          임상적으로 중요한 클래스(Pneumothorax 등)는 제거하지 않음.

    Args:
        detections: YOLO 탐지 결과 리스트
        image_size: [width, height] 원본 이미지 크기
        margin_ratio: 가장자리 margin 비율 (기본 10%)

    Returns:
        필터링된 탐지 결과 리스트 (원본 수정하지 않음)
    """
    if not detections or not image_size:
        return detections

    w, h = image_size[0], image_size[1]
    margin_x = w * margin_ratio
    margin_y = h * margin_ratio

    filtered = []
    for det in detections:
        bbox = det.get("bbox", [0, 0, 0, 0])
        cx = (bbox[0] + bbox[2]) / 2
        cy = (bbox[1] + bbox[3]) / 2

        # 가장자리 체크
        at_edge = (cx < margin_x or cx > w - margin_x or
                   cy < margin_y or cy > h - margin_y)

        # Other_lesion만 가장자리에서 제거
        if at_edge and det.get("class_name") == "Other_lesion":
            continue

        filtered.append(det)

    return filtered
