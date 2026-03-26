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


# ── 마스크 후처리: 파편 제거 + 횡격막 클리핑 ──────────────────
def _postprocess_mask(mask: np.ndarray) -> np.ndarray:
    """
    마스크 후처리: connected component 파편 제거 + Heart 횡격막 클리핑.

    1) 각 클래스(L Lung, R Lung, Heart)에서 가장 큰 연결 컴포넌트만 유지,
       작은 파편(아티팩트) 제거.
    2) Heart(class 3)가 폐 하단 경계 아래로 확장된 경우 클리핑.
    """
    try:
        from scipy import ndimage as _ndi
        _HAS_SCIPY = True
    except ImportError:
        _HAS_SCIPY = False

    cleaned = mask.copy()

    # ── Step 1: 각 클래스별 최대 connected component만 유지 ──
    for cls_id in [1, 2, 3]:  # L Lung, R Lung, Heart
        cls_mask = (cleaned == cls_id)
        if not cls_mask.any():
            continue

        if _HAS_SCIPY:
            labeled, n_components = _ndi.label(cls_mask)
            if n_components > 1:
                sizes = _ndi.sum(cls_mask, labeled, range(1, n_components + 1))
                largest = int(np.argmax(sizes)) + 1
                cleaned[cls_mask & (labeled != largest)] = 0
        else:
            # Pure numpy fallback: flood-fill via iterative BFS
            # 각 연결 영역의 픽셀 수를 세어 가장 큰 것만 유지
            visited = np.zeros_like(cls_mask, dtype=bool)
            components = []  # list of (pixel_count, set_of_coords)
            rows_idx, cols_idx = np.where(cls_mask)
            for r, c in zip(rows_idx, cols_idx):
                if visited[r, c]:
                    continue
                # BFS
                queue = [(r, c)]
                visited[r, c] = True
                pixels = []
                while queue:
                    cr, cc = queue.pop(0)
                    pixels.append((cr, cc))
                    for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        nr, nc = cr + dr, cc + dc
                        if 0 <= nr < cls_mask.shape[0] and 0 <= nc < cls_mask.shape[1]:
                            if cls_mask[nr, nc] and not visited[nr, nc]:
                                visited[nr, nc] = True
                                queue.append((nr, nc))
                components.append(pixels)
            if len(components) > 1:
                largest_comp = max(components, key=len)
                largest_set = set(map(tuple, largest_comp))
                for comp in components:
                    if comp is not largest_comp:
                        for r, c in comp:
                            cleaned[r, c] = 0

    # ── Step 2: Heart 횡격막 클리핑 ──
    # 폐(class 1, 2)의 하단 경계를 찾아, Heart가 그 아래로 넘어가면 제거
    lung_mask = (cleaned == 1) | (cleaned == 2)
    heart_mask = (cleaned == 3)

    if lung_mask.any() and heart_mask.any():
        # 폐가 존재하는 행 중 가장 아래 행 = 폐 하단 경계
        lung_rows = np.where(lung_mask.any(axis=1))[0]
        lung_lower_boundary = int(lung_rows[-1])
        small_margin = 5  # 320px 기준 약 1.5% 여유

        # Heart 픽셀 중 lung_lower_boundary + margin 아래에 있는 것을 제거
        clip_row = lung_lower_boundary + small_margin
        if clip_row < cleaned.shape[0]:
            heart_below = heart_mask.copy()
            heart_below[:clip_row, :] = False  # clip_row 위는 유지
            if heart_below.any():
                cleaned[heart_below] = 0  # 복부로 넘어간 Heart 제거

    return cleaned


# ── 마스크 → base64 PNG ───────────────────────────────────
def _mask_to_base64(mask: np.ndarray, original_size: tuple = None) -> str:
    """(H, W) uint8 마스크를 반투명 RGBA PNG base64로 인코딩.
    배경(class 0)은 완전 투명, 장기 영역은 반투명 오버레이.
    original_size가 주어지면 원본 이미지 크기로 리사이즈하여 정확한 오버레이 정렬 보장."""
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
    # 원본 종횡비로 리사이즈 — 320x320 정사각형 마스크를 원본 비율에 맞춤
    # 전송 효율을 위해 장변 최대 1024px로 제한
    if original_size is not None:
        orig_h, orig_w = original_size
        max_side = 1024
        scale = min(max_side / orig_w, max_side / orig_h, 1.0)
        target_w = max(1, int(orig_w * scale))
        target_h = max(1, int(orig_h * scale))
        img = img.resize((target_w, target_h), Image.NEAREST)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# ── 좌우 폐 분리 후처리 ────────────────────────────────────
def _cleanup_lung_mask(mask: np.ndarray) -> np.ndarray:
    """
    좌우 폐(class 1, 2) 영역이 겹치는 문제를 수정.

    방법: 심장(class 3) 또는 흉곽 중심선을 기준으로,
    중심선 왼쪽의 폐 픽셀은 class 1(left_lung),
    오른쪽은 class 2(right_lung)로 강제 재할당.

    참고: UNet 모델의 class 1 = viewer 왼쪽 폐 = patient's right lung
    """
    lung_mask = (mask == 1) | (mask == 2)
    if not lung_mask.any():
        return mask

    # 중심선 결정: 심장 중심 또는 폐 영역 좌우 중심
    heart_mask = (mask == 3)
    if heart_mask.any():
        heart_cols = np.where(heart_mask.any(axis=0))[0]
        midline = int((heart_cols[0] + heart_cols[-1]) / 2)
    else:
        lung_cols = np.where(lung_mask.any(axis=0))[0]
        midline = int((lung_cols[0] + lung_cols[-1]) / 2)

    # 중심선 기준으로 좌우 재할당
    cleaned = mask.copy()
    # 중심선 왼쪽(viewer left)의 모든 폐 → class 1
    left_region = lung_mask & (np.arange(mask.shape[1])[np.newaxis, :] < midline)
    cleaned[left_region] = 1
    # 중심선 오른쪽(viewer right)의 모든 폐 → class 2
    right_region = lung_mask & (np.arange(mask.shape[1])[np.newaxis, :] >= midline)
    cleaned[right_region] = 2

    return cleaned


# ── CTR (Cardiothoracic Ratio) 계산 ─────────────────────────
def _compute_ctr(mask: np.ndarray) -> dict:
    """
    CTR = heart_width / thorax_width

    heart_width: 심장 영역(class 3)의 최대 수평 폭.
    thorax_width: 양쪽 폐(class 1+2)의 최대 수평 폭.

    정상: < 0.5, 심비대: >= 0.5

    Returns:
        dict with 'ctr' ratio and coordinate info for SVG overlay:
        - heart_left_x, heart_right_x, heart_row: 심장 최대폭 행 좌표 (mask 320x320 좌표)
        - thorax_left_x, thorax_right_x, thorax_row: 흉곽 최대폭 행 좌표 (mask 320x320 좌표)
        - heart_width, thorax_width: 픽셀 폭
    """
    heart_mask = (mask == 3)
    lung_mask = (mask == 1) | (mask == 2)

    empty = {
        "ctr": 0.0,
        "heart_left_x": 0, "heart_right_x": 0, "heart_row": 0,
        "thorax_left_x": 0, "thorax_right_x": 0, "thorax_row": 0,
        "heart_width": 0, "thorax_width": 0,
    }

    if not heart_mask.any() or not lung_mask.any():
        return empty

    # 심장 — 각 행별 수평 폭, 최대값 + 해당 좌표
    heart_rows = np.where(heart_mask.any(axis=1))[0]
    best_heart_width = 0
    heart_left_x, heart_right_x, heart_row = 0, 0, 0
    for r in heart_rows:
        cols = np.where(heart_mask[r])[0]
        w = cols[-1] - cols[0]
        if w > best_heart_width:
            best_heart_width = w
            heart_left_x = int(cols[0])
            heart_right_x = int(cols[-1])
            heart_row = int(r)

    # 흉곽 — 양쪽 폐 전체의 최대 수평 범위 + 해당 좌표
    lung_rows = np.where(lung_mask.any(axis=1))[0]
    best_thorax_width = 0
    thorax_left_x, thorax_right_x, thorax_row = 0, 0, 0
    for r in lung_rows:
        cols = np.where(lung_mask[r])[0]
        w = cols[-1] - cols[0]
        if w > best_thorax_width:
            best_thorax_width = w
            thorax_left_x = int(cols[0])
            thorax_right_x = int(cols[-1])
            thorax_row = int(r)

    thorax_width = best_thorax_width if best_thorax_width > 0 else 1
    ctr = float(best_heart_width) / float(thorax_width)

    return {
        "ctr": round(ctr, 4),
        "heart_left_x": heart_left_x,
        "heart_right_x": heart_right_x,
        "heart_row": heart_row,
        "thorax_left_x": thorax_left_x,
        "thorax_right_x": thorax_right_x,
        "thorax_row": thorax_row,
        "heart_width": best_heart_width,
        "thorax_width": thorax_width,
    }


# ── CP angle (costophrenic angle) 계산 ──────────────────────
def _compute_cp_angle(mask: np.ndarray, lung_class: int) -> dict:
    """
    Costophrenic angle 근사 계산.

    날카로운 CP angle (> ~30도): 정상
    무딘(blunted) CP angle (< ~30도): 흉수(pleural effusion) 의심

    Args:
        mask: 세그멘테이션 마스크 (H, W)
        lung_class: 1 (left lung) 또는 2 (right lung)

    Returns:
        dict with 'angle_degrees' and 'cp_point' (x, y) in mask 320x320 좌표.
        폐 영역이 없으면 angle_degrees=0.0.
    """
    empty = {"angle_degrees": 0.0, "cp_point_x": 0, "cp_point_y": 0}

    lung_mask = (mask == lung_class)

    if not lung_mask.any():
        return empty

    rows = np.where(lung_mask.any(axis=1))[0]
    bottom_row = rows[-1]

    # 최하단 부근(하위 10% 행)
    lower_region_start = max(rows[0], int(bottom_row - 0.1 * (bottom_row - rows[0])))
    lower_rows = rows[rows >= lower_region_start]

    if len(lower_rows) < 2:
        return empty

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
        return empty

    cp_point = lateral_points[-1]
    top_point = lateral_points[0]

    bottom_cols = np.where(lung_mask[bottom_row])[0]
    if len(bottom_cols) == 0:
        return empty

    if lung_class == 1:
        diaphragm_point = (bottom_row, bottom_cols[-1])
    else:
        diaphragm_point = (bottom_row, bottom_cols[0])

    vec_a = np.array([top_point[0] - cp_point[0], top_point[1] - cp_point[1]], dtype=np.float64)
    vec_b = np.array([diaphragm_point[0] - cp_point[0], diaphragm_point[1] - cp_point[1]], dtype=np.float64)

    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)

    if norm_a < 1e-6 or norm_b < 1e-6:
        return empty

    cos_angle = np.dot(vec_a, vec_b) / (norm_a * norm_b)
    cos_angle = np.clip(cos_angle, -1.0, 1.0)
    angle_deg = float(np.degrees(np.arccos(cos_angle)))

    return {
        "angle_degrees": round(angle_deg, 2),
        "cp_point_x": int(cp_point[1]),   # col → x
        "cp_point_y": int(cp_point[0]),   # row → y
    }


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


# ── 종격동(Mediastinum) 폭 계산 ────────────────────────────
def _compute_mediastinum(mask: np.ndarray) -> dict:
    """
    종격동 영역(class 4)의 최대 수평 폭과 좌표(mask 320x320).
    class 4가 없으면 심장(class 3)의 상부 1/3 영역으로 대체 추정.
    """
    med_mask = (mask == 4)

    if med_mask.any():
        rows = np.where(med_mask.any(axis=1))[0]
        best_w = 0
        x_left, x_right, y_level = 0, 0, 0
        for r in rows:
            cols = np.where(med_mask[r])[0]
            w = cols[-1] - cols[0]
            if w > best_w:
                best_w = w
                x_left = int(cols[0])
                x_right = int(cols[-1])
                y_level = int(r)
        return {
            "x_left": x_left, "x_right": x_right,
            "measurement_y_level": y_level, "width_px": best_w,
            "status": "normal" if best_w < 80 else "widened",  # 320 기준 ~25% 폭
        }

    # fallback: 두 폐 사이 간격 (상부 20~35% 영역)으로 종격동 추정
    # 심장 상부를 사용하면 심비대 시 왜곡됨 — 폐 간 공간이 더 정확
    lung_mask = (mask == 1) | (mask == 2)
    if not lung_mask.any():
        return {"x_left": 0, "x_right": 0, "measurement_y_level": 0, "width_px": 0, "status": "unmeasurable"}

    h, w = mask.shape
    # 상부 흉곽 (15~45% 높이) — 대혈관/기관/기관지 높이
    upper_start = int(h * 0.15)
    upper_end = int(h * 0.45)

    best_gap = 0
    x_left, x_right, y_level = 0, 0, 0
    for r in range(upper_start, upper_end):
        row = lung_mask[r]
        if not row.any():
            continue
        lung_cols = np.where(row)[0]
        # 폐 영역 사이의 gap (종격동) 찾기
        # CXR은 방사선학적 반전: 이미지 왼쪽=환자 오른쪽
        # Class 1(L Lung)=이미지 왼쪽, Class 2(R Lung)=이미지 오른쪽
        l_lung_row = (mask[r] == 1)  # L Lung (이미지 왼쪽)
        r_lung_row = (mask[r] == 2)  # R Lung (이미지 오른쪽)
        if l_lung_row.any() and r_lung_row.any():
            l_cols = np.where(l_lung_row)[0]
            r_cols = np.where(r_lung_row)[0]
            gap_left = int(l_cols[-1])   # L Lung 우측 경계 (이미지 기준)
            gap_right = int(r_cols[0])   # R Lung 좌측 경계 (이미지 기준)
            gap = gap_right - gap_left
            if gap > best_gap and gap > 5:
                best_gap = gap
                x_left = gap_left
                x_right = gap_right
                y_level = r

    if best_gap == 0:
        return {"x_left": 0, "x_right": 0, "measurement_y_level": 0, "width_px": 0, "status": "unmeasurable"}

    return {
        "x_left": x_left, "x_right": x_right,
        "measurement_y_level": y_level, "width_px": best_gap,
        "status": "estimated",
    }


# ── 기관(Trachea) / 중심선 편위 ───────────────────────────
def _compute_trachea(mask: np.ndarray) -> dict:
    """
    흉곽 중심선 vs 종격동 중심을 비교하여 기관 편위를 판단.
    좌표는 mask 320x320.
    """
    lung_mask = (mask == 1) | (mask == 2)
    if not lung_mask.any():
        return {
            "thorax_center_x": 0, "mediastinum_center_x": 0,
            "midline": True, "deviation_direction": None, "alert": False,
        }

    # 흉곽 중심: 폐 영역 전체의 좌우 중심
    lung_cols = np.where(lung_mask.any(axis=0))[0]
    thorax_center_x = int((lung_cols[0] + lung_cols[-1]) / 2)

    # 종격동 중심: class 4 우선, 없으면 상부 폐 간격의 중심
    med_mask = (mask == 4)
    if med_mask.any():
        med_cols = np.where(med_mask.any(axis=0))[0]
        mediastinum_center_x = int((med_cols[0] + med_cols[-1]) / 2)
    else:
        # 상부 흉곽(20~35%)에서 R Lung/L Lung 사이 중심 = 종격동/기관 중심
        h_mask = mask.shape[0]
        upper_start = int(h_mask * 0.15)
        upper_end = int(h_mask * 0.45)
        gap_centers = []
        for r in range(upper_start, upper_end):
            l_lung_row = (mask[r] == 1)  # L Lung (이미지 왼쪽)
            r_lung_row = (mask[r] == 2)  # R Lung (이미지 오른쪽)
            if l_lung_row.any() and r_lung_row.any():
                gap_left = np.where(l_lung_row)[0][-1]   # L Lung 우측 경계
                gap_right = np.where(r_lung_row)[0][0]    # R Lung 좌측 경계
                if gap_right > gap_left:
                    gap_centers.append((gap_left + gap_right) / 2)
        if gap_centers:
            mediastinum_center_x = int(np.mean(gap_centers))
        else:
            mediastinum_center_x = thorax_center_x

    deviation_px = abs(mediastinum_center_x - thorax_center_x)
    # 320px 기준에서 5% (16px) 이내면 정중선 — 폐 비대칭에 의한 오차 허용
    midline = deviation_px < 16
    deviation_direction = None
    if not midline:
        deviation_direction = "left" if mediastinum_center_x < thorax_center_x else "right"

    # 기관 y 범위 (mask 좌표): 쇄골(10%)~carina(33%)
    h_mask = mask.shape[0]
    trachea_y_start = int(h_mask * 0.10)
    trachea_y_end = int(h_mask * 0.33)

    return {
        "thorax_center_x": thorax_center_x,
        "mediastinum_center_x": mediastinum_center_x,
        "midline": midline,
        "deviation_direction": deviation_direction,
        "alert": deviation_px >= 24,  # 강한 편위 (7.5% 이상)
        "trachea_y_start": trachea_y_start,  # 쇄골 레벨 (mask 좌표)
        "trachea_y_end": trachea_y_end,      # carina 레벨 (mask 좌표)
    }


# ── 횡격막(Diaphragm) 최고점 계산 ─────────────────────────
def _compute_diaphragm(mask: np.ndarray) -> dict:
    """
    좌/우 폐 하단 경계(횡격막 돔)의 최고점 좌표(mask 320x320).
    """
    result = {"status": "unmeasurable", "right_dome_x": 0, "right_dome_y": 0, "left_dome_x": 0, "left_dome_y": 0}

    for lung_class, side in [(2, "right"), (1, "left")]:
        lm = (mask == lung_class)
        if not lm.any():
            continue
        rows = np.where(lm.any(axis=1))[0]
        bottom_row = rows[-1]
        # 횡격막 돔 = 폐 하단 경계에서 가장 높은(작은 row) 지점의 중앙 위치
        # 하위 20% 영역에서 각 열의 최하단을 추적
        lower_start = max(rows[0], int(bottom_row - 0.2 * (bottom_row - rows[0])))
        lower_rows = rows[rows >= lower_start]
        if len(lower_rows) == 0:
            continue
        # 각 행의 중앙 col 을 추적, 가장 아래(bottom_row) 행의 중앙이 돔 위치
        bottom_cols = np.where(lm[bottom_row])[0]
        if len(bottom_cols) == 0:
            continue
        dome_x = int((bottom_cols[0] + bottom_cols[-1]) / 2)
        dome_y = int(bottom_row)
        result[f"{side}_dome_x"] = dome_x
        result[f"{side}_dome_y"] = dome_y

    if result["right_dome_y"] > 0 or result["left_dome_y"] > 0:
        # 좌우 높이 차이로 상태 결정
        if result["right_dome_y"] > 0 and result["left_dome_y"] > 0:
            diff = abs(result["right_dome_y"] - result["left_dome_y"])
            if diff < 10:  # 320 기준
                result["status"] = "normal"
            else:
                result["status"] = "elevated_right" if result["right_dome_y"] < result["left_dome_y"] else "elevated_left"
        else:
            result["status"] = "partial"

    return result


# ── 측정 좌표를 원본 이미지 크기로 스케일링 ──────────────────
def _build_structured_measurements(
    ctr_info: dict,
    cp_left_info: dict,
    cp_right_info: dict,
    med_info: dict,
    tra_info: dict,
    dia_info: dict,
    original_size: tuple,
) -> dict:
    """
    320x320 마스크 좌표를 원본 이미지 좌표로 스케일링하여
    프론트엔드 drawMeasurements()가 기대하는 구조체를 생성.

    Args:
        original_size: (orig_h, orig_w)
    """
    orig_h, orig_w = original_size
    sx = orig_w / 320.0
    sy = orig_h / 320.0

    def scale_x(v): return round(v * sx)
    def scale_y(v): return round(v * sy)

    # mediastinum 구조체
    mediastinum = {
        "x_left": scale_x(med_info["x_left"]),
        "x_right": scale_x(med_info["x_right"]),
        "measurement_y_level": scale_y(med_info["measurement_y_level"]),
        "width_px": scale_x(med_info["width_px"]),
        "status": med_info["status"],
    }

    # trachea 구조체 — y 좌표도 스케일링
    trachea = {
        "thorax_center_x": scale_x(tra_info["thorax_center_x"]),
        "mediastinum_center_x": scale_x(tra_info["mediastinum_center_x"]),
        "midline": tra_info["midline"],
        "deviation_direction": tra_info["deviation_direction"],
        "alert": tra_info["alert"],
        "trachea_y_start": scale_y(tra_info.get("trachea_y_start", 0)),
        "trachea_y_end": scale_y(tra_info.get("trachea_y_end", 0)),
    }

    # cp_angle 구조체
    def _cp_struct(info, side_label):
        angle = info["angle_degrees"]
        return {
            "point": [scale_x(info["cp_point_x"]), scale_y(info["cp_point_y"])],
            "angle_degrees": angle,
            "status": "blunted" if 0 < angle < 30 else "normal" if angle >= 30 else "unmeasurable",
        }

    cp_angle = {
        "right": _cp_struct(cp_right_info, "right"),
        "left": _cp_struct(cp_left_info, "left"),
    }

    # diaphragm 구조체
    diaphragm = {
        "status": dia_info["status"],
        "right_dome_point": [scale_x(dia_info["right_dome_x"]), scale_y(dia_info["right_dome_y"])],
        "left_dome_point": [scale_x(dia_info["left_dome_x"]), scale_y(dia_info["left_dome_y"])],
    }

    # heart/thorax width도 원본 스케일로
    heart_width_orig = scale_x(ctr_info["heart_width"])
    thorax_width_orig = scale_x(ctr_info["thorax_width"])

    # CTR 측정선 좌표 (프론트엔드 SVG 오버레이용)
    ctr_lines = {
        "heart_left_x": scale_x(ctr_info.get("heart_left_x", 0)),
        "heart_right_x": scale_x(ctr_info.get("heart_right_x", 0)),
        "heart_row": scale_y(ctr_info.get("heart_row", 0)),
        "thorax_left_x": scale_x(ctr_info.get("thorax_left_x", 0)),
        "thorax_right_x": scale_x(ctr_info.get("thorax_right_x", 0)),
        "thorax_row": scale_y(ctr_info.get("thorax_row", 0)),
    }

    return {
        "mediastinum": mediastinum,
        "trachea": trachea,
        "cp_angle": cp_angle,
        "diaphragm": diaphragm,
        "ctr_lines": ctr_lines,
        "heart_width_px": heart_width_orig,
        "thorax_width_px": thorax_width_orig,
    }


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

    # ── 좌우 폐 분리 후처리 ──
    # UNet이 class 1(left_lung)과 class 2(right_lung)를 겹치게 예측하는 경우 보정.
    # 심장/종격동 중심선 기준으로 좌우를 깔끔히 분리.
    mask = _cleanup_lung_mask(mask)

    # ── 마스크 후처리: 파편 제거 + Heart 횡격막 클리핑 ──
    # Phase 3: connected component로 작은 파편 제거, Heart가 폐 아래로
    # 확장된 경우 클리핑하여 CTR/측정 정확도 향상.
    mask = _postprocess_mask(mask)

    # 마스크 base64 인코딩 — 원본 크기로 리사이즈하여 오버레이 정렬 보장
    orig_size = (pil_image.height, pil_image.width)
    mask_b64 = _mask_to_base64(mask, original_size=orig_size)

    # 임상 측정값 (좌표 포함 dict 반환)
    ctr_info = _compute_ctr(mask)
    cp_left_info = _compute_cp_angle(mask, lung_class=1)
    cp_right_info = _compute_cp_angle(mask, lung_class=2)
    lung_ratio = _compute_lung_area_ratio(mask)
    class_areas = _compute_class_areas(mask)
    med_info = _compute_mediastinum(mask)
    tra_info = _compute_trachea(mask)
    dia_info = _compute_diaphragm(mask)

    # 스칼라 값 추출 (기존 호환)
    ctr = ctr_info["ctr"]
    cp_left = cp_left_info["angle_degrees"]
    cp_right = cp_right_info["angle_degrees"]

    # 프론트엔드 SVG 오버레이용 구조체 (원본 이미지 좌표로 스케일링)
    structured = _build_structured_measurements(
        ctr_info, cp_left_info, cp_right_info,
        med_info, tra_info, dia_info,
        original_size=orig_size,
    )

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
        "seg_mask_raw": mask,  # (320, 320) uint8 — YOLO bbox 후처리용
        "original_size": [pil_image.height, pil_image.width],  # [H, W] — SVG viewBox 용
        "measurements": {
            # 기존 스칼라 값 (호환 유지)
            "ctr": ctr,
            "ctr_status": "normal" if ctr < 0.5 else "cardiomegaly",
            "cp_angle_left": cp_left,
            "cp_angle_right": cp_right,
            "lung_area_ratio": lung_ratio,
            "heart_width_px": structured["heart_width_px"],
            "thorax_width_px": structured["thorax_width_px"],
            "right_lung_area_px": class_areas.get("right_lung", 0),
            "left_lung_area_px": class_areas.get("left_lung", 0),
            "heart_area_px": class_areas.get("heart", 0),
            # 프론트엔드 drawMeasurements() SVG 오버레이용 구조체
            "mediastinum": structured["mediastinum"],
            "trachea": structured["trachea"],
            "cp_angle": structured["cp_angle"],
            "diaphragm": structured["diaphragm"],
        },
        "class_areas": class_areas,
        "view": view,
        "age_pred": round(age, 1) if age is not None else None,
        "sex_pred": sex,
        "processing_time": elapsed,
    }
