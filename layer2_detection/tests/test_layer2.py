"""
Layer 2 DenseNet-121 14-Disease Detection 테스트
파일 하나로 완결 — 외부 모듈 import 없음, pip install 없음

실행:
  python test_layer2.py
"""
import os
import sys
import numpy as np
import torch
import torch.nn as nn
from torchvision import models, transforms
from PIL import Image
import boto3

# ============================================================
# 설정
# ============================================================
WORK_BUCKET = 'pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an'
CHECKPOINT_S3_PREFIX = 'checkpoints/densenet121-full-pa-v6-multigpu/'
MODEL_S3_OUTPUT = 'output/densenet121-full-pa-v6-multigpu/output/model.tar.gz'
MODEL_LOCAL = '/tmp/densenet121_best.pth'

LABEL_COLS = [
    'Atelectasis', 'Cardiomegaly', 'Consolidation', 'Edema',
    'Enlarged Cardiomediastinum', 'Fracture', 'Lung Lesion', 'Lung Opacity',
    'No Finding', 'Pleural Effusion', 'Pleural Other', 'Pneumonia',
    'Pneumothorax', 'Support Devices'
]

s3 = boto3.client('s3', region_name='ap-northeast-2')


# ============================================================
# 1) 모델 다운로드
# ============================================================
def download_model():
    if os.path.exists(MODEL_LOCAL):
        size_mb = os.path.getsize(MODEL_LOCAL) / 1024 / 1024
        print(f'[1/3] 모델 캐시 사용: {MODEL_LOCAL} ({size_mb:.1f} MB)')
        return MODEL_LOCAL

    # 먼저 학습 완료 모델 시도
    print('[1/3] 학습 완료 모델 확인 중...')
    try:
        s3.head_object(Bucket=WORK_BUCKET, Key=MODEL_S3_OUTPUT)
        print('  model.tar.gz 발견! 다운로드 중...')
        tar_local = '/tmp/densenet_model.tar.gz'
        s3.download_file(WORK_BUCKET, MODEL_S3_OUTPUT, tar_local)

        import tarfile
        extract_dir = '/tmp/densenet_extracted'
        os.makedirs(extract_dir, exist_ok=True)
        with tarfile.open(tar_local, 'r:gz') as tar:
            tar.extractall(extract_dir)

        for fname in ['best_model.pth', 'model.pth']:
            candidate = os.path.join(extract_dir, fname)
            if os.path.exists(candidate):
                os.rename(candidate, MODEL_LOCAL)
                print(f'  완료: {fname}')
                return MODEL_LOCAL

        for f in os.listdir(extract_dir):
            if f.endswith('.pth'):
                os.rename(os.path.join(extract_dir, f), MODEL_LOCAL)
                print(f'  완료: {f}')
                return MODEL_LOCAL

    except Exception:
        pass

    # 체크포인트 시도
    print('  완료 모델 없음 -> 체크포인트 검색...')
    try:
        resp = s3.list_objects_v2(Bucket=WORK_BUCKET, Prefix=CHECKPOINT_S3_PREFIX)
        pth_files = [o for o in resp.get('Contents', []) if o['Key'].endswith('.pth')]

        if not pth_files:
            print('  체크포인트도 없음!')
            return None

        latest = sorted(pth_files, key=lambda x: x['LastModified'])[-1]
        size_mb = latest['Size'] / 1024 / 1024
        print(f'  최신 체크포인트: {os.path.basename(latest["Key"])} ({size_mb:.1f} MB)')
        print(f'  다운로드 중...')
        s3.download_file(WORK_BUCKET, latest['Key'], MODEL_LOCAL)
        print(f'  완료!')
        return MODEL_LOCAL

    except Exception as e:
        print(f'  실패: {e}')
        return None


# ============================================================
# 2) 모델 로드
# ============================================================
def load_model(model_path):
    print(f'[2/3] DenseNet-121 모델 로드 중...')

    model = models.densenet121(weights=None)
    num_features = model.classifier.in_features
    model.classifier = nn.Linear(num_features, len(LABEL_COLS))

    raw = torch.load(model_path, map_location='cpu', weights_only=False)

    # checkpoint.pth는 dict 형식 (model_state_dict 키 포함)
    if isinstance(raw, dict) and 'model_state_dict' in raw:
        print(f'  체크포인트 형식 (epoch {raw.get("epoch", "?")}, stage {raw.get("stage", "?")})')
        state_dict = raw['model_state_dict']
    else:
        state_dict = raw

    # DataParallel module. 접두사 제거
    if any(k.startswith('module.') for k in state_dict.keys()):
        state_dict = {k.replace('module.', ''): v for k, v in state_dict.items()}

    model.load_state_dict(state_dict)
    model.eval()

    print(f'  로드 완료! (14개 질환 분류)')
    return model


# ============================================================
# 3) 테스트 이미지 다운로드
# ============================================================
def download_test_images(num=5):
    """작업 버킷의 테스트 이미지 다운로드 (say1 접근 불가하므로 미리 복사해둔 이미지 사용)"""
    print(f'[3/3] 테스트 이미지 다운로드 중...')

    TEST_PREFIX = 'test-images/'

    # 작업 버킷에서 테스트 이미지 목록 조회
    resp = s3.list_objects_v2(Bucket=WORK_BUCKET, Prefix=TEST_PREFIX)
    objects = [o for o in resp.get('Contents', []) if o['Key'].endswith('.jpg') and o['Size'] > 0]

    if not objects:
        print('  테스트 이미지 없음!')
        return []

    objects = objects[:num]
    print(f'  {len(objects)}장 발견')

    images = []
    for idx, obj in enumerate(objects, 1):
        filename = os.path.basename(obj['Key'])
        local_path = f'/tmp/cxr_test_{filename}'

        if not os.path.exists(local_path):
            try:
                s3.download_file(WORK_BUCKET, obj['Key'], local_path)
                print(f'  [{idx}/{len(objects)}] {filename} OK')
            except Exception as e:
                print(f'  [{idx}/{len(objects)}] {filename} FAIL: {e}')
                continue
        else:
            print(f'  [{idx}/{len(objects)}] {filename} (캐시)')

        images.append({
            'path': local_path,
            'dicom_id': filename.replace('.jpg', ''),
            'gt_labels': [],  # 작업 버킷 이미지는 GT 라벨 없음
        })

    return images


# ============================================================
# 4) 추론
# ============================================================
def predict(model, image_path):
    transform = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406],
                             std=[0.229, 0.224, 0.225])
    ])

    img = Image.open(image_path).convert('RGB')
    x = transform(img).unsqueeze(0)

    with torch.inference_mode():
        logits = model(x)
        probs = torch.sigmoid(logits).squeeze(0).cpu().numpy()

    results = []
    for i, disease in enumerate(LABEL_COLS):
        p = float(probs[i])
        results.append({
            'disease': disease,
            'probability': p,
            'positive': p >= 0.5,
        })

    results.sort(key=lambda x: x['probability'], reverse=True)
    return results


# ============================================================
# 5) 결과 출력
# ============================================================
def print_result(findings, gt_labels, dicom_id, idx, total):
    positive = [f for f in findings if f['positive'] and f['disease'] != 'No Finding']

    print()
    print(f'{"="*65}')
    print(f'  [{idx}/{total}] {dicom_id}')
    print(f'{"="*65}')

    if positive:
        print(f'  \033[91m{len(positive)}개 이상 소견 탐지\033[0m')
    else:
        print(f'  \033[92m특이 소견 없음\033[0m')

    print()
    print(f'  {"Disease":<30} {"Prob":>7}  {"Pred":>4}  {"GT":>4}')
    print(f'  {"─"*30} {"───":>7}  {"──":>4}  {"──":>4}')

    for f in findings:
        disease = f['disease']
        prob = f['probability']
        pred = 'O' if f['positive'] else '-'
        gt = 'O' if disease in gt_labels else '-'

        bar = '#' * int(prob * 20) + '.' * (20 - int(prob * 20))

        # 색상
        if f['positive'] and prob >= 0.7:
            c = '\033[91m'  # 빨강
        elif f['positive']:
            c = '\033[93m'  # 노랑
        elif disease in gt_labels:
            c = '\033[96m'  # 시안 (놓친 것)
        else:
            c = '\033[0m'
        r = '\033[0m'

        # 예측-정답 일치 표시
        match = ''
        if f['positive'] and disease in gt_labels:
            match = ' TP'
        elif f['positive'] and disease not in gt_labels:
            match = ' FP'
        elif not f['positive'] and disease in gt_labels:
            match = ' FN'

        print(f'  {c}{disease:<30} {prob:>6.1%}  {pred:>4}  {gt:>4}{r}  {bar}{match}')

    print()
    if gt_labels:
        print(f'  정답: {", ".join(gt_labels)}')
    else:
        print(f'  정답: (라벨 없음)')


# ============================================================
# 메인
# ============================================================
def main():
    print()
    print('=' * 65)
    print('  Layer 2: DenseNet-121 14-Disease Detection Test')
    print('=' * 65)
    print()

    # 1) 모델 다운로드
    model_path = download_model()
    if model_path is None:
        print('\n모델을 찾을 수 없습니다. 학습이 아직 진행 중이거나 실패했습니다.')
        sys.exit(1)

    # 2) 모델 로드
    model = load_model(model_path)

    # 3) 테스트 이미지
    images = download_test_images(num=5)
    if not images:
        print('\n테스트 이미지를 가져올 수 없습니다.')
        sys.exit(1)

    # 4) 추론 + 결과 출력
    print()
    print('=' * 65)
    print('  추론 시작')
    print('=' * 65)

    all_findings = []
    for i, img_info in enumerate(images, 1):
        findings = predict(model, img_info['path'])
        print_result(findings, img_info['gt_labels'], img_info['dicom_id'], i, len(images))
        all_findings.append({
            'findings': findings,
            'gt_labels': img_info['gt_labels'],
        })

    # 5) 전체 요약
    print()
    print('=' * 65)
    print('  전체 요약')
    print('=' * 65)

    total_images = len(all_findings)
    has_finding = 0
    disease_counts = {d: 0 for d in LABEL_COLS}

    for item in all_findings:
        pos = [f for f in item['findings'] if f['positive'] and f['disease'] != 'No Finding']
        if pos:
            has_finding += 1
        for f in item['findings']:
            if f['positive']:
                disease_counts[f['disease']] += 1

    print(f'  테스트 이미지: {total_images}장')
    print(f'  이상 소견: {has_finding}장 ({has_finding/total_images*100:.0f}%)')
    print(f'  정상:      {total_images - has_finding}장')

    # 질환별 탐지 빈도
    print()
    print(f'  {"Disease":<30} {"Count":>6}  {"Avg Prob":>8}')
    print(f'  {"─"*30} {"──":>6}  {"──":>8}')

    for d in LABEL_COLS:
        if disease_counts[d] > 0:
            avg_prob = np.mean([
                f['probability']
                for item in all_findings
                for f in item['findings']
                if f['disease'] == d and f['positive']
            ])
            print(f'  {d:<30} {disease_counts[d]:>6}  {avg_prob:>7.1%}')

    print()
    print('=' * 65)
    print('  테스트 완료!')
    print('=' * 65)
    print()


if __name__ == '__main__':
    main()
