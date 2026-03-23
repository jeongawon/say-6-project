"""
Layer 1 테스트 준비 — SageMaker 노트북에서 실행
1. HuggingFace 모델 다운로드 → S3 저장 (매번 HF 안 받게)
2. 샘플 CXR 이미지 5장 → S3 웹 경로에 복사
3. 간단 추론 테스트
"""
import os
import json
import random
import boto3
import io

WORK_BUCKET = 'pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an'
IMAGE_BUCKET = WORK_BUCKET  # p10 이미지가 이미 work 버킷에 복사돼있음
IMAGE_PREFIX = 'data/p10_pa'  # 이미지 경로 프리픽스
MODEL_S3_PREFIX = 'models/segmentation/chest-x-ray-basic'
SAMPLE_S3_PREFIX = 'web/test-layer1/samples'
CSV_S3_KEY = 'preprocessing/p10_train_ready_resplit.csv'

s3 = boto3.client('s3', region_name='ap-northeast-2')


# ============================================================
# Step 1: HuggingFace 모델 → S3 저장
# ============================================================
def save_model_to_s3():
    """HF 모델을 S3에 저장 (이후 Lambda에서 S3에서 로드)"""
    import torch
    from transformers import AutoModel
    import tempfile

    # 이미 업로드됐는지 확인
    try:
        s3.head_object(Bucket=WORK_BUCKET, Key=f'{MODEL_S3_PREFIX}/config.json')
        print('✅ 모델 이미 S3에 저장됨. 스킵.')
        return
    except:
        pass

    print('📥 HuggingFace에서 모델 다운로드 중...')
    model = AutoModel.from_pretrained('ianpan/chest-x-ray-basic', trust_remote_code=True)
    print(f'   모델 타입: {type(model).__name__}')

    with tempfile.TemporaryDirectory() as tmpdir:
        print('💾 로컬에 저장 중...')
        model.save_pretrained(tmpdir)

        # S3에 업로드
        print('☁️  S3에 업로드 중...')
        file_count = 0
        for root, dirs, files in os.walk(tmpdir):
            for f in files:
                local_path = os.path.join(root, f)
                rel_path = os.path.relpath(local_path, tmpdir)
                s3_key = f'{MODEL_S3_PREFIX}/{rel_path}'
                file_size = os.path.getsize(local_path)
                print(f'   {rel_path} ({file_size / 1024 / 1024:.1f}MB)')
                s3.upload_file(local_path, WORK_BUCKET, s3_key)
                file_count += 1

        print(f'✅ 모델 저장 완료: s3://{WORK_BUCKET}/{MODEL_S3_PREFIX}/ ({file_count}개 파일)')


# ============================================================
# Step 2: 샘플 CXR 이미지 복사
# ============================================================
def copy_sample_images(num_samples=5):
    """MIMIC-CXR에서 PA 이미지 5장을 웹 테스트용으로 복사"""
    import pandas as pd

    # 이미 복사됐는지 확인
    try:
        resp = s3.list_objects_v2(
            Bucket=WORK_BUCKET, Prefix=SAMPLE_S3_PREFIX, MaxKeys=5
        )
        existing = resp.get('Contents', [])
        jpg_count = sum(1 for o in existing if o['Key'].endswith('.jpg'))
        if jpg_count >= num_samples:
            print(f'✅ 샘플 이미지 {jpg_count}장 이미 존재. 스킵.')
            return
    except:
        pass

    # CSV에서 랜덤 PA 이미지 선택
    print('📋 CSV 로드 중...')
    csv_path = '/tmp/p10_train_ready_resplit.csv'
    s3.download_file(WORK_BUCKET, CSV_S3_KEY, csv_path)
    df = pd.read_csv(csv_path)

    # train split에서 랜덤 선택
    train_df = df[df['split'] == 'train']
    samples = train_df.sample(n=num_samples, random_state=42)

    print(f'📸 샘플 이미지 {num_samples}장 복사 중...')
    sample_info = []

    for i, (_, row) in enumerate(samples.iterrows(), 1):
        src_key = row['image_path']  # MIMIC 경로 (files/p10/...)
        dst_key = f'{SAMPLE_S3_PREFIX}/sample_{i}.jpg'

        # work 버킷 내부 복사 (data/p10_pa/ 에서 web/samples/ 로)
        try:
            full_src_key = f'{IMAGE_PREFIX}/{src_key}'
            copy_source = {'Bucket': IMAGE_BUCKET, 'Key': full_src_key}
            s3.copy_object(
                CopySource=copy_source,
                Bucket=WORK_BUCKET,
                Key=dst_key
            )

            # 라벨 정보 수집
            label_cols = [
                'Atelectasis', 'Cardiomegaly', 'Consolidation', 'Edema',
                'Enlarged Cardiomediastinum', 'Fracture', 'Lung Lesion',
                'Lung Opacity', 'No Finding', 'Pleural Effusion',
                'Pleural Other', 'Pneumonia', 'Pneumothorax', 'Support Devices'
            ]
            positive_labels = [col for col in label_cols if row.get(col, 0) == 1.0]

            info = {
                'filename': f'sample_{i}.jpg',
                's3_key': dst_key,
                'subject_id': str(row.get('subject_id', '')),
                'study_id': str(row.get('study_id', '')),
                'labels': positive_labels if positive_labels else ['No Finding'],
            }
            sample_info.append(info)
            print(f'   [{i}/{num_samples}] sample_{i}.jpg — {", ".join(info["labels"])}')

        except Exception as e:
            print(f'   [{i}] 복사 실패: {e}')

    # 샘플 정보 JSON 저장
    info_key = f'{SAMPLE_S3_PREFIX}/samples.json'
    s3.put_object(
        Bucket=WORK_BUCKET,
        Key=info_key,
        Body=json.dumps(sample_info, ensure_ascii=False, indent=2),
        ContentType='application/json'
    )
    print(f'✅ 샘플 이미지 {len(sample_info)}장 복사 완료')
    print(f'   s3://{WORK_BUCKET}/{SAMPLE_S3_PREFIX}/')


# ============================================================
# Step 3: 빠른 추론 테스트
# ============================================================
def quick_test():
    """샘플 이미지 1장으로 추론 테스트"""
    from PIL import Image
    import numpy as np

    print('\n🧪 추론 테스트...')

    # 샘플 이미지 다운로드
    img_key = f'{SAMPLE_S3_PREFIX}/sample_1.jpg'
    response = s3.get_object(Bucket=WORK_BUCKET, Key=img_key)
    img = Image.open(io.BytesIO(response['Body'].read())).convert('RGB')
    print(f'   이미지 크기: {img.size}')

    # 모델 로드 (S3에서)
    import tempfile
    model_dir = '/tmp/chest-x-ray-basic'
    if not os.path.exists(os.path.join(model_dir, 'config.json')):
        os.makedirs(model_dir, exist_ok=True)
        print('   모델 S3에서 다운로드 중...')
        paginator = s3.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=WORK_BUCKET, Prefix=MODEL_S3_PREFIX):
            for obj in page.get('Contents', []):
                rel = obj['Key'][len(MODEL_S3_PREFIX) + 1:]
                local = os.path.join(model_dir, rel)
                os.makedirs(os.path.dirname(local), exist_ok=True)
                s3.download_file(WORK_BUCKET, obj['Key'], local)

    from transformers import AutoModel
    import torch

    model = AutoModel.from_pretrained(model_dir, trust_remote_code=True)
    model.eval()

    # 전처리 + 추론
    img_np = np.array(img.convert('L'))
    x = model.preprocess(img_np)
    x = torch.from_numpy(x).unsqueeze(0).unsqueeze(0).float()

    with torch.inference_mode():
        out = model(x)

    mask = out['mask'].argmax(dim=1).squeeze(0).cpu().numpy()

    # CTR 계산
    heart = (mask == 3)
    right_lung = (mask == 1)
    left_lung = (mask == 2)
    thorax = right_lung | left_lung | heart

    def max_width(m):
        if not m.any():
            return 0
        rows = m.any(axis=1)
        mw = 0
        for r in np.where(rows)[0]:
            cols = np.where(m[r])[0]
            mw = max(mw, cols[-1] - cols[0] + 1)
        return mw

    hw = max_width(heart)
    tw = max_width(thorax)
    ctr = hw / tw if tw > 0 else 0

    # 결과 출력
    view_idx = out['view'].argmax(dim=-1).item()
    view = {0: 'AP', 1: 'PA', 2: 'lateral'}.get(view_idx, '?')
    age = out['age'].item()
    sex = 'F' if out['female'].item() >= 0.5 else 'M'

    print(f'\n   === 추론 결과 ===')
    print(f'   View: {view}')
    print(f'   CTR: {ctr:.4f} ({"정상" if ctr < 0.5 else "심비대"})')
    print(f'   심장 폭: {hw}px / 흉곽 폭: {tw}px')
    print(f'   우폐 면적: {int(right_lung.sum())}px')
    print(f'   좌폐 면적: {int(left_lung.sum())}px')
    print(f'   심장 면적: {int(heart.sum())}px')
    print(f'   예측 나이: {age:.1f}세')
    print(f'   예측 성별: {sex}')
    print(f'   ✅ 추론 테스트 성공!')


# ============================================================
# 실행
# ============================================================
if __name__ == '__main__':
    print('=' * 60)
    print('Layer 1 테스트 준비')
    print('=' * 60)

    print('\n--- Step 1: 모델 S3 저장 ---')
    save_model_to_s3()

    print('\n--- Step 2: 샘플 이미지 복사 ---')
    copy_sample_images()

    print('\n--- Step 3: 추론 테스트 ---')
    quick_test()

    print('\n' + '=' * 60)
    print('준비 완료! 다음 단계:')
    print('  1. deploy/layer1_segmentation/ 의 Dockerfile 빌드')
    print('  2. ECR 푸시 → Lambda 생성')
    print('  3. 테스트 웹페이지 CloudFront 배포')
    print('=' * 60)
