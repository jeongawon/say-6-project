"""
Layer 2b YOLOv8 Detection Lambda — VinDr-CXR 14-Class Object Detection
입력: CXR 이미지 (base64 또는 S3 경로)
출력: 바운딩박스 + 클래스 + 신뢰도

GET  → 테스트 페이지 (index.html)
POST → 탐지 API
"""
import os
import json
import base64
import io
import time
import boto3
import numpy as np
from PIL import Image

# 글로벌 캐시 (Lambda 컨테이너 재사용 시 유지)
model = None
s3_client = boto3.client('s3', region_name='ap-northeast-2')

WORK_BUCKET = os.environ.get(
    'WORK_BUCKET',
    'pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an'
)
MODEL_S3_KEY = os.environ.get(
    'MODEL_S3_KEY',
    'models/yolov8_vindr_best.pt'
)
SAMPLE_S3_PREFIX = os.environ.get(
    'SAMPLE_S3_PREFIX',
    'web/test-layer2b/samples'
)
MODEL_LOCAL = '/tmp/yolov8_vindr_best.pt'

CLASS_NAMES = [
    'Aortic_enlargement', 'Atelectasis', 'Calcification', 'Cardiomegaly',
    'Consolidation', 'ILD', 'Infiltration', 'Lung_Opacity',
    'Nodule_Mass', 'Other_lesion', 'Pleural_effusion', 'Pleural_thickening',
    'Pneumothorax', 'Pulmonary_fibrosis'
]

# 클래스별 색상 (HTML 렌더링용)
CLASS_COLORS = [
    '#ef4444', '#f97316', '#eab308', '#22c55e',
    '#14b8a6', '#06b6d4', '#3b82f6', '#6366f1',
    '#8b5cf6', '#a855f7', '#ec4899', '#f43f5e',
    '#fb923c', '#84cc16'
]


def load_model():
    """YOLOv8 모델 로드 (cold start 시 S3에서 다운로드)"""
    global model
    if model is not None:
        return model

    # numpy trapz 패치
    if not hasattr(np, 'trapz') and hasattr(np, 'trapezoid'):
        np.trapz = np.trapezoid

    from ultralytics import YOLO

    if not os.path.exists(MODEL_LOCAL):
        print('[Cold Start] S3에서 YOLOv8 모델 다운로드...')
        start = time.time()
        s3_client.download_file(WORK_BUCKET, MODEL_S3_KEY, MODEL_LOCAL)
        size_mb = os.path.getsize(MODEL_LOCAL) / 1024 / 1024
        print(f'[Cold Start] 다운로드 완료: {size_mb:.1f}MB, {time.time() - start:.1f}초')

    print('[Load] YOLOv8 모델 로드 중...')
    start = time.time()
    model = YOLO(MODEL_LOCAL)
    print(f'[Load] 완료: {time.time() - start:.1f}초')
    return model


def get_image(event):
    """요청에서 이미지 추출 (base64 / S3 key 지원)"""
    body = event
    if isinstance(event.get('body'), str):
        body = json.loads(event['body'])
    elif isinstance(event.get('body'), dict):
        body = event['body']

    if 's3_key' in body:
        bucket = body.get('bucket', WORK_BUCKET)
        resp = s3_client.get_object(Bucket=bucket, Key=body['s3_key'])
        return Image.open(io.BytesIO(resp['Body'].read())).convert('RGB')

    if 'image_base64' in body:
        data = body['image_base64']
        if ',' in data:
            data = data.split(',', 1)[1]
        return Image.open(io.BytesIO(base64.b64decode(data))).convert('RGB')

    raise ValueError('image_base64 또는 s3_key 필요')


def run_detection(img):
    """YOLOv8 추론 → 바운딩박스 + 클래스 + 신뢰도"""
    m = load_model()

    results = m.predict(
        source=img,
        conf=0.15,
        iou=0.45,
        imgsz=1024,
        device='cpu',
        verbose=False,
    )

    detections = []
    r = results[0]
    img_w, img_h = img.size

    if r.boxes is not None and len(r.boxes) > 0:
        boxes = r.boxes.xyxy.cpu().numpy()
        confs = r.boxes.conf.cpu().numpy()
        cls_ids = r.boxes.cls.cpu().numpy().astype(int)

        for i in range(len(boxes)):
            x1, y1, x2, y2 = boxes[i]
            cls_id = cls_ids[i]
            conf = float(confs[i])
            class_name = CLASS_NAMES[cls_id] if cls_id < len(CLASS_NAMES) else f'class_{cls_id}'

            detections.append({
                'class_id': int(cls_id),
                'class_name': class_name,
                'confidence': round(conf, 4),
                'bbox': [round(float(x1), 1), round(float(y1), 1),
                         round(float(x2), 1), round(float(y2), 1)],
                'color': CLASS_COLORS[cls_id % len(CLASS_COLORS)],
            })

    detections.sort(key=lambda x: x['confidence'], reverse=True)

    # 클래스별 요약
    class_summary = {}
    for d in detections:
        cn = d['class_name']
        if cn not in class_summary:
            class_summary[cn] = {'count': 0, 'max_conf': 0}
        class_summary[cn]['count'] += 1
        class_summary[cn]['max_conf'] = max(class_summary[cn]['max_conf'], d['confidence'])

    if not detections:
        summary = 'No lesions detected'
    else:
        classes = list(class_summary.keys())
        summary = f'{len(detections)} lesions detected: {", ".join(classes)}'

    return {
        'detections': detections,
        'num_detections': len(detections),
        'class_summary': class_summary,
        'image_size': [img_w, img_h],
        'summary': summary,
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
    """테스트 페이지 HTML 반환"""
    html_path = os.path.join(os.path.dirname(__file__), 'index.html')
    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()
    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'text/html; charset=utf-8'},
        'body': html
    }


def handler(event, context):
    """Lambda 핸들러 — GET: 테스트 페이지, POST: YOLOv8 탐지 API"""
    method = event.get('requestContext', {}).get('http', {}).get('method', 'POST')

    if method == 'GET':
        return serve_html()

    try:
        body = event
        if isinstance(event.get('body'), str):
            body = json.loads(event['body'])
        elif isinstance(event.get('body'), dict):
            body = event['body']

        action = body.get('action', 'detect')

        if action == 'list_samples':
            samples = list_samples()
            return {
                'statusCode': 200,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'samples': samples}, ensure_ascii=False)
            }

        # YOLOv8 탐지 실행
        start = time.time()
        img = get_image(event)
        result = run_detection(img)
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
