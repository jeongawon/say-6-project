"""
DenseNet-121 종합 성능평가 — 로컬 실행 버전
테스트 이미지를 S3에서 직접 다운로드하여 평가.
998장 테스트셋 × 14개 질환 전체 메트릭 산출.
"""
import os
import sys
import json
import time
import io
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from torchvision import models, transforms
from PIL import Image
import boto3
from sklearn.metrics import (
    roc_auc_score, roc_curve,
    f1_score, confusion_matrix
)

# ============================================================
WORK_BUCKET = 'pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an'
IMAGE_BUCKET = 'say1-pre-project-5'
MODEL_S3_KEY = 'models/detection/densenet121.pth'
S3_IMAGE_PREFIX = 'data/mimic-cxr-jpg/'
REGION = 'ap-northeast-2'

LABEL_COLS = [
    'Atelectasis', 'Cardiomegaly', 'Consolidation', 'Edema',
    'Enlarged Cardiomediastinum', 'Fracture', 'Lung Lesion', 'Lung Opacity',
    'No Finding', 'Pleural Effusion', 'Pleural Other', 'Pneumonia',
    'Pneumothorax', 'Support Devices'
]
NUM_CLASSES = 14
THRESHOLD = 0.5

CHEXPERT_BENCHMARK = {
    'Atelectasis': 0.858,
    'Cardiomegaly': 0.854,
    'Consolidation': 0.939,
    'Edema': 0.941,
    'Pleural Effusion': 0.936,
}


# ============================================================
# 데이터 준비
# ============================================================
def build_test_df():
    print("[1/4] 테스트셋 CSV 빌드")
    s3 = boto3.client('s3', region_name=REGION)

    print("  metadata 로드...")
    resp = s3.get_object(Bucket=WORK_BUCKET, Key='mimic-cxr-csv/mimic-cxr-2.0.0-metadata.csv')
    meta = pd.read_csv(io.BytesIO(resp['Body'].read()))
    print(f"    {len(meta):,}행")

    print("  split 로드...")
    resp = s3.get_object(Bucket=WORK_BUCKET, Key='mimic-cxr-csv/mimic-cxr-2.0.0-split.csv')
    split = pd.read_csv(io.BytesIO(resp['Body'].read()))

    print("  chexpert 로드...")
    resp = s3.get_object(Bucket=WORK_BUCKET, Key='mimic-cxr-csv/mimic-cxr-2.0.0-chexpert.csv')
    chex = pd.read_csv(io.BytesIO(resp['Body'].read()))

    meta_pa = meta[meta['ViewPosition'] == 'PA']
    df = meta_pa.merge(chex, on=['subject_id', 'study_id'], how='inner')
    df = df.merge(split, on=['subject_id', 'study_id', 'dicom_id'], how='inner')

    for col in LABEL_COLS:
        df[col] = df[col].fillna(0).replace(-1, 1).astype(int)

    def build_path(row):
        sid = str(row['subject_id'])
        return f"files/p{sid[:2]}/p{sid}/s{row['study_id']}/{row['dicom_id']}.jpg"
    df['image_path'] = df.apply(build_path, axis=1)

    test_df = df[df['split'] == 'test'].reset_index(drop=True)
    print(f"  테스트셋: {len(test_df):,}장")
    return test_df


def download_test_images(test_df, local_dir):
    print(f"\n[2/4] 테스트 이미지 다운로드 ({len(test_df)}장)")

    to_download = []
    for _, row in test_df.iterrows():
        s3_key = S3_IMAGE_PREFIX + row['image_path']
        local_path = os.path.join(local_dir, row['image_path'])
        if not os.path.exists(local_path):
            to_download.append((s3_key, local_path))

    if not to_download:
        print(f"  캐시 완료")
        return

    # 디렉토리 생성
    dirs = set(os.path.dirname(p) for _, p in to_download)
    for d in dirs:
        os.makedirs(d, exist_ok=True)

    print(f"  다운로드: {len(to_download)}개")
    start = time.time()
    done = [0, 0]

    def _dl(item):
        thread_s3 = boto3.client('s3', region_name=REGION)
        key, path = item
        for attempt in range(3):
            try:
                thread_s3.download_file(IMAGE_BUCKET, key, path)
                return True
            except Exception:
                if attempt < 2:
                    time.sleep(1)
        return False

    with ThreadPoolExecutor(max_workers=16) as ex:
        futures = {ex.submit(_dl, item): item for item in to_download}
        for future in as_completed(futures):
            ok = future.result()
            done[0 if ok else 1] += 1
            total = sum(done)
            if total % 100 == 0 or total == len(to_download):
                elapsed = time.time() - start
                rate = total / elapsed if elapsed > 0 else 0
                pct = total / len(to_download) * 100
                eta = (len(to_download) - total) / rate if rate > 0 else 0
                print(f"  {total}/{len(to_download)} ({pct:.0f}%) | {rate:.0f}/s | ETA ~{eta:.0f}s")

    print(f"  완료: {done[0]}개 성공, {done[1]}개 실패 ({time.time()-start:.0f}초)")


# ============================================================
# Dataset
# ============================================================
class TestDataset(Dataset):
    def __init__(self, df, label_cols, image_dir, transform):
        self.df = df.reset_index(drop=True)
        self.label_cols = label_cols
        self.image_dir = image_dir
        self.transform = transform

    def __len__(self):
        return len(self.df)

    def __getitem__(self, idx):
        row = self.df.iloc[idx]
        img_path = os.path.join(self.image_dir, row['image_path'])
        labels = torch.tensor([row[col] for col in self.label_cols], dtype=torch.float32)
        try:
            img = Image.open(img_path).convert('RGB')
            if self.transform:
                img = self.transform(img)
        except Exception:
            img = torch.zeros(3, 224, 224)
        return img, labels


# ============================================================
# 메인
# ============================================================
def main():
    total_start = time.time()
    device = torch.device('cpu')
    print(f"Device: {device}\n")

    # 1. CSV
    test_df = build_test_df()

    # 2. 이미지 다운로드
    cache_dir = os.path.join(tempfile.gettempdir(), 'mimic_test_cache')
    download_test_images(test_df, cache_dir)

    # 3. 모델
    print(f"\n[3/4] 모델 로드")
    model_path = os.path.join(tempfile.gettempdir(), 'best_model.pth')
    if not os.path.exists(model_path):
        s3 = boto3.client('s3', region_name=REGION)
        print(f"  S3 다운로드: s3://{WORK_BUCKET}/{MODEL_S3_KEY}")
        s3.download_file(WORK_BUCKET, MODEL_S3_KEY, model_path)

    size_mb = os.path.getsize(model_path) / 1024 / 1024
    print(f"  모델 크기: {size_mb:.1f}MB")

    densenet = models.densenet121(weights=None)
    densenet.classifier = nn.Linear(densenet.classifier.in_features, NUM_CLASSES)
    state_dict = torch.load(model_path, map_location='cpu', weights_only=False)
    if isinstance(state_dict, dict) and 'model_state_dict' in state_dict:
        state_dict = state_dict['model_state_dict']
    if any(k.startswith('module.') for k in state_dict.keys()):
        state_dict = {k.replace('module.', ''): v for k, v in state_dict.items()}
    densenet.load_state_dict(state_dict)
    densenet.eval()
    print("  로드 완료")

    # 4. 추론
    print(f"\n[4/4] 추론 ({len(test_df)}장)")
    val_transform = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
    ])
    dataset = TestDataset(test_df, LABEL_COLS, cache_dir, val_transform)
    loader = DataLoader(dataset, batch_size=32, shuffle=False, num_workers=0)

    all_preds, all_labels = [], []
    infer_start = time.time()

    with torch.inference_mode():
        for batch_idx, (images, labels) in enumerate(loader):
            logits = densenet(images)
            probs = torch.sigmoid(logits).numpy()
            all_preds.append(probs)
            all_labels.append(labels.numpy())
            done = (batch_idx + 1) * images.shape[0]
            elapsed = time.time() - infer_start
            rate = done / elapsed if elapsed > 0 else 0
            eta = (len(test_df) - done) / rate if rate > 0 else 0
            print(f"  {done}/{len(test_df)} ({done/len(test_df)*100:.0f}%) | {rate:.0f}img/s | ETA ~{eta:.0f}s")

    all_preds = np.concatenate(all_preds)
    all_labels = np.concatenate(all_labels)
    print(f"  추론 완료: {time.time()-infer_start:.1f}초")

    # ============================================================
    # 메트릭 산출
    # ============================================================
    print("\n" + "=" * 70)
    print("  DenseNet-121 14-Disease Detection - Performance Evaluation")
    print("=" * 70)
    print(f"\n  테스트셋: {len(all_labels)}장 (MIMIC-CXR PA)")
    print(f"  판정 임계값: {THRESHOLD}")

    all_binary = (all_preds >= THRESHOLD).astype(int)
    results = {'per_class': {}}

    print(f"\n{'─' * 70}")
    print(f"  {'질환':<28} {'AUROC':>7} {'Sens':>7} {'Spec':>7} {'Prec':>7} {'F1':>7} {'Prev':>6}")
    print(f"{'─' * 70}")

    aurocs_list = []
    roc_data = {}

    for i, disease in enumerate(LABEL_COLS):
        y_true = all_labels[:, i]
        y_prob = all_preds[:, i]
        y_pred = all_binary[:, i]

        m = {}
        # AUROC
        try:
            if len(np.unique(y_true)) > 1:
                m['auroc'] = float(roc_auc_score(y_true, y_prob))
                aurocs_list.append(m['auroc'])
                fpr, tpr, thresholds = roc_curve(y_true, y_prob)
                j_scores = tpr - fpr
                best_idx = np.argmax(j_scores)
                m['optimal_threshold'] = float(thresholds[best_idx])
                roc_data[disease] = {'fpr': fpr.tolist(), 'tpr': tpr.tolist()}
            else:
                m['auroc'] = None
                m['optimal_threshold'] = THRESHOLD
        except Exception:
            m['auroc'] = None
            m['optimal_threshold'] = THRESHOLD

        # Confusion matrix
        tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
        m['tp'], m['fp'], m['tn'], m['fn'] = int(tp), int(fp), int(tn), int(fn)
        m['sensitivity'] = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0
        m['specificity'] = float(tn / (tn + fp)) if (tn + fp) > 0 else 0.0
        m['precision'] = float(tp / (tp + fp)) if (tp + fp) > 0 else 0.0
        m['npv'] = float(tn / (tn + fn)) if (tn + fn) > 0 else 0.0
        m['f1'] = float(2 * tp / (2 * tp + fp + fn)) if (2 * tp + fp + fn) > 0 else 0.0
        m['accuracy'] = float((tp + tn) / (tp + tn + fp + fn))
        m['prevalence'] = float((tp + fn) / len(y_true))

        auroc_str = f"{m['auroc']:.4f}" if m['auroc'] is not None else "  N/A "
        print(f"  {disease:<28} {auroc_str:>7} {m['sensitivity']:>7.4f} "
              f"{m['specificity']:>7.4f} {m['precision']:>7.4f} {m['f1']:>7.4f} "
              f"{m['prevalence']:>5.1%}")

        results['per_class'][disease] = m

    # 전체 요약
    mean_auroc = float(np.mean(aurocs_list)) if aurocs_list else 0.0
    f1s = [m['f1'] for m in results['per_class'].values()]
    sens = [m['sensitivity'] for m in results['per_class'].values()]
    specs = [m['specificity'] for m in results['per_class'].values()]

    print(f"\n{'─' * 70}")
    print(f"  전체 요약")
    print(f"{'─' * 70}")
    print(f"  Mean AUROC      : {mean_auroc:.4f}")
    print(f"  Mean Sensitivity: {np.mean(sens):.4f}")
    print(f"  Mean Specificity: {np.mean(specs):.4f}")
    print(f"  Mean F1         : {np.mean(f1s):.4f}")
    print(f"  Macro F1        : {f1_score(all_labels, all_binary, average='macro'):.4f}")
    print(f"  Micro F1        : {f1_score(all_labels, all_binary, average='micro'):.4f}")

    # 벤치마크 비교
    print(f"\n{'─' * 70}")
    print(f"  CheXpert 벤치마크 비교 (5개 경쟁 질환)")
    print(f"{'─' * 70}")
    print(f"  {'질환':<28} {'Ours':>7} {'CheXpert':>9} {'차이':>7}")
    print(f"{'─' * 70}")
    for disease, bench in CHEXPERT_BENCHMARK.items():
        m = results['per_class'].get(disease, {})
        ours = m.get('auroc')
        if ours is not None:
            diff = ours - bench
            sign = "+" if diff >= 0 else ""
            print(f"  {disease:<28} {ours:>7.4f} {bench:>9.4f} {sign}{diff:>6.4f}")

    # Confusion matrix
    print(f"\n{'─' * 70}")
    print(f"  Confusion Matrix")
    print(f"{'─' * 70}")
    print(f"  {'질환':<28} {'TP':>5} {'FP':>5} {'FN':>5} {'TN':>5} {'Opt.Thr':>8}")
    print(f"{'─' * 70}")
    for disease in LABEL_COLS:
        m = results['per_class'][disease]
        print(f"  {disease:<28} {m['tp']:>5} {m['fp']:>5} "
              f"{m['fn']:>5} {m['tn']:>5} {m['optimal_threshold']:>8.4f}")

    print(f"\n{'=' * 70}")

    # 결과 저장
    results['summary'] = {
        'mean_auroc': mean_auroc,
        'mean_f1': float(np.mean(f1s)),
        'mean_sensitivity': float(np.mean(sens)),
        'mean_specificity': float(np.mean(specs)),
        'macro_f1': float(f1_score(all_labels, all_binary, average='macro')),
        'micro_f1': float(f1_score(all_labels, all_binary, average='micro')),
        'total_samples': len(all_labels),
    }

    out_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(out_dir, 'eval_results.json'), 'w') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    with open(os.path.join(out_dir, 'roc_data.json'), 'w') as f:
        json.dump(roc_data, f)
    print(f"\n  결과 저장: {out_dir}/eval_results.json")

    # S3에도 업로드
    try:
        s3 = boto3.client('s3', region_name=REGION)
        s3.upload_file(os.path.join(out_dir, 'eval_results.json'), WORK_BUCKET,
                       'output/densenet121-eval/eval_results.json')
        print(f"  S3 업로드: s3://{WORK_BUCKET}/output/densenet121-eval/eval_results.json")
    except Exception as e:
        print(f"  S3 업로드 실패: {e}")

    total_time = time.time() - total_start
    print(f"\n  총 소요: {total_time/60:.1f}분")


if __name__ == '__main__':
    main()
