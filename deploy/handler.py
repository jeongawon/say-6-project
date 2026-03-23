"""
Lambda 핸들러 — 흉부 X-Ray 모달 v2 진입점

오케스트레이터가 이 Lambda를 호출하면:
1. request_id 발급 + DynamoDB에 상태 "접수" 기록
2. S3에서 CXR 이미지 다운로드
3. 6-Layer 파이프라인 실행 (각 Layer 완료 시 DynamoDB 상태 업데이트)
4. 결과 JSON 반환 + 어노테이션 이미지 S3 업로드

프론트엔드는 status_handler Lambda를 폴링하여 진행 상태를 실시간 확인.

첫 호출 시(cold start) 모델을 S3에서 다운로드하여 /tmp에 캐시.
Lambda 컨테이너가 재사용되면 캐시된 모델을 바로 로드 (warm start).
"""

import json
import os
import io
import time
import uuid
import traceback
from datetime import datetime, timezone, timedelta

import boto3
import numpy as np
from PIL import Image

# ============================================================
# 글로벌 변수 (Lambda 컨테이너 재사용 시 유지됨)
# ============================================================
models = None  # 모델 캐시
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-2')

# 설정
MODEL_BUCKET = os.environ.get(
    'MODEL_BUCKET',
    'pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an'
)
MODEL_PREFIX = os.environ.get('MODEL_PREFIX', 'models')
RESULT_PREFIX = os.environ.get('RESULT_PREFIX', 'results')
STATUS_TABLE = os.environ.get('STATUS_TABLE', 'chest-xray-modal-status')

# 6-Layer 진행 단계 정의
PIPELINE_STAGES = [
    {'stage': 'received',           'progress': 0,   'message': '요청 접수'},
    {'stage': 'image_loaded',       'progress': 5,   'message': 'X-Ray 이미지 로드 완료'},
    {'stage': 'segmentation_done',  'progress': 15,  'message': '해부학 구조 분석 완료 (폐/심장 세그멘테이션)'},
    {'stage': 'detection_done',     'progress': 40,  'message': '질환 탐지 완료 (DenseNet-121 + YOLOv8)'},
    {'stage': 'clinical_logic_done','progress': 60,  'message': '임상 판독 로직 완료 (CTR, CP angle 등)'},
    {'stage': 'cross_val_done',     'progress': 70,  'message': '교차 검증 완료 (3중 일치 확인)'},
    {'stage': 'rag_done',           'progress': 80,  'message': '유사 판독문 검색 완료'},
    {'stage': 'report_done',        'progress': 95,  'message': '소견서 생성 완료'},
    {'stage': 'completed',          'progress': 100, 'message': '전체 분석 완료'},
]


# ============================================================
# 상태 업데이트 (DynamoDB)
# ============================================================
def update_status(request_id, stage_index, extra_data=None):
    """DynamoDB에 현재 진행 상태를 기록"""
    try:
        table = dynamodb.Table(STATUS_TABLE)
        stage = PIPELINE_STAGES[stage_index]
        kst = timezone(timedelta(hours=9))

        item = {
            'request_id': request_id,
            'status': stage['stage'],
            'progress': stage['progress'],
            'message': stage['message'],
            'updated_at': datetime.now(kst).isoformat(),
        }

        if extra_data:
            item['data'] = extra_data

        table.put_item(Item=item)
    except Exception as e:
        # 상태 업데이트 실패해도 파이프라인은 계속 진행
        print(f"[Status Update 실패] {e}")


# ============================================================
# 모델 로드 (cold start 시 1회만 실행)
# ============================================================
def load_models():
    """S3에서 모델 가중치 다운로드 → 로드"""
    global models
    if models is not None:
        return models  # warm start — 이미 로드됨

    import torch
    import torch.nn as nn
    from torchvision import models as tv_models

    print("[Cold Start] 모델 로드 시작...")
    start = time.time()

    model_cache_dir = '/tmp/models'
    os.makedirs(model_cache_dir, exist_ok=True)

    loaded = {}

    # --- DenseNet-121 ---
    densenet_path = os.path.join(model_cache_dir, 'densenet121.pth')
    if not os.path.exists(densenet_path):
        print("  DenseNet-121 다운로드 중...")
        s3_client.download_file(
            MODEL_BUCKET,
            f'{MODEL_PREFIX}/densenet121.pth',
            densenet_path
        )

    densenet = tv_models.densenet121(weights=None)
    densenet.classifier = nn.Linear(densenet.classifier.in_features, 14)
    densenet.load_state_dict(torch.load(densenet_path, map_location='cpu'))
    densenet.eval()
    loaded['densenet'] = densenet
    print("  DenseNet-121 로드 완료")

    # --- Segmentation (HuggingFace 사전학습 모델) ---
    from layer1_segmentation.segmentation_model import SegmentationModel
    seg_model = SegmentationModel(device='cpu')  # Lambda는 CPU
    seg_model.load()
    loaded['segmentation'] = seg_model
    print("  Segmentation 모델 로드 완료 (ianpan/chest-x-ray-basic)")

    # --- YOLOv8 ---
    # TODO: YOLOv8 학습 후 여기에 로드 코드 추가
    loaded['yolo'] = None
    print("  YOLOv8: 미구현 (Phase 2에서 추가)")

    # --- FAISS 인덱스 ---
    # TODO: RAG 인덱스 구축 후 여기에 로드 코드 추가
    loaded['faiss_index'] = None
    print("  FAISS: 미구현 (Phase 5에서 추가)")

    elapsed = time.time() - start
    print(f"[Cold Start] 모델 로드 완료 ({elapsed:.1f}초)")

    models = loaded
    return models


# ============================================================
# 이미지 전처리
# ============================================================
def load_image_from_s3(bucket, key):
    """S3에서 이미지를 로드하여 PIL Image 반환"""
    response = s3_client.get_object(Bucket=bucket, Key=key)
    img_bytes = response['Body'].read()
    image = Image.open(io.BytesIO(img_bytes)).convert('RGB')
    return image


def preprocess_for_densenet(image):
    """DenseNet-121 입력용 전처리"""
    from torchvision import transforms
    transform = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize(
            mean=[0.485, 0.456, 0.406],
            std=[0.229, 0.224, 0.225]
        )
    ])
    return transform(image).unsqueeze(0)


# ============================================================
# 6-Layer 파이프라인
# ============================================================
def run_pipeline(request_id, image, patient_info=None, prior_results=None):
    """
    6-Layer 파이프라인 실행
    각 Layer 완료 시 DynamoDB에 상태 업데이트
    """
    import torch
    from pipeline.config import LABEL_COLS

    m = load_models()
    result = {}

    # ---- Layer 1: Anatomy Segmentation ----
    seg_result = m['segmentation'].predict(image)
    anatomy = {
        'measurements': seg_result['measurements'],
        'view': seg_result['view'],
        'age_pred': seg_result['age_pred'],
        'sex_pred': seg_result['sex_pred'],
    }
    result['anatomy_measurements'] = anatomy
    update_status(request_id, 2)  # segmentation_done

    # ---- Layer 2a: DenseNet-121 ----
    input_tensor = preprocess_for_densenet(image)
    with torch.no_grad():
        output = m['densenet'](input_tensor)
        probs = torch.sigmoid(output).cpu().numpy()[0]

    densenet_preds = {
        LABEL_COLS[i]: float(probs[i]) for i in range(len(LABEL_COLS))
    }
    result['densenet_predictions'] = densenet_preds

    # ---- Layer 2b: YOLOv8 ----
    yolo_detections = []
    if m['yolo'] is not None:
        # TODO: YOLOv8 추론
        pass
    result['yolo_detections'] = yolo_detections
    update_status(request_id, 3)  # detection_done

    # ---- Layer 3: Clinical Logic ----
    clinical_findings = []
    # TODO: clinical_engine.analyze() 호출
    result['clinical_logic_findings'] = clinical_findings
    update_status(request_id, 4)  # clinical_logic_done

    # ---- Layer 4: Cross-Validation ----
    cross_validation = {
        'densenet_yolo_agreement': None,
        'densenet_clinical_agreement': None,
        'overall_confidence': 'low'
    }
    result['cross_validation'] = cross_validation
    update_status(request_id, 5)  # cross_val_done

    # ---- Layer 5: RAG ----
    rag_evidence = []
    # TODO: FAISS 검색
    result['rag_evidence'] = rag_evidence
    update_status(request_id, 6)  # rag_done

    # ---- Layer 6: Bedrock Report ----
    # TODO: Bedrock API 호출하여 소견서 생성
    result['report'] = None
    result['recommendations'] = []
    result['alert_flags'] = []
    update_status(request_id, 7)  # report_done

    return result


# ============================================================
# Lambda 핸들러
# ============================================================
def lambda_handler(event, context):
    """
    Lambda 진입점

    event 예시:
    {
        "patient_id": "p10000032",
        "cxr_image_s3_path": "s3://bucket/image.jpg",
        "patient_info": {
            "age": 67, "sex": "M",
            "chief_complaint": "흉통, 호흡곤란",
            "vitals": {"HR": 110, "BP": "90/60", "SpO2": 88}
        },
        "prior_results": [
            {"modal": "ecg", "summary": "정상 동성리듬"}
        ]
    }
    """
    start_time = time.time()

    # request_id 발급 (프론트엔드가 이 ID로 상태 폴링)
    request_id = event.get('request_id', f"req_{uuid.uuid4().hex[:12]}")

    try:
        print(f"요청 수신: request_id={request_id}, patient_id={event.get('patient_id')}")

        # 상태: 접수
        update_status(request_id, 0)

        # S3 경로 파싱
        s3_path = event.get('cxr_image_s3_path', '')
        if s3_path.startswith('s3://'):
            parts = s3_path.replace('s3://', '').split('/', 1)
            bucket, key = parts[0], parts[1]
        else:
            bucket = MODEL_BUCKET
            key = s3_path

        # 이미지 로드
        image = load_image_from_s3(bucket, key)
        print(f"이미지 로드 완료: {image.size}")
        update_status(request_id, 1)  # image_loaded

        # 파이프라인 실행 (내부에서 각 Layer별 상태 업데이트)
        result = run_pipeline(
            request_id=request_id,
            image=image,
            patient_info=event.get('patient_info'),
            prior_results=event.get('prior_results', [])
        )

        # 메타데이터 추가
        elapsed = time.time() - start_time
        result['modal'] = 'chest_xray'
        result['request_id'] = request_id
        result['patient_id'] = event.get('patient_id')
        result['processing_time_seconds'] = round(elapsed, 2)
        result['status'] = 'completed'

        # 상태: 완료 (결과 포함)
        update_status(request_id, 8, extra_data=result)

        print(f"처리 완료: {elapsed:.2f}초")

        return {
            'statusCode': 200,
            'body': json.dumps(result, ensure_ascii=False)
        }

    except Exception as e:
        elapsed = time.time() - start_time
        error_msg = traceback.format_exc()
        print(f"오류 발생: {error_msg}")

        # 상태: 에러
        update_status(request_id, 0, extra_data={
            'status': 'error',
            'error': str(e),
            'progress': -1,
            'message': f'오류 발생: {str(e)}'
        })

        return {
            'statusCode': 500,
            'body': json.dumps({
                'status': 'error',
                'request_id': request_id,
                'error': str(e),
                'processing_time_seconds': round(elapsed, 2)
            })
        }
