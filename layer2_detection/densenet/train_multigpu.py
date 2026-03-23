"""
DenseNet-121 14-Disease Multi-label Classification — Multi-GPU SageMaker 스크립트 v2

ml.g5.12xlarge (A10G x4, 48 vCPU, 192GB RAM) 최적화 버전.
- nn.DataParallel로 4 GPU 병렬 학습
- 배치 128 (GPU당 32), num_workers 16
- EFA/NCCL/OMP 환경변수 사전 설정
- S3 다운로드 thread-safe (스레드별 클라이언트)
- gradient clipping, drop_last, atomic checkpoint

=== 2-Stage Fine-tuning ===
- Stage 1: classifier만 학습 (feature extractor 동결)
- Stage 2: 전체 네트워크 fine-tuning (낮은 LR)
"""

import argparse
import os
import sys
import json
import time
import gzip
import io
import subprocess

# ============================================================
# 환경변수 — 반드시 torch import 전에 설정
# ============================================================
# EFA fork 안전 모드 (DataLoader fork() 크래시 방지)
os.environ['FI_EFA_FORK_SAFE'] = '1'
os.environ['RDMAV_FORK_SAFE'] = '1'

# NCCL 통신 안정화 (g5 인스턴스는 InfiniBand 없음)
os.environ['NCCL_IB_DISABLE'] = '1'
os.environ['NCCL_ASYNC_ERROR_HANDLING'] = '1'
os.environ['TORCH_NCCL_ASYNC_ERROR_HANDLING'] = '1'
os.environ['NCCL_SOCKET_IFNAME'] = 'eth0'
os.environ['NCCL_DEBUG'] = 'WARN'

# CPU 스레드 제어 (48 vCPU / 4 GPU = 12, 여유 두고 4)
os.environ['OMP_NUM_THREADS'] = '4'

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from torchvision import models, transforms
from PIL import Image
from sklearn.metrics import roc_auc_score
import boto3
from concurrent.futures import ThreadPoolExecutor

# ============================================================
# 상수
# ============================================================
SM_MODEL_DIR = os.environ.get('SM_MODEL_DIR', '/opt/ml/model')
SM_OUTPUT_DATA_DIR = os.environ.get('SM_OUTPUT_DATA_DIR', '/opt/ml/output/data')
CHECKPOINT_DIR = '/opt/ml/checkpoints'
DATA_DIR = '/opt/ml/input/data'

LABEL_COLS = [
    'Atelectasis', 'Cardiomegaly', 'Consolidation', 'Edema',
    'Enlarged Cardiomediastinum', 'Fracture', 'Lung Lesion', 'Lung Opacity',
    'No Finding', 'Pleural Effusion', 'Pleural Other', 'Pneumonia',
    'Pneumothorax', 'Support Devices'
]
NUM_CLASSES = 14


# ============================================================
# Multi-GPU 헬퍼
# ============================================================
def unwrap_model(model):
    """DataParallel로 감싼 모델에서 원본 모델 추출"""
    return model.module if isinstance(model, nn.DataParallel) else model


# ============================================================
# Phase 1: 데이터 준비
# ============================================================
def load_csv_from_s3(name, work_bucket, image_bucket):
    """S3에서 CSV 로드 — 작업 버킷 mimic-cxr-csv/ 우선, 이미지 버킷 루트 폴백"""
    s3 = boto3.client('s3')

    candidates = [
        (work_bucket, f'mimic-cxr-csv/{name}'),
        (work_bucket, f'mimic-cxr-csv/{name}.gz'),
        (image_bucket, name),
        (image_bucket, f'{name}.gz'),
    ]

    for bucket, key in candidates:
        try:
            print(f"  시도: s3://{bucket}/{key}")
            resp = s3.get_object(Bucket=bucket, Key=key)
            data = resp['Body'].read()
            if key.endswith('.gz'):
                data = gzip.decompress(data)
            df = pd.read_csv(io.BytesIO(data))
            print(f"  성공: {len(df):,}행")
            return df
        except Exception as e:
            print(f"    실패: {e}")

    raise FileNotFoundError(f"CSV not found: {name}")


def build_full_pa_csv(image_bucket, work_bucket):
    """
    소스 CSV 3종 → 전체 PA Master CSV 생성.
    377K → PA ~96K → 라벨 정리 → ~94K
    """
    print("\n[1/3] 소스 CSV 로드")
    meta = load_csv_from_s3('mimic-cxr-2.0.0-metadata.csv', work_bucket, image_bucket)
    split = load_csv_from_s3('mimic-cxr-2.0.0-split.csv', work_bucket, image_bucket)
    chex = load_csv_from_s3('mimic-cxr-2.0.0-chexpert.csv', work_bucket, image_bucket)

    print(f"\n[2/3] PA 필터 + 병합")
    meta_pa = meta[meta['ViewPosition'] == 'PA'].copy()
    print(f"  PA 필터: {len(meta):,} → {len(meta_pa):,}")

    df = meta_pa.merge(chex, on=['subject_id', 'study_id'], how='inner')
    print(f"  라벨 병합: {len(df):,}")

    df = df.merge(split, on=['subject_id', 'study_id', 'dicom_id'], how='inner')
    print(f"  Split 병합: {len(df):,}")

    # U-Ones: NaN → 0, -1(uncertain) → 1
    for col in LABEL_COLS:
        df[col] = df[col].fillna(0).replace(-1, 1).astype(int)

    def build_image_path(row):
        sid = str(row['subject_id'])
        group = sid[:2]
        return f"files/p{group}/p{sid}/s{row['study_id']}/{row['dicom_id']}.jpg"

    df['image_path'] = df.apply(build_image_path, axis=1)

    print(f"\n[3/3] 최종 데이터")
    print(f"  전체: {len(df):,}행")
    print(f"  Split: {df['split'].value_counts().to_dict()}")

    return df


def download_needed_images(df, bucket, local_dir, max_workers=64):
    """PA 이미지만 S3에서 선택 다운로드 — 스레드별 S3 클라이언트 생성"""
    S3_PREFIX = 'data/mimic-cxr-jpg/'

    to_download = []
    for _, row in df.iterrows():
        img_rel = row['image_path']
        s3_key = S3_PREFIX + img_rel
        local_path = os.path.join(local_dir, img_rel)
        if not os.path.exists(local_path):
            to_download.append((s3_key, local_path))

    already = len(df) - len(to_download)
    if not to_download:
        print(f"  이미지 캐시 완료 ({already:,}개)")
        return

    print(f"  다운로드: {len(to_download):,}개 (캐시: {already:,}개)")

    dirs = set(os.path.dirname(p) for _, p in to_download)
    for d in dirs:
        os.makedirs(d, exist_ok=True)

    start = time.time()
    done = [0, 0]

    def _dl(item):
        """스레드별로 S3 클라이언트 생성 (boto3는 thread-safe 아님)"""
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
            if total % 5000 == 0 or total == len(to_download):
                elapsed = time.time() - start
                rate = total / elapsed if elapsed > 0 else 0
                eta = (len(to_download) - total) / rate if rate > 0 else 0
                pct = total / len(to_download) * 100
                print(f"  {total:,}/{len(to_download):,} ({pct:.1f}%) | "
                      f"{rate:.0f}/s | ETA ~{eta/60:.1f}분")

    elapsed = time.time() - start
    print(f"  완료: {done[0]:,}개 ({elapsed/60:.1f}분), 오류: {done[1]}")


def check_disk_space(path='/opt/ml'):
    """디스크 사용량 출력"""
    try:
        stat = os.statvfs(path)
        total = stat.f_blocks * stat.f_frsize / (1024**3)
        free = stat.f_bfree * stat.f_frsize / (1024**3)
        used = total - free
        print(f"  디스크: {used:.1f}GB / {total:.1f}GB 사용 ({free:.1f}GB 여유)")
        return free
    except Exception:
        import shutil
        total, used, free = shutil.disk_usage(path)
        total, used, free = total/(1024**3), used/(1024**3), free/(1024**3)
        print(f"  디스크: {used:.1f}GB / {total:.1f}GB 사용 ({free:.1f}GB 여유)")
        return free


def prepare_data(args):
    """Phase 1: 전체 PA CSV 생성 + 이미지 다운로드"""
    print("=" * 60)
    print("Phase 1: 데이터 준비")
    print("=" * 60)

    check_disk_space()

    images_dir = os.path.join(DATA_DIR, 'images_cache')
    os.makedirs(images_dir, exist_ok=True)

    df = build_full_pa_csv(args.image_bucket, args.work_bucket)

    print(f"\n이미지 다운로드 (s3://{args.image_bucket}/)")
    download_needed_images(df, args.image_bucket, images_dir)

    free_gb = check_disk_space()
    if free_gb < 5:
        print(f"  [경고] 디스크 여유 {free_gb:.1f}GB — pip 캐시 정리")
        subprocess.run([sys.executable, '-m', 'pip', 'cache', 'purge'], capture_output=True)
        for f in os.listdir('/tmp'):
            try:
                p = os.path.join('/tmp', f)
                if os.path.isfile(p):
                    os.remove(p)
            except Exception:
                pass
        check_disk_space()

    return df, images_dir


# ============================================================
# Dataset
# ============================================================
class MIMICCXRDataset(Dataset):
    def __init__(self, dataframe, label_cols, image_base_dir, transform=None):
        self.df = dataframe.reset_index(drop=True)
        self.label_cols = label_cols
        self.image_base_dir = image_base_dir
        self.transform = transform

    def __len__(self):
        return len(self.df)

    def __getitem__(self, idx):
        row = self.df.iloc[idx]
        img_path = os.path.join(self.image_base_dir, row['image_path'])
        labels = torch.tensor(
            [row[col] for col in self.label_cols], dtype=torch.float32)

        try:
            image = Image.open(img_path).convert('RGB')
            if self.transform:
                image = self.transform(image)
            return image, labels
        except Exception as e:
            print(f"  [WARN] 이미지 로드 실패: {img_path} — {e}")
            return torch.zeros(3, 224, 224), labels


# ============================================================
# 전처리 & 가중치
# ============================================================
def get_transforms():
    train_transform = transforms.Compose([
        transforms.Resize((256, 256)),
        transforms.RandomCrop(224),
        transforms.RandomHorizontalFlip(p=0.5),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406],
                             std=[0.229, 0.224, 0.225])
    ])
    val_transform = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406],
                             std=[0.229, 0.224, 0.225])
    ])
    return train_transform, val_transform


def compute_pos_weights(df, label_cols):
    pos_weights = []
    for col in label_cols:
        pos = df[col].sum()
        neg = len(df) - pos
        pos_weights.append(neg / max(pos, 1))
    return torch.tensor(pos_weights, dtype=torch.float32)


# ============================================================
# 학습/검증 함수
# ============================================================
def train_one_epoch(model, loader, criterion, optimizer, device, epoch, total_epochs):
    model.train()
    running_loss = 0.0
    total_batches = len(loader)
    epoch_start = time.time()

    for batch_idx, (images, labels) in enumerate(loader):
        images, labels = images.to(device), labels.to(device)
        optimizer.zero_grad()
        outputs = model(images)
        loss = criterion(outputs, labels)
        loss.backward()

        # gradient clipping — pos_weight 불균형으로 인한 gradient 폭발 방지
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)

        optimizer.step()
        running_loss += loss.item()

        if (batch_idx + 1) % 50 == 0 or (batch_idx + 1) == total_batches:
            elapsed = time.time() - epoch_start
            pct = (batch_idx + 1) / total_batches * 100
            eta = elapsed / (batch_idx + 1) * (total_batches - batch_idx - 1)
            avg_loss = running_loss / (batch_idx + 1)
            print(f"  [Epoch {epoch+1}/{total_epochs}] {pct:5.1f}% | "
                  f"batch {batch_idx+1}/{total_batches} | "
                  f"loss: {avg_loss:.4f} | "
                  f"elapsed: {elapsed:.0f}s | ETA: ~{eta:.0f}s")

    return running_loss / total_batches


def validate(model, loader, criterion, device):
    model.eval()
    running_loss = 0.0
    all_preds, all_labels = [], []

    with torch.no_grad():
        for images, labels in loader:
            images, labels = images.to(device), labels.to(device)
            outputs = model(images)
            loss = criterion(outputs, labels)
            running_loss += loss.item()
            all_preds.append(torch.sigmoid(outputs).cpu().numpy())
            all_labels.append(labels.cpu().numpy())

    all_preds = np.concatenate(all_preds)
    all_labels = np.concatenate(all_labels)

    aurocs = []
    for i in range(NUM_CLASSES):
        try:
            if len(np.unique(all_labels[:, i])) > 1:
                aurocs.append(roc_auc_score(all_labels[:, i], all_preds[:, i]))
            else:
                aurocs.append(None)
        except Exception:
            aurocs.append(None)

    valid = [a for a in aurocs if a is not None]
    mean_auroc = np.mean(valid) if valid else 0.0
    return running_loss / len(loader), mean_auroc, aurocs


# ============================================================
# 체크포인트
# ============================================================
def save_checkpoint(model, optimizer, scheduler, epoch, stage,
                    best_val_loss, best_val_auroc, checkpoint_dir):
    """DataParallel 안전한 체크포인트 저장 — 항상 unwrap해서 저장"""
    os.makedirs(checkpoint_dir, exist_ok=True)
    path = os.path.join(checkpoint_dir, 'checkpoint.pth')
    tmp_path = path + '.tmp'

    raw_model = unwrap_model(model)
    state = {
        'epoch': epoch,
        'stage': stage,
        'model_state_dict': raw_model.state_dict(),
        'optimizer_state_dict': optimizer.state_dict(),
        'scheduler_state_dict': scheduler.state_dict(),
        'best_val_loss': best_val_loss,
        'best_val_auroc': best_val_auroc,
    }
    torch.save(state, tmp_path)
    os.replace(tmp_path, path)


def load_checkpoint(checkpoint_dir, device):
    filepath = os.path.join(checkpoint_dir, 'checkpoint.pth')
    if os.path.exists(filepath):
        print("  체크포인트 발견! 이어서 학습합니다.")
        return torch.load(filepath, map_location=device, weights_only=False)
    return None


# ============================================================
# 메인
# ============================================================
def main(args):
    total_start = time.time()

    # ============ Phase 1: 데이터 준비 ============
    df, images_dir = prepare_data(args)

    # ============ Phase 2: 학습 ============
    print("\n" + "=" * 60)
    print("Phase 2: DenseNet-121 Multi-GPU 학습")
    print("=" * 60)

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    num_gpus = torch.cuda.device_count()
    print(f"\nDevice: {device}")
    print(f"GPU 수: {num_gpus}")
    for i in range(num_gpus):
        name = torch.cuda.get_device_name(i)
        mem = torch.cuda.get_device_properties(i).total_memory / 1024**3
        print(f"  GPU {i}: {name} ({mem:.1f}GB)")

    train_df = df[df['split'] == 'train']
    val_df = df[df['split'] == 'validate']
    test_df = df[df['split'] == 'test']
    print(f"\nSplit — train: {len(train_df):,} / val: {len(val_df):,} / test: {len(test_df):,}")

    # Dataset & DataLoader
    train_transform, val_transform = get_transforms()
    train_dataset = MIMICCXRDataset(train_df, LABEL_COLS, images_dir, train_transform)
    val_dataset = MIMICCXRDataset(val_df, LABEL_COLS, images_dir, val_transform)
    test_dataset = MIMICCXRDataset(test_df, LABEL_COLS, images_dir, val_transform)

    effective_batch = args.batch_size
    print(f"\n배치 설정: total {effective_batch} (GPU당 {effective_batch // max(num_gpus,1)})")

    train_loader = DataLoader(train_dataset, batch_size=effective_batch, shuffle=True,
                              num_workers=args.num_workers, pin_memory=True,
                              drop_last=True, persistent_workers=True)
    val_loader = DataLoader(val_dataset, batch_size=effective_batch, shuffle=False,
                            num_workers=args.num_workers, pin_memory=True,
                            persistent_workers=True)
    test_loader = DataLoader(test_dataset, batch_size=effective_batch, shuffle=False,
                             num_workers=args.num_workers, pin_memory=True,
                             persistent_workers=True)

    print(f"DataLoader — train: {len(train_loader)} / val: {len(val_loader)} / test: {len(test_loader)} batches")

    # 모델
    model = models.densenet121(weights='IMAGENET1K_V1')
    num_features = model.classifier.in_features
    model.classifier = nn.Linear(num_features, NUM_CLASSES)

    # 체크포인트 복원 (DataParallel 전에 로드)
    start_epoch = 0
    best_val_loss = float('inf')
    best_val_auroc = 0.0
    restored_stage = 0

    checkpoint = load_checkpoint(CHECKPOINT_DIR, device)
    if checkpoint:
        model.load_state_dict(checkpoint['model_state_dict'])
        start_epoch = checkpoint['epoch'] + 1
        best_val_loss = checkpoint['best_val_loss']
        best_val_auroc = checkpoint.get('best_val_auroc', 0.0)
        restored_stage = checkpoint['stage']
        print(f"  → epoch {start_epoch}부터 재개 (stage {restored_stage})")

    # GPU에 올리고 DataParallel 적용
    model = model.to(device)
    if num_gpus > 1:
        model = nn.DataParallel(model)
        print(f"\n★ DataParallel 활성화: {num_gpus}개 GPU 병렬 학습")

    # pos_weight & Loss
    pos_weights = compute_pos_weights(train_df, LABEL_COLS).to(device)
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weights)

    total_epochs = args.stage1_epochs + args.stage2_epochs
    print(f"\n학습: Stage1({args.stage1_epochs}ep, classifier) + "
          f"Stage2({args.stage2_epochs}ep, full) = {total_epochs}ep")

    # Stage 설정 — unwrap_model로 원본 모델 접근
    def setup_stage1():
        raw = unwrap_model(model)
        for param in raw.features.parameters():
            param.requires_grad = False
        for param in raw.classifier.parameters():
            param.requires_grad = True
        opt = optim.Adam(filter(lambda p: p.requires_grad, model.parameters()), lr=args.lr)
        sched = optim.lr_scheduler.ReduceLROnPlateau(opt, mode='min', factor=0.1, patience=3)
        trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
        total = sum(p.numel() for p in model.parameters())
        print(f"  Stage 1: {trainable:,}/{total:,} params ({trainable/total*100:.1f}%)")
        return opt, sched

    def setup_stage2():
        raw = unwrap_model(model)
        for param in raw.parameters():
            param.requires_grad = True
        opt = optim.Adam(model.parameters(), lr=args.lr * 0.1)
        sched = optim.lr_scheduler.ReduceLROnPlateau(opt, mode='min', factor=0.1, patience=3)
        print(f"  Stage 2: 전체 파라미터 학습")
        return opt, sched

    if start_epoch < args.stage1_epochs:
        optimizer, scheduler = setup_stage1()
        current_stage = 1
        if checkpoint and restored_stage == 1:
            optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
            scheduler.load_state_dict(checkpoint['scheduler_state_dict'])
    else:
        optimizer, scheduler = setup_stage2()
        current_stage = 2
        if checkpoint and restored_stage == 2:
            optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
            scheduler.load_state_dict(checkpoint['scheduler_state_dict'])

    # 학습 루프
    train_start = time.time()

    for epoch in range(start_epoch, total_epochs):
        # Stage 전환
        if epoch == args.stage1_epochs and current_stage == 1:
            print(f"\n{'='*50}")
            print(f"Stage 2 전환: Full Fine-tuning")
            optimizer, scheduler = setup_stage2()
            current_stage = 2

        epoch_start = time.time()
        print(f"\n{'─'*50}")
        print(f"[Epoch {epoch+1}/{total_epochs}] Stage {current_stage} | GPU: {num_gpus}x")

        train_loss = train_one_epoch(
            model, train_loader, criterion, optimizer, device, epoch, total_epochs)

        val_loss, val_auroc, _ = validate(model, val_loader, criterion, device)
        scheduler.step(val_loss)

        epoch_time = time.time() - epoch_start
        remaining = epoch_time * (total_epochs - epoch - 1)

        print(f"\n  Train Loss: {train_loss:.4f} | Val Loss: {val_loss:.4f}")
        print(f"  Val AUROC: {val_auroc:.4f} | LR: {optimizer.param_groups[0]['lr']:.2e}")
        print(f"  소요: {epoch_time:.0f}s | 남은 예상: ~{remaining/60:.1f}분")

        if val_auroc > best_val_auroc:
            best_val_auroc = val_auroc
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            os.makedirs(SM_MODEL_DIR, exist_ok=True)
            best_path = os.path.join(SM_MODEL_DIR, 'best_model.pth')
            tmp_path = best_path + '.tmp'
            torch.save(unwrap_model(model).state_dict(), tmp_path)
            os.replace(tmp_path, best_path)
            print(f"  ★ Best 모델 저장! (val_loss: {val_loss:.4f}, auroc: {val_auroc:.4f})")

        save_checkpoint(model, optimizer, scheduler, epoch, current_stage,
                        best_val_loss, best_val_auroc, CHECKPOINT_DIR)

    # 테스트
    total_train_time = time.time() - train_start
    print(f"\n{'='*60}")
    print(f"학습 완료! ({total_train_time/60:.1f}분)")

    best_path = os.path.join(SM_MODEL_DIR, 'best_model.pth')
    if os.path.exists(best_path):
        unwrap_model(model).load_state_dict(
            torch.load(best_path, map_location=device, weights_only=False))

    test_loss, test_auroc, test_aurocs = validate(model, test_loader, criterion, device)

    print(f"\n테스트 결과:")
    print(f"  Mean AUROC: {test_auroc:.4f}")
    print(f"\n{'질환':<35} {'AUROC':>8}")
    print("─" * 45)
    for i, col in enumerate(LABEL_COLS):
        v = f"{test_aurocs[i]:.4f}" if test_aurocs[i] is not None else "N/A"
        print(f"  {col:<35} {v:>8}")

    # 결과 저장
    results = {
        'test_loss': float(test_loss),
        'mean_auroc': float(test_auroc),
        'per_class_auroc': {
            col: float(test_aurocs[i]) if test_aurocs[i] is not None else None
            for i, col in enumerate(LABEL_COLS)
        },
        'best_val_loss': float(best_val_loss),
        'best_val_auroc': float(best_val_auroc),
        'total_epochs': total_epochs,
        'stage1_epochs': args.stage1_epochs,
        'stage2_epochs': args.stage2_epochs,
        'batch_size': args.batch_size,
        'learning_rate': args.lr,
        'num_gpus': num_gpus,
        'training_time_minutes': total_train_time / 60,
        'total_time_minutes': (time.time() - total_start) / 60,
        'data_count': {'train': len(train_df), 'val': len(val_df), 'test': len(test_df)},
    }

    os.makedirs(SM_MODEL_DIR, exist_ok=True)
    with open(os.path.join(SM_MODEL_DIR, 'results.json'), 'w') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n전체 완료! (총 {(time.time()-total_start)/60:.1f}분)")


# ============================================================
# SageMaker 진입점
# ============================================================
if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    # 하이퍼파라미터 — g5.12xlarge (4 GPU) 최적화 기본값
    parser.add_argument('--batch-size', type=int, default=128)
    parser.add_argument('--stage1-epochs', type=int, default=5)
    parser.add_argument('--stage2-epochs', type=int, default=25)
    parser.add_argument('--lr', type=float, default=1e-4)
    parser.add_argument('--num-workers', type=int, default=16)

    # S3 설정
    parser.add_argument('--image-bucket', type=str, default='say1-pre-project-5',
                        help='CXR 이미지가 있는 S3 버킷')
    parser.add_argument('--work-bucket', type=str,
                        default='pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an',
                        help='작업 S3 버킷 (CSV, 캐시용)')

    # 호환성
    parser.add_argument('--data-dir', type=str,
                        default=os.environ.get('SM_CHANNEL_TRAIN', ''))
    parser.add_argument('--csv-dir', type=str,
                        default=os.environ.get('SM_CHANNEL_CSV', ''))
    parser.add_argument('--model-dir', type=str,
                        default=os.environ.get('SM_MODEL_DIR', '/opt/ml/model'))

    args = parser.parse_args()
    main(args)
