"""
Layer 1 Segmentation Lambda — 개별 엔드포인트
입력: CXR 이미지 (base64 또는 S3 경로)
출력: 세그멘테이션 마스크 + CTR + 측정값
"""
import os
import json
import base64
import io
import time
import boto3
import numpy as np
from PIL import Image

# 글로벌 캐시
model = None
s3_client = boto3.client('s3', region_name='ap-northeast-2')

WORK_BUCKET = os.environ.get(
    'WORK_BUCKET',
    'pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an'
)
MODEL_S3_PREFIX = os.environ.get(
    'MODEL_S3_PREFIX',
    'models/segmentation/chest-x-ray-basic'
)
SAMPLE_S3_PREFIX = os.environ.get(
    'SAMPLE_S3_PREFIX',
    'web/test-layer1/samples'
)
MODEL_LOCAL = '/tmp/segmentation_model'


def load_model():
    """모델 로드 (cold start 시 S3에서 다운로드, warm start 시 캐시 사용)"""
    global model
    if model is not None:
        return model

    import torch
    from transformers import AutoModel

    # S3에서 /tmp로 다운로드
    if not os.path.exists(os.path.join(MODEL_LOCAL, 'config.json')):
        print('[Cold Start] S3에서 모델 다운로드...')
        start = time.time()
        os.makedirs(MODEL_LOCAL, exist_ok=True)

        paginator = s3_client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=WORK_BUCKET, Prefix=MODEL_S3_PREFIX):
            for obj in page.get('Contents', []):
                rel = obj['Key'][len(MODEL_S3_PREFIX) + 1:]
                if not rel:
                    continue
                local_path = os.path.join(MODEL_LOCAL, rel)
                local_dir = os.path.dirname(local_path)
                if local_dir:
                    os.makedirs(local_dir, exist_ok=True)
                s3_client.download_file(WORK_BUCKET, obj['Key'], local_path)

        print(f'[Cold Start] 다운로드 완료: {time.time() - start:.1f}초')

    print('[Load] 모델 로드 중...')
    start = time.time()
    model = AutoModel.from_pretrained(MODEL_LOCAL, trust_remote_code=True)
    model.eval()
    print(f'[Load] 완료: {time.time() - start:.1f}초')

    return model


def get_image(event):
    """요청에서 이미지 추출 (base64 / S3 key 지원)"""
    body = event
    if isinstance(event.get('body'), str):
        body = json.loads(event['body'])
    elif isinstance(event.get('body'), dict):
        body = event['body']

    # S3 key로 이미지 로드
    if 's3_key' in body:
        key = body['s3_key']
        bucket = body.get('bucket', WORK_BUCKET)
        resp = s3_client.get_object(Bucket=bucket, Key=key)
        img = Image.open(io.BytesIO(resp['Body'].read())).convert('RGB')
        return img

    # base64 이미지
    if 'image_base64' in body:
        img_data = base64.b64decode(body['image_base64'])
        img = Image.open(io.BytesIO(img_data)).convert('RGB')
        return img

    raise ValueError('image_base64 또는 s3_key 필요')


def max_horizontal_width(binary_mask):
    """마스크에서 최대 가로폭"""
    if not binary_mask.any():
        return 0
    rows = binary_mask.any(axis=1)
    mw = 0
    for r in np.where(rows)[0]:
        cols = np.where(binary_mask[r])[0]
        mw = max(mw, cols[-1] - cols[0] + 1)
    return mw


def measure_mediastinum(right_lung, left_lung):
    """종격동 너비 측정
    상부 종격동(폐 상단 20~35%) 영역에서 좌우 폐 내측 경계 사이 거리.
    종격동 = 양쪽 폐 사이 공간 (기관, 대동맥, 심장 상부 위치).
    """
    rl_rows = np.where(right_lung.any(axis=1))[0]
    ll_rows = np.where(left_lung.any(axis=1))[0]
    empty = {'width_px': 0, 'measurement_y_level': 0,
             'x_left': 0, 'x_right': 0, 'status': 'unmeasurable'}
    if len(rl_rows) == 0 or len(ll_rows) == 0:
        return empty

    top = max(rl_rows[0], ll_rows[0])
    bottom = min(rl_rows[-1], ll_rows[-1])
    lung_height = bottom - top
    if lung_height <= 0:
        return empty

    y_start = top + int(lung_height * 0.20)
    y_end = top + int(lung_height * 0.35)

    widths = []
    for y in range(y_start, min(y_end + 1, right_lung.shape[0])):
        rl_cols = np.where(right_lung[y])[0]
        ll_cols = np.where(left_lung[y])[0]
        if len(rl_cols) == 0 or len(ll_cols) == 0:
            continue
        # 두 폐 사이 갭 (방향 무관)
        if rl_cols.max() < ll_cols.min():
            x_l, x_r = int(rl_cols.max()), int(ll_cols.min())
        elif ll_cols.max() < rl_cols.min():
            x_l, x_r = int(ll_cols.max()), int(rl_cols.min())
        else:
            continue
        w = x_r - x_l
        if w > 0:
            widths.append((w, y, x_l, x_r))

    if not widths:
        return empty

    widths.sort(key=lambda t: t[0])
    w, y_level, x_l, x_r = widths[len(widths) // 2]
    return {
        'width_px': int(w), 'measurement_y_level': int(y_level),
        'x_left': int(x_l), 'x_right': int(x_r), 'status': 'normal'
    }


def measure_trachea_shift(right_lung, left_lung):
    """기관/종격동 중심선 편위 측정
    상부 종격동 중심 vs 흉곽 전체 중심의 차이.
    |편위비율| >= 0.03 → 편위, >= 0.08 → 심각 (tension pneumothorax 등 의심)
    """
    rl_rows = np.where(right_lung.any(axis=1))[0]
    ll_rows = np.where(left_lung.any(axis=1))[0]
    empty = {
        'mediastinum_center_x': 0, 'thorax_center_x': 0,
        'deviation_px': 0, 'deviation_ratio': 0.0,
        'midline': True, 'deviation_direction': 'none', 'alert': False
    }
    if len(rl_rows) == 0 or len(ll_rows) == 0:
        return empty

    top = max(rl_rows[0], ll_rows[0])
    bottom = min(rl_rows[-1], ll_rows[-1])
    lung_height = bottom - top
    if lung_height <= 0:
        return empty

    y_start = top + int(lung_height * 0.10)
    y_end = top + int(lung_height * 0.30)

    med_centers = []
    for y in range(y_start, min(y_end + 1, right_lung.shape[0])):
        rl_cols = np.where(right_lung[y])[0]
        ll_cols = np.where(left_lung[y])[0]
        if len(rl_cols) == 0 or len(ll_cols) == 0:
            continue
        if rl_cols.max() < ll_cols.min():
            med_centers.append((rl_cols.max() + ll_cols.min()) / 2.0)
        elif ll_cols.max() < rl_cols.min():
            med_centers.append((ll_cols.max() + rl_cols.min()) / 2.0)

    if not med_centers:
        return empty

    med_center = float(np.mean(med_centers))
    all_lung = right_lung | left_lung
    lung_cols = np.where(all_lung.any(axis=0))[0]
    if len(lung_cols) == 0:
        return empty
    thorax_center = float((lung_cols[0] + lung_cols[-1]) / 2.0)
    thorax_width = float(lung_cols[-1] - lung_cols[0])
    if thorax_width == 0:
        return empty

    dev_px = round(med_center - thorax_center, 1)
    dev_ratio = round(dev_px / thorax_width, 4)
    abs_r = abs(dev_ratio)
    midline = abs_r < 0.03
    direction = 'none' if midline else ('right' if dev_px > 0 else 'left')
    return {
        'mediastinum_center_x': round(med_center, 1),
        'thorax_center_x': round(thorax_center, 1),
        'deviation_px': dev_px, 'deviation_ratio': dev_ratio,
        'midline': midline, 'deviation_direction': direction,
        'alert': abs_r >= 0.08
    }


def measure_cp_angles(right_lung, left_lung):
    """CP Angle (Costophrenic Angle) 분석
    각 폐 하단 외측 꼭지점에서 3점 각도법으로 측정.
    CP angle > 70° → blunted (흉수 의심, Pleural Effusion 첫 징후)
    """
    image_w = right_lung.shape[1]
    result = {}

    for side, lung_mask in [('right', right_lung), ('left', left_lung)]:
        rows = np.where(lung_mask.any(axis=1))[0]
        if len(rows) < 10:
            result[side] = {'point': [0, 0], 'angle_degrees': 0.0, 'status': 'unmeasurable'}
            continue

        y_min_l, y_max_l = int(rows[0]), int(rows[-1])
        lung_h = y_max_l - y_min_l
        cx = float(np.mean(np.where(lung_mask)[1]))
        lateral_is_left = cx < image_w / 2

        # CP 꼭지점: 하단 15%에서 가장 lateral + bottom 점
        search = max(int(lung_h * 0.15), 10)
        cp_x, cp_y = None, None
        for y in range(y_max_l, max(y_max_l - search, y_min_l), -1):
            cols = np.where(lung_mask[y])[0]
            if len(cols) == 0:
                continue
            cand = int(cols[0]) if lateral_is_left else int(cols[-1])
            if cp_x is None:
                cp_x, cp_y = cand, y
            elif (lateral_is_left and cand <= cp_x) or (not lateral_is_left and cand >= cp_x):
                cp_x, cp_y = cand, y

        if cp_x is None:
            result[side] = {'point': [0, 0], 'angle_degrees': 0.0, 'status': 'unmeasurable'}
            continue

        arm = max(30, int(lung_h * 0.08))

        # Arm 1: lateral wall 방향 (위로)
        a1_y = max(cp_y - arm, y_min_l)
        c1 = np.where(lung_mask[a1_y])[0]
        a1_x = (int(c1[0]) if lateral_is_left else int(c1[-1])) if len(c1) > 0 else cp_x

        # Arm 2: diaphragm 방향 (내측으로)
        a2_x = (cp_x + arm) if lateral_is_left else (cp_x - arm)
        a2_x = max(0, min(a2_x, lung_mask.shape[1] - 1))
        c2 = np.where(lung_mask[:, a2_x])[0]
        a2_y = int(c2[-1]) if len(c2) > 0 else cp_y

        v1 = np.array([a1_x - cp_x, a1_y - cp_y], dtype=float)
        v2 = np.array([a2_x - cp_x, a2_y - cp_y], dtype=float)
        n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
        if n1 > 0 and n2 > 0:
            cos_a = np.clip(np.dot(v1, v2) / (n1 * n2), -1, 1)
            angle = round(float(np.degrees(np.arccos(cos_a))), 1)
        else:
            angle = 0.0

        status = 'unmeasurable' if angle == 0 else ('blunted' if angle > 70 else 'sharp')
        result[side] = {'point': [cp_x, cp_y], 'angle_degrees': angle, 'status': status}

    return result


def measure_diaphragm(right_lung, left_lung, image_height):
    """횡격막 돔 높이 비교
    각 폐 중앙 30~70% 컬럼에서 하단 경계의 최하점(돔 정점)을 찾아 좌우 비교.
    정상: 우측이 좌측보다 약간 높음 (간이 밀어올림).
    한쪽 3% 이상 높으면 무기폐/횡격막 마비 의심.
    """
    domes = {}
    for side, lung_mask in [('right', right_lung), ('left', left_lung)]:
        cols = np.where(lung_mask.any(axis=0))[0]
        if len(cols) < 10:
            domes[side] = None
            continue
        x_min, x_max = int(cols[0]), int(cols[-1])
        x_s = x_min + int((x_max - x_min) * 0.3)
        x_e = x_min + int((x_max - x_min) * 0.7)

        best_y, best_x = 0, (x_s + x_e) // 2
        for x in range(x_s, x_e + 1):
            col_rows = np.where(lung_mask[:, x])[0]
            if len(col_rows) > 0 and col_rows[-1] > best_y:
                best_y = int(col_rows[-1])
                best_x = x
        domes[side] = [int(best_x), best_y]

    if domes.get('right') is None or domes.get('left') is None:
        return {
            'right_dome_point': domes.get('right') or [0, 0],
            'left_dome_point': domes.get('left') or [0, 0],
            'height_diff_px': 0, 'height_diff_ratio': 0.0,
            'status': 'unmeasurable', 'elevated_side': None
        }

    r_y, l_y = domes['right'][1], domes['left'][1]
    diff = l_y - r_y
    ratio = round(diff / image_height, 4) if image_height > 0 else 0.0
    if abs(ratio) < 0.03:
        status, elevated = 'normal', None
    elif diff > 0:
        status, elevated = 'elevated_right', 'right'
    else:
        status, elevated = 'elevated_left', 'left'

    return {
        'right_dome_point': domes['right'], 'left_dome_point': domes['left'],
        'height_diff_px': int(diff), 'height_diff_ratio': ratio,
        'status': status, 'elevated_side': elevated
    }


def run_segmentation(img):
    """세그멘테이션 추론 + 측정값 계산"""
    import torch

    m = load_model()

    # 전처리
    img_np = np.array(img.convert('L'))
    original_size = img_np.shape[:2]

    x = m.preprocess(img_np)
    x = torch.from_numpy(x).unsqueeze(0).unsqueeze(0).float()

    # 추론
    with torch.inference_mode():
        out = m(x)

    # 마스크
    mask = out['mask'].argmax(dim=1).squeeze(0).cpu().numpy()
    if mask.shape != original_size:
        mask = np.array(
            Image.fromarray(mask.astype(np.uint8)).resize(
                (original_size[1], original_size[0]), Image.NEAREST
            )
        )

    # 좌우 폐 교차 픽셀 보정 (모델이 중심부에서 좌우를 혼동하는 경우 보정)
    # CXR 규약: 이미지 왼쪽 = 환자 오른쪽, class 1 = R Lung, class 2 = L Lung
    lung_mask = (mask == 1) | (mask == 2)
    if lung_mask.any():
        lung_cols = np.where(lung_mask.any(axis=0))[0]
        midline = int((lung_cols[0] + lung_cols[-1]) / 2)
    else:
        midline = mask.shape[1] // 2

    # 이미지 왼쪽에 있는 class 2(L Lung) → class 1(R Lung)으로 재분류
    mask[(mask == 2) & (np.arange(mask.shape[1])[None, :] < midline)] = 1
    # 이미지 오른쪽에 있는 class 1(R Lung) → class 2(L Lung)로 재분류
    mask[(mask == 1) & (np.arange(mask.shape[1])[None, :] >= midline)] = 2

    # 측정값 (class 1=환자 우폐/이미지 왼쪽, 2=환자 좌폐/이미지 오른쪽, 3=심장)
    right_lung = (mask == 1)
    left_lung = (mask == 2)
    heart = (mask == 3)
    thorax = right_lung | left_lung | heart

    hw = max_horizontal_width(heart)
    tw = max_horizontal_width(thorax)
    ctr = hw / tw if tw > 0 else 0.0

    rl_area = int(right_lung.sum())
    ll_area = int(left_lung.sum())

    measurements = {
        'ctr': round(ctr, 4),
        'ctr_status': 'severe_cardiomegaly' if ctr >= 0.60 else ('cardiomegaly' if ctr >= 0.50 else 'normal'),
        'heart_width_px': int(hw),
        'thorax_width_px': int(tw),
        'right_lung_area_px': rl_area,
        'left_lung_area_px': ll_area,
        'heart_area_px': int(heart.sum()),
        'total_lung_area_px': rl_area + ll_area,
        'lung_area_ratio': round(ll_area / rl_area, 4) if rl_area > 0 else 0.0,
    }

    # 추가 해부학적 측정값 (4개)
    measurements['mediastinum'] = measure_mediastinum(right_lung, left_lung)
    measurements['trachea'] = measure_trachea_shift(right_lung, left_lung)
    measurements['cp_angle'] = measure_cp_angles(right_lung, left_lung)
    measurements['diaphragm'] = measure_diaphragm(right_lung, left_lung, original_size[0])

    # View
    view_idx = out['view'].argmax(dim=-1).item()
    view = {0: 'AP', 1: 'PA', 2: 'lateral'}.get(view_idx, 'unknown')

    # Age / Sex
    age = round(out['age'].item(), 1)
    sex = 'F' if out['female'].item() >= 0.5 else 'M'

    # 마스크를 컬러 PNG로 변환 (반투명 오버레이용)
    color_mask = np.zeros((*mask.shape, 4), dtype=np.uint8)
    color_mask[mask == 1] = [41, 128, 185, 140]   # 우폐(Right Lung, class 1): 파랑
    color_mask[mask == 2] = [39, 174, 96, 140]    # 좌폐(Left Lung, class 2): 초록
    color_mask[mask == 3] = [231, 76, 60, 160]    # 심장(Heart, class 3): 빨강

    mask_img = Image.fromarray(color_mask, 'RGBA')
    buf = io.BytesIO()
    mask_img.save(buf, format='PNG')
    mask_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')

    return {
        'measurements': measurements,
        'view': view,
        'age_pred': age,
        'sex_pred': sex,
        'mask_base64': mask_base64,
        'original_size': list(original_size),
    }


def list_samples():
    """샘플 이미지 목록 + 프리사인 URL 반환"""
    paginator = s3_client.get_paginator('list_objects_v2')
    samples = []
    for page in paginator.paginate(Bucket=WORK_BUCKET, Prefix=SAMPLE_S3_PREFIX + '/'):
        for obj in page.get('Contents', []):
            key = obj['Key']
            if key.endswith(('.jpg', '.png', '.jpeg')):
                filename = key.split('/')[-1]
                url = s3_client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': WORK_BUCKET, 'Key': key},
                    ExpiresIn=3600
                )
                samples.append({'filename': filename, 's3_key': key, 'url': url})
    return samples


def serve_html():
    """테스트 페이지 HTML 반환 (GET 요청 시)"""
    html_path = os.path.join(os.path.dirname(__file__), 'index.html')
    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()
    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'text/html; charset=utf-8'},
        'body': html
    }


def handler(event, context):
    """Lambda 핸들러 — GET: 테스트 페이지, POST: API"""
    method = event.get('requestContext', {}).get('http', {}).get('method', 'POST')

    # GET → 테스트 페이지 서빙
    if method == 'GET':
        return serve_html()

    try:
        # body 파싱
        body = event
        if isinstance(event.get('body'), str):
            body = json.loads(event['body'])
        elif isinstance(event.get('body'), dict):
            body = event['body']

        # 액션 분기
        action = body.get('action', 'segment')
        if action == 'list_samples':
            samples = list_samples()
            return {
                'statusCode': 200,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'samples': samples}, ensure_ascii=False)
            }

        # 세그멘테이션 실행
        start = time.time()
        img = get_image(event)
        result = run_segmentation(img)
        result['processing_time'] = round(time.time() - start, 2)

        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps(result, ensure_ascii=False)
        }

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': str(e)})
        }
