"""
DenseNet-121 종합 성능평가 스크립트 — SageMaker Training Job으로 실행
998장 테스트셋에 대해 14개 질환 전체 메트릭 산출.

출력:
  /opt/ml/model/eval_results.json   — 전체 수치 결과
  /opt/ml/model/eval_report.txt     — 사람이 읽을 수 있는 리포트
  /opt/ml/model/roc_data.json       — ROC 커브 데이터 (FPR/TPR per class)
"""
import os
import sys
import json
import time
import gzip
import io
import argparse

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from torchvision import models, transforms
from PIL import Image
import boto3
from concurrent.futures import ThreadPoolExecutor
from sklearn.metrics import (
    roc_auc_score, roc_curve,
    f1_score, precision_score, recall_score,
    classification_report, confusion_matrix
)

# ============================================================
# 상수
# ============================================================
SM_MODEL_DIR = os.environ.get('SM_MODEL_DIR', '/opt/ml/model')
DATA_DIR = os.environ.get('SM_CHANNEL_TRAINING', '/opt/ml/input/data/training')

LABEL_COLS = [
    'Atelectasis', 'Cardiomegaly', 'Consolidation', 'Edema',
    'Enlarged Cardiomediastinum', 'Fracture', 'Lung Lesion', 'Lung Opacity',
    'No Finding', 'Pleural Effusion', 'Pleural Other', 'Pneumonia',
    'Pneumothorax', 'Support Devices'
]
NUM_CLASSES = 14
THRESHOLD = 0.5

# CheXpert 논문 벤치마크 (Stanford, Irvin et al. 2019 — radiologist average)
CHEXPERT_BENCHMARK = {
    'Atelectasis': 0.858,
    'Cardiomegaly': 0.854,
    'Consolidation': 0.939,
    'Edema': 0.941,
    'Pleural Effusion': 0.936,
}


# ============================================================
# 데이터 준비 (train_multigpu.py 로직 재활용)
# ============================================================
def load_csv_from_s3(name, work_bucket, image_bucket):
    s3 = boto3.client('s3')
    candidates = [
        (work_bucket, f'mimic-cxr-csv/{name}'),
        (work_bucket, f'mimic-cxr-csv/{name}.gz'),
        (image_bucket, name),
        (image_bucket, f'{name}.gz'),
    ]
    for bucket, key in candidates:
        try:
            resp = s3.get_object(Bucket=bucket, Key=key)
            data = resp['Body'].read()
            if key.endswith('.gz'):
                data = gzip.decompress(data)
            df = pd.read_csv(io.BytesIO(data))
            print(f"  CSV 로드: s3://{bucket}/{key} ({len(df):,}행)")
            return df
        except Exception:
            pass
    raise FileNotFoundError(f"CSV not found: {name}")


def build_test_csv(image_bucket, work_bucket):
    print("\n[데이터] CSV 빌드")
    meta = load_csv_from_s3('mimic-cxr-2.0.0-metadata.csv', work_bucket, image_bucket)
    split = load_csv_from_s3('mimic-cxr-2.0.0-split.csv', work_bucket, image_bucket)
    chex = load_csv_from_s3('mimic-cxr-2.0.0-chexpert.csv', work_bucket, image_bucket)

    meta_pa = meta[meta['ViewPosition'] == 'PA'].copy()
    df = meta_pa.merge(chex, on=['subject_id', 'study_id'], how='inner')
    df = df.merge(split, on=['subject_id', 'study_id', 'dicom_id'], how='inner')

    for col in LABEL_COLS:
        df[col] = df[col].fillna(0).replace(-1, 1).astype(int)

    def build_image_path(row):
        sid = str(row['subject_id'])
        return f"files/p{sid[:2]}/p{sid}/s{row['study_id']}/{row['dicom_id']}.jpg"

    df['image_path'] = df.apply(build_image_path, axis=1)

    test_df = df[df['split'] == 'test'].copy()
    print(f"  테스트셋: {len(test_df):,}장")
    return test_df


def download_images(df, bucket, local_dir, max_workers=32):
    S3_PREFIX = 'data/mimic-cxr-jpg/'
    to_download = []
    for _, row in df.iterrows():
        s3_key = S3_PREFIX + row['image_path']
        local_path = os.path.join(local_dir, row['image_path'])
        if not os.path.exists(local_path):
            to_download.append((s3_key, local_path))

    if not to_download:
        print(f"  이미지 캐시 완료 ({len(df):,}개)")
        return

    print(f"  다운로드: {len(to_download):,}개")
    dirs = set(os.path.dirname(p) for _, p in to_download)
    for d in dirs:
        os.makedirs(d, exist_ok=True)

    start = time.time()
    done = [0, 0]

    def _dl(item):
        thread_s3 = boto3.client('s3')
        key, path = item
        for attempt in range(3):
            try:
                thread_s3.download_file(bucket, key, path)
                return True
            except Exception:
                if attempt < 2:
                    time.sleep(1)
        return False

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for ok in ex.map(_dl, to_download):
            done[0 if ok else 1] += 1
            total = sum(done)
            if total % 200 == 0 or total == len(to_download):
                elapsed = time.time() - start
                rate = total / elapsed if elapsed > 0 else 0
                pct = total / len(to_download) * 100
                print(f"  {total:,}/{len(to_download):,} ({pct:.1f}%) | {rate:.0f}/s")

    print(f"  완료: {done[0]:,}개, 오류: {done[1]}")


# ============================================================
# Dataset
# ============================================================
class TestDataset(Dataset):
    def __init__(self, dataframe, label_cols, image_base_dir, transform):
        self.df = dataframe.reset_index(drop=True)
        self.label_cols = label_cols
        self.image_base_dir = image_base_dir
        self.transform = transform

    def __len__(self):
        return len(self.df)

    def __getitem__(self, idx):
        row = self.df.iloc[idx]
        img_path = os.path.join(self.image_base_dir, row['image_path'])
        labels = torch.tensor([row[col] for col in self.label_cols], dtype=torch.float32)
        try:
            img = Image.open(img_path).convert('RGB')
            if self.transform:
                img = self.transform(img)
        except Exception:
            img = torch.zeros(3, 224, 224)
        return img, labels


# ============================================================
# 모델 로드
# ============================================================
def load_model(model_bucket, model_key):
    print("\n[모델] 로드")
    local_path = '/tmp/best_model.pth'
    if not os.path.exists(local_path):
        s3 = boto3.client('s3')
        print(f"  S3 다운로드: s3://{model_bucket}/{model_key}")
        s3.download_file(model_bucket, model_key, local_path)

    size_mb = os.path.getsize(local_path) / 1024 / 1024
    print(f"  크기: {size_mb:.1f}MB")

    densenet = models.densenet121(weights=None)
    num_features = densenet.classifier.in_features
    densenet.classifier = nn.Linear(num_features, NUM_CLASSES)

    state_dict = torch.load(local_path, map_location='cpu', weights_only=False)
    if isinstance(state_dict, dict) and 'model_state_dict' in state_dict:
        state_dict = state_dict['model_state_dict']
    if any(k.startswith('module.') for k in state_dict.keys()):
        state_dict = {k.replace('module.', ''): v for k, v in state_dict.items()}

    densenet.load_state_dict(state_dict)
    densenet.eval()
    print("  로드 완료")
    return densenet


# ============================================================
# 추론
# ============================================================
def run_inference(model, dataloader, device):
    print("\n[추론] 시작")
    all_preds, all_labels = [], []
    start = time.time()

    with torch.inference_mode():
        for batch_idx, (images, labels) in enumerate(dataloader):
            images = images.to(device)
            logits = model(images)
            probs = torch.sigmoid(logits).cpu().numpy()
            all_preds.append(probs)
            all_labels.append(labels.numpy())

            if (batch_idx + 1) % 10 == 0:
                done = (batch_idx + 1) * images.shape[0]
                elapsed = time.time() - start
                print(f"  {done}장 완료 ({elapsed:.1f}초)")

    all_preds = np.concatenate(all_preds)
    all_labels = np.concatenate(all_labels)
    total_time = time.time() - start
    print(f"  추론 완료: {len(all_preds)}장, {total_time:.1f}초")
    return all_preds, all_labels


# ============================================================
# 메트릭 산출
# ============================================================
def compute_metrics(all_preds, all_labels, threshold=THRESHOLD):
    print("\n[평가] 메트릭 산출")
    results = {'per_class': {}, 'roc_data': {}}
    all_binary = (all_preds >= threshold).astype(int)

    for i, disease in enumerate(LABEL_COLS):
        y_true = all_labels[:, i]
        y_prob = all_preds[:, i]
        y_pred = all_binary[:, i]

        metrics = {}

        # AUROC
        try:
            if len(np.unique(y_true)) > 1:
                metrics['auroc'] = float(roc_auc_score(y_true, y_prob))
                fpr, tpr, thresholds = roc_curve(y_true, y_prob)
                # Youden's J로 최적 threshold 계산
                j_scores = tpr - fpr
                best_idx = np.argmax(j_scores)
                metrics['optimal_threshold'] = float(thresholds[best_idx])
                results['roc_data'][disease] = {
                    'fpr': fpr.tolist(),
                    'tpr': tpr.tolist(),
                }
            else:
                metrics['auroc'] = None
                metrics['optimal_threshold'] = threshold
        except Exception:
            metrics['auroc'] = None
            metrics['optimal_threshold'] = threshold

        # Confusion Matrix
        tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
        metrics['tp'] = int(tp)
        metrics['fp'] = int(fp)
        metrics['tn'] = int(tn)
        metrics['fn'] = int(fn)

        # 기본 메트릭
        metrics['sensitivity'] = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0  # recall
        metrics['specificity'] = float(tn / (tn + fp)) if (tn + fp) > 0 else 0.0
        metrics['precision'] = float(tp / (tp + fp)) if (tp + fp) > 0 else 0.0  # PPV
        metrics['npv'] = float(tn / (tn + fn)) if (tn + fn) > 0 else 0.0
        metrics['f1'] = float(2 * tp / (2 * tp + fp + fn)) if (2 * tp + fp + fn) > 0 else 0.0
        metrics['accuracy'] = float((tp + tn) / (tp + tn + fp + fn))
        metrics['prevalence'] = float((tp + fn) / len(y_true))
        metrics['positive_count'] = int(tp + fn)
        metrics['negative_count'] = int(tn + fp)

        # 벤치마크 비교
        if disease in CHEXPERT_BENCHMARK:
            metrics['chexpert_benchmark'] = CHEXPERT_BENCHMARK[disease]
            if metrics['auroc'] is not None:
                metrics['vs_benchmark'] = round(metrics['auroc'] - CHEXPERT_BENCHMARK[disease], 4)

        results['per_class'][disease] = metrics

    # 전체 요약
    aurocs = [m['auroc'] for m in results['per_class'].values() if m['auroc'] is not None]
    f1s = [m['f1'] for m in results['per_class'].values()]
    sensitivities = [m['sensitivity'] for m in results['per_class'].values()]
    specificities = [m['specificity'] for m in results['per_class'].values()]

    results['summary'] = {
        'mean_auroc': float(np.mean(aurocs)) if aurocs else 0.0,
        'mean_f1': float(np.mean(f1s)),
        'mean_sensitivity': float(np.mean(sensitivities)),
        'mean_specificity': float(np.mean(specificities)),
        'macro_f1': float(f1_score(all_labels, all_binary, average='macro')),
        'micro_f1': float(f1_score(all_labels, all_binary, average='micro')),
        'total_samples': len(all_labels),
        'threshold': threshold,
    }

    return results


# ============================================================
# 리포트 생성
# ============================================================
def generate_report(results):
    lines = []
    s = results['summary']

    lines.append("=" * 70)
    lines.append("  DenseNet-121 14-Disease Detection — 종합 성능평가 리포트")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"  테스트셋: {s['total_samples']}장 (MIMIC-CXR PA)")
    lines.append(f"  판정 임계값: {s['threshold']}")
    lines.append("")
    lines.append("─" * 70)
    lines.append("  전체 요약")
    lines.append("─" * 70)
    lines.append(f"  Mean AUROC      : {s['mean_auroc']:.4f}")
    lines.append(f"  Mean Sensitivity: {s['mean_sensitivity']:.4f}")
    lines.append(f"  Mean Specificity: {s['mean_specificity']:.4f}")
    lines.append(f"  Mean F1         : {s['mean_f1']:.4f}")
    lines.append(f"  Macro F1        : {s['macro_f1']:.4f}")
    lines.append(f"  Micro F1        : {s['micro_f1']:.4f}")
    lines.append("")

    # 질환별 상세
    lines.append("─" * 70)
    lines.append(f"  {'질환':<28} {'AUROC':>7} {'Sens':>7} {'Spec':>7} {'Prec':>7} {'F1':>7} {'Prev':>6}")
    lines.append("─" * 70)

    sorted_diseases = sorted(
        results['per_class'].items(),
        key=lambda x: x[1]['auroc'] if x[1]['auroc'] is not None else 0,
        reverse=True
    )
    for disease, m in sorted_diseases:
        auroc = f"{m['auroc']:.4f}" if m['auroc'] is not None else "  N/A "
        lines.append(
            f"  {disease:<28} {auroc:>7} {m['sensitivity']:>7.4f} "
            f"{m['specificity']:>7.4f} {m['precision']:>7.4f} {m['f1']:>7.4f} "
            f"{m['prevalence']:>5.1%}"
        )
    lines.append("")

    # 벤치마크 비교
    lines.append("─" * 70)
    lines.append("  CheXpert 벤치마크 비교 (5개 경쟁 질환)")
    lines.append("─" * 70)
    lines.append(f"  {'질환':<28} {'Ours':>7} {'CheXpert':>9} {'차이':>7}")
    lines.append("─" * 70)
    for disease in CHEXPERT_BENCHMARK:
        m = results['per_class'].get(disease, {})
        ours = m.get('auroc')
        bench = CHEXPERT_BENCHMARK[disease]
        if ours is not None:
            diff = ours - bench
            sign = "+" if diff >= 0 else ""
            lines.append(f"  {disease:<28} {ours:>7.4f} {bench:>9.4f} {sign}{diff:>6.4f}")
    lines.append("")

    # Confusion Matrix 요약
    lines.append("─" * 70)
    lines.append("  Confusion Matrix 요약")
    lines.append("─" * 70)
    lines.append(f"  {'질환':<28} {'TP':>5} {'FP':>5} {'FN':>5} {'TN':>5} {'Opt.Thr':>8}")
    lines.append("─" * 70)
    for disease, m in sorted_diseases:
        lines.append(
            f"  {disease:<28} {m['tp']:>5} {m['fp']:>5} "
            f"{m['fn']:>5} {m['tn']:>5} {m['optimal_threshold']:>8.4f}"
        )
    lines.append("")
    lines.append("=" * 70)

    return "\n".join(lines)


# ============================================================
# 메인
# ============================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image-bucket', type=str, default='say1-pre-project-5')
    parser.add_argument('--work-bucket', type=str,
                        default='pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an')
    parser.add_argument('--model-key', type=str, default='models/detection/densenet121.pth')
    parser.add_argument('--batch-size', type=int, default=64)
    parser.add_argument('--num-workers', type=int, default=4)
    args = parser.parse_args()

    total_start = time.time()
    device = torch.device('cpu')
    print(f"Device: {device}")

    # 1. 데이터
    images_dir = os.path.join('/opt/ml/input/data', 'images_cache')
    os.makedirs(images_dir, exist_ok=True)
    test_df = build_test_csv(args.image_bucket, args.work_bucket)
    download_images(test_df, args.image_bucket, images_dir)

    # 2. 모델
    model = load_model(args.work_bucket, args.model_key)
    model.to(device)

    # 3. DataLoader
    val_transform = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406],
                             std=[0.229, 0.224, 0.225])
    ])
    test_dataset = TestDataset(test_df, LABEL_COLS, images_dir, val_transform)
    test_loader = DataLoader(test_dataset, batch_size=args.batch_size,
                             shuffle=False, num_workers=args.num_workers)

    # 4. 추론
    all_preds, all_labels = run_inference(model, test_loader, device)

    # 5. 메트릭
    results = compute_metrics(all_preds, all_labels)
    results['model_info'] = {
        'model_key': args.model_key,
        'architecture': 'DenseNet-121',
        'num_classes': NUM_CLASSES,
        'eval_time_minutes': round((time.time() - total_start) / 60, 2),
    }

    # 6. 저장
    os.makedirs(SM_MODEL_DIR, exist_ok=True)

    # JSON 결과 (ROC 데이터 분리)
    roc_data = results.pop('roc_data')
    with open(os.path.join(SM_MODEL_DIR, 'eval_results.json'), 'w') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    with open(os.path.join(SM_MODEL_DIR, 'roc_data.json'), 'w') as f:
        json.dump(roc_data, f)

    # 텍스트 리포트
    results['roc_data'] = roc_data  # 리포트 생성용 복원
    report = generate_report(results)
    print("\n" + report)
    with open(os.path.join(SM_MODEL_DIR, 'eval_report.txt'), 'w', encoding='utf-8') as f:
        f.write(report)

    total_time = time.time() - total_start
    print(f"\n총 소요: {total_time/60:.1f}분")


if __name__ == '__main__':
    main()
