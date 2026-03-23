"""
Layer 2 Detection 테스트 — CLI (터미널 출력)
SageMaker에서 바로 실행 가능, Gradio/포트 불필요

사용법:
  # 체크포인트로 테스트 (학습 중)
  python test_layer2_cli.py --checkpoint

  # 학습 완료 후 테스트
  python test_layer2_cli.py

  # 로컬 모델 직접 지정
  python test_layer2_cli.py --model-path /tmp/best_model.pth

  # 특정 이미지 테스트
  python test_layer2_cli.py --checkpoint --image /tmp/test.jpg

  # 테스트셋 N장 테스트
  python test_layer2_cli.py --checkpoint --num-samples 10
"""
import os
import sys
import argparse
import numpy as np
import torch
import boto3
from PIL import Image

# detection_model import
_script_dir = os.path.dirname(os.path.abspath(__file__))
for _candidate in [
    _script_dir,
    os.path.join(_script_dir, 'layer2_detection', 'densenet'),
]:
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

try:
    from layer2_detection.densenet.detection_model import DetectionModel, LABEL_COLS
except ModuleNotFoundError:
    from detection_model import DetectionModel, LABEL_COLS

# ============================================================
# 설정
# ============================================================
WORK_BUCKET = 'pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an'
IMAGE_BUCKET = 'say1-pre-project-5'
MODEL_S3_OUTPUT = 'output/densenet121-full-pa-v6-multigpu/output/model.tar.gz'
CHECKPOINT_S3_PREFIX = 'checkpoints/densenet121-full-pa-v6-multigpu/'
MODEL_LOCAL = '/tmp/densenet121_model'

s3 = boto3.client('s3', region_name='ap-northeast-2')


# ============================================================
# 모델 찾기
# ============================================================
def find_best_model(use_checkpoint=False):
    os.makedirs(MODEL_LOCAL, exist_ok=True)
    local_pth = os.path.join(MODEL_LOCAL, 'best_model.pth')

    if os.path.exists(local_pth):
        print(f'[Model] 로컬 캐시 사용: {local_pth}')
        return local_pth

    if use_checkpoint:
        print('[Model] 체크포인트 검색 중...')
        try:
            resp = s3.list_objects_v2(Bucket=WORK_BUCKET, Prefix=CHECKPOINT_S3_PREFIX)
            pth_files = [o for o in resp.get('Contents', []) if o['Key'].endswith('.pth')]
            if pth_files:
                latest = sorted(pth_files, key=lambda x: x['LastModified'])[-1]
                size_mb = latest['ContentLength'] / 1024 / 1024
                print(f'[Model] 최신 체크포인트: {latest["Key"]} ({size_mb:.1f} MB)')
                s3.download_file(WORK_BUCKET, latest['Key'], local_pth)
                print(f'[Model] 다운로드 완료')
                return local_pth
            else:
                print('[Model] 체크포인트 없음!')
        except Exception as e:
            print(f'[Model] 체크포인트 실패: {e}')
    else:
        print('[Model] 학습 완료 모델 다운로드 중...')
        tar_local = os.path.join(MODEL_LOCAL, 'model.tar.gz')
        try:
            s3.download_file(WORK_BUCKET, MODEL_S3_OUTPUT, tar_local)
            import tarfile
            with tarfile.open(tar_local, 'r:gz') as tar:
                tar.extractall(MODEL_LOCAL)
            for fname in ['best_model.pth', 'model.pth']:
                candidate = os.path.join(MODEL_LOCAL, fname)
                if os.path.exists(candidate):
                    return candidate
            for f in os.listdir(MODEL_LOCAL):
                if f.endswith('.pth'):
                    return os.path.join(MODEL_LOCAL, f)
        except Exception as e:
            print(f'[Model] 완료 모델 실패: {e}')
            print('[Model] 체크포인트로 폴백...')
            return find_best_model(use_checkpoint=True)

    return None


# ============================================================
# 테스트 이미지 가져오기
# ============================================================
def get_test_images(num_samples=5):
    """테스트 CSV에서 샘플 이미지 경로 가져오기"""
    try:
        import pandas as pd
    except ImportError:
        print('[Error] pandas 필요: pip install pandas')
        return []

    csv_local = '/tmp/mimic_cxr_pa_final.csv'
    if not os.path.exists(csv_local):
        print('[Data] CSV 다운로드 중...')
        s3.download_file(WORK_BUCKET, 'mimic-cxr-csv/mimic_cxr_pa_final.csv', csv_local)

    df = pd.read_csv(csv_local)
    test_df = df[df['split'] == 'test'].head(num_samples)
    print(f'[Data] 테스트셋에서 {len(test_df)}장 선택')

    images = []
    for _, row in test_df.iterrows():
        dicom_id = row['dicom_id']
        subject_id = str(int(row['subject_id']))
        study_id = str(int(row['study_id']))
        p_prefix = f'p{subject_id[:2]}'
        s3_key = f'files/{p_prefix}/p{subject_id}/s{study_id}/{dicom_id}.jpg'

        # 정답 라벨
        gt_labels = [col for col in LABEL_COLS if col in row and row[col] == 1.0]

        local_path = f'/tmp/cxr_test_{dicom_id}.jpg'
        if not os.path.exists(local_path):
            try:
                s3.download_file(IMAGE_BUCKET, s3_key, local_path)
            except Exception as e:
                print(f'  {dicom_id} 다운로드 실패: {e}')
                continue

        images.append({
            'path': local_path,
            'dicom_id': dicom_id,
            'gt_labels': gt_labels,
        })

    return images


# ============================================================
# 결과 출력
# ============================================================
def print_result(result, gt_labels=None, idx=None):
    """단일 결과 터미널 출력"""
    header = f"  [ Image {idx} ]  " if idx else "  [ Result ]  "
    print('\n' + '=' * 60)
    print(header)
    print('=' * 60)
    print(f'  Summary: {result["summary"]}')
    print(f'  Positive: {len(result["positive_findings"])}개')
    print()

    # 확률 높은 순으로 14개 출력
    print(f'  {"질환":<30} {"확률":>8}  {"판정":>6}  {"정답":>6}')
    print(f'  {"-"*30} {"---":>8}  {"---":>6}  {"---":>6}')

    for f in result['findings']:
        disease = f['disease']
        prob = f['probability']
        pred = 'POS' if f['positive'] else 'neg'
        bar = '█' * int(prob * 20) + '░' * (20 - int(prob * 20))

        gt = ''
        if gt_labels is not None:
            gt = 'GT+' if disease in gt_labels else ''

        # 색상 (ANSI)
        if f['positive']:
            color = '\033[91m' if prob >= 0.7 else '\033[93m'  # 빨강/노랑
        else:
            color = '\033[0m'
        reset = '\033[0m'

        print(f'  {color}{disease:<30} {prob:>7.1%}  {pred:>6}  {gt:>6}{reset}  {bar}')

    if gt_labels:
        print(f'\n  정답 라벨: {", ".join(gt_labels) if gt_labels else "없음"}')

    print()


def print_summary(all_results):
    """전체 요약 통계"""
    print('\n' + '=' * 60)
    print('  [ 전체 요약 ]')
    print('=' * 60)

    total = len(all_results)
    has_finding = sum(1 for r in all_results
                      if r['result']['positive_findings']
                      and not (len(r['result']['positive_findings']) == 1
                               and r['result']['positive_findings'][0] == 'No Finding'))

    print(f'  총 이미지: {total}장')
    print(f'  이상 소견: {has_finding}장 ({has_finding/total*100:.0f}%)')
    print(f'  정상:      {total - has_finding}장')

    # 질환별 양성 카운트
    disease_counts = {d: 0 for d in LABEL_COLS}
    for r in all_results:
        for d in r['result']['positive_findings']:
            disease_counts[d] += 1

    print(f'\n  {"질환":<30} {"탐지 횟수":>10}')
    print(f'  {"-"*30} {"---":>10}')
    for d, cnt in sorted(disease_counts.items(), key=lambda x: -x[1]):
        if cnt > 0 and d != 'No Finding':
            print(f'  {d:<30} {cnt:>10}')

    # 정답 비교 (GT 있는 경우)
    gt_available = [r for r in all_results if r.get('gt_labels')]
    if gt_available:
        print(f'\n  --- 정답 비교 (GT 있는 {len(gt_available)}장) ---')
        tp, fp, fn = 0, 0, 0
        for r in gt_available:
            gt_set = set(r['gt_labels'])
            pred_set = set(r['result']['positive_findings'])
            tp += len(gt_set & pred_set)
            fp += len(pred_set - gt_set)
            fn += len(gt_set - pred_set)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

        print(f'  Precision: {precision:.3f}')
        print(f'  Recall:    {recall:.3f}')
        print(f'  F1 Score:  {f1:.3f}')

    print()


# ============================================================
# 메인
# ============================================================
def main():
    parser = argparse.ArgumentParser(description='Layer 2 Detection CLI Test')
    parser.add_argument('--checkpoint', action='store_true',
                        help='학습 중 체크포인트 사용')
    parser.add_argument('--model-path', type=str, default=None,
                        help='로컬 모델 경로 직접 지정')
    parser.add_argument('--image', type=str, default=None,
                        help='특정 이미지 파일 경로')
    parser.add_argument('--num-samples', type=int, default=5,
                        help='테스트셋에서 테스트할 이미지 수 (기본 5)')
    args = parser.parse_args()

    print('=' * 60)
    print(' Layer 2: 14-Disease Detection — CLI Test')
    print('=' * 60)

    # 모델 로드
    if args.model_path:
        model_path = args.model_path
    else:
        model_path = find_best_model(use_checkpoint=args.checkpoint)

    if model_path is None:
        print('\n[Error] 모델을 찾을 수 없습니다!')
        print('  학습 중이면: --checkpoint 옵션 사용')
        print('  직접 지정:   --model-path /path/to/best_model.pth')
        sys.exit(1)

    detector = DetectionModel(model_path=model_path)
    detector.load()

    # 추론
    if args.image:
        # 단일 이미지
        print(f'\n[Test] 이미지: {args.image}')
        result = detector.predict(args.image)
        print_result(result)
    else:
        # 테스트셋에서 N장
        print(f'\n[Test] 테스트셋에서 {args.num_samples}장 테스트')
        test_images = get_test_images(args.num_samples)

        if not test_images:
            print('[Error] 테스트 이미지를 가져올 수 없습니다')
            sys.exit(1)

        all_results = []
        for i, img_info in enumerate(test_images, 1):
            print(f'\n--- [{i}/{len(test_images)}] {img_info["dicom_id"]} ---')
            result = detector.predict(img_info['path'])
            print_result(result, gt_labels=img_info['gt_labels'], idx=i)
            all_results.append({
                'result': result,
                'gt_labels': img_info['gt_labels'],
                'dicom_id': img_info['dicom_id'],
            })

        print_summary(all_results)


if __name__ == '__main__':
    main()
