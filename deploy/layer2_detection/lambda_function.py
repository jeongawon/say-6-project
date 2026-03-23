"""
Layer 2 Detection Lambda — DenseNet-121 14-Disease 엔드포인트
입력: CXR 이미지 (base64 또는 S3 경로)
출력: 14개 질환 확률 + 양성/음성 판정

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
    'models/detection/densenet121.pth'
)
SAMPLE_S3_PREFIX = os.environ.get(
    'SAMPLE_S3_PREFIX',
    'web/test-layer2/samples'
)
MODEL_LOCAL = '/tmp/densenet121.pth'

LABEL_COLS = [
    'Atelectasis', 'Cardiomegaly', 'Consolidation', 'Edema',
    'Enlarged Cardiomediastinum', 'Fracture', 'Lung Lesion', 'Lung Opacity',
    'No Finding', 'Pleural Effusion', 'Pleural Other', 'Pneumonia',
    'Pneumothorax', 'Support Devices'
]


def load_model():
    """모델 로드 (cold start 시 S3에서 다운로드, warm start 시 캐시 사용)"""
    global model
    if model is not None:
        return model

    import torch
    import torch.nn as nn
    from torchvision import models as tv_models

    # S3에서 /tmp로 다운로드
    if not os.path.exists(MODEL_LOCAL):
        print('[Cold Start] S3에서 모델 다운로드...')
        start = time.time()
        s3_client.download_file(WORK_BUCKET, MODEL_S3_KEY, MODEL_LOCAL)
        size_mb = os.path.getsize(MODEL_LOCAL) / 1024 / 1024
        print(f'[Cold Start] 다운로드 완료: {size_mb:.1f}MB, {time.time() - start:.1f}초')

    print('[Load] DenseNet-121 모델 로드 중...')
    start = time.time()

    densenet = tv_models.densenet121(weights=None)
    num_features = densenet.classifier.in_features
    densenet.classifier = nn.Linear(num_features, len(LABEL_COLS))

    state_dict = torch.load(MODEL_LOCAL, map_location='cpu', weights_only=False)

    # checkpoint.pth dict 형식 처리
    if isinstance(state_dict, dict) and 'model_state_dict' in state_dict:
        state_dict = state_dict['model_state_dict']

    # DataParallel module. 접두사 제거
    if any(k.startswith('module.') for k in state_dict.keys()):
        state_dict = {k.replace('module.', ''): v for k, v in state_dict.items()}

    densenet.load_state_dict(state_dict)
    densenet.eval()

    model = densenet
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
    """DenseNet-121 추론 → 14개 질환 확률"""
    import torch
    from torchvision import transforms

    m = load_model()

    transform = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406],
                             std=[0.229, 0.224, 0.225])
    ])

    x = transform(img).unsqueeze(0)

    with torch.inference_mode():
        logits = m(x)
        probs = torch.sigmoid(logits).squeeze(0).cpu().numpy()

    findings = []
    positive = []
    negative = []
    prob_dict = {}

    for i, disease in enumerate(LABEL_COLS):
        p = float(probs[i])
        is_pos = p >= 0.5
        findings.append({
            'disease': disease,
            'probability': round(p, 4),
            'positive': is_pos,
        })
        prob_dict[disease] = round(p, 4)
        if is_pos:
            positive.append(disease)
        else:
            negative.append(disease)

    findings.sort(key=lambda x: x['probability'], reverse=True)

    if not positive or (len(positive) == 1 and positive[0] == 'No Finding'):
        summary = 'No significant findings'
    else:
        real = [f for f in positive if f != 'No Finding']
        summary = f'{len(real)} abnormalities: {", ".join(real)}'

    return {
        'findings': findings,
        'positive_findings': positive,
        'negative_findings': negative,
        'probabilities': prob_dict,
        'num_positive': len(positive),
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
    """Lambda 핸들러 — GET: 테스트 페이지, POST: 탐지 API"""
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

        # 탐지 실행
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
