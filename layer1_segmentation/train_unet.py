"""
U-Net (EfficientNet-B4) 폐/심장 세그멘테이션 — 올인원 SageMaker 스크립트

한 번 제출하고 자면 됨. Training Job이 알아서:
1. CheXmask CSV 다운로드 (S3 캐시 또는 PhysioNet)
2. Split CSV 로드 (say1-pre-project-5 또는 해시 기반)
3. 이미지 S3 선택 다운로드 (필요한 것만)
4. 마스크 실시간 RLE 디코딩 (NPZ 불필요)
5. U-Net 학습

=== 데이터 채널: 없음 (전부 S3 직접 접근) ===
=== 모델 ===
- segmentation_models_pytorch U-Net + EfficientNet-B4 encoder
- 4-class: 배경(0), 좌폐(1), 우폐(2), 심장(3)
- Loss: Dice + CrossEntropy combo
"""

import argparse
import os
import sys
import json
import time
import gc
import gzip
import io
import hashlib
import subprocess

# pip install (SageMaker 컨테이너에 없을 수 있음)
subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-q',
                       'segmentation-models-pytorch', 'albumentations'])

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from PIL import Image
import segmentation_models_pytorch as smp
import albumentations as A
from albumentations.pytorch import ToTensorV2
import boto3
from concurrent.futures import ThreadPoolExecutor

# ============================================================
# 상수
# ============================================================
SM_MODEL_DIR = os.environ.get('SM_MODEL_DIR', '/opt/ml/model')
SM_OUTPUT_DATA_DIR = os.environ.get('SM_OUTPUT_DATA_DIR', '/opt/ml/output/data')
CHECKPOINT_DIR = '/opt/ml/checkpoints'
DATA_DIR = '/opt/ml/input/data'

NUM_CLASSES = 4  # 배경, 좌폐, 우폐, 심장

CHEXMASK_URL = (
    "https://physionet.org/files/chexmask-cxr-segmentation-data/"
    "1.0.0/Preprocessed/MIMIC-CXR-JPG.csv"
)


# ============================================================
# Phase 1: 데이터 준비
# ============================================================
def download_chexmask(work_bucket, local_path):
    """
    CheXmask CSV 확보: S3 캐시 우선 → PhysioNet 폴백.
    첫 실행 시 PhysioNet에서 다운로드 후 S3에 캐시.
    두 번째부터는 S3에서 바로 다운로드 (~1분).
    """
    s3 = boto3.client('s3')
    s3_key = 'data/chexmask/MIMIC-CXR-JPG.csv'

    if os.path.exists(local_path):
        print(f"  이미 존재: {os.path.getsize(local_path)/(1024**3):.1f}GB")
        return

    # S3 캐시 확인
    try:
        s3.head_object(Bucket=work_bucket, Key=s3_key)
        print(f"  S3 캐시 발견! s3://{work_bucket}/{s3_key}")
        start = time.time()
        s3.download_file(work_bucket, s3_key, local_path)
        print(f"  S3 캐시 다운로드 완료 ({time.time()-start:.0f}초)")
        return
    except Exception:
        pass

    # PhysioNet에서 다운로드
    print("  PhysioNet에서 다운로드 시작 (~4.4GB)")
    start = time.time()

    # wget 사용 (SageMaker 컨테이너에 기본 설치됨)
    try:
        subprocess.run([
            'wget', '-c', '-O', local_path,
            '--progress=dot:giga', CHEXMASK_URL
        ], check=True, timeout=7200)
    except (subprocess.CalledProcessError, FileNotFoundError):
        # wget 실패 시 Python urllib 사용
        print("  wget 실패, Python urllib 사용")
        import urllib.request
        urllib.request.urlretrieve(CHEXMASK_URL, local_path)

    elapsed = time.time() - start
    size_gb = os.path.getsize(local_path) / (1024**3)
    print(f"  다운로드 완료: {size_gb:.1f}GB ({elapsed/60:.1f}분)")

    # S3에 캐시 (다음 실행 시 빠르게)
    print(f"  S3 캐시 업로드: s3://{work_bucket}/{s3_key}")
    try:
        s3.upload_file(local_path, work_bucket, s3_key)
        print("  S3 캐시 업로드 완료")
    except Exception as e:
        print(f"  S3 캐시 업로드 실패 (무시): {e}")


def load_split_csv(image_bucket, work_bucket):
    """
    MIMIC-CXR 공식 split CSV 로드.
    작업 버킷 mimic-cxr-csv/ → 이미지 버킷 루트 순으로 시도.
    실패 시 None 반환 (해시 기반 split 사용).
    """
    s3 = boto3.client('s3')

    candidates = [
        (work_bucket, 'mimic-cxr-csv/mimic-cxr-2.0.0-split.csv'),
        (work_bucket, 'mimic-cxr-csv/mimic-cxr-2.0.0-split.csv.gz'),
        (image_bucket, 'mimic-cxr-2.0.0-split.csv.gz'),
        (image_bucket, 'mimic-cxr-2.0.0-split.csv'),
    ]

    for bucket, key in candidates:
        try:
            print(f"  시도: s3://{bucket}/{key}")
            resp = s3.get_object(Bucket=bucket, Key=key)
            data = resp['Body'].read()
            if key.endswith('.gz'):
                data = gzip.decompress(data)
            split_df = pd.read_csv(io.BytesIO(data))
            print(f"  Split CSV 로드 성공: {len(split_df):,}행")
            return split_df
        except Exception as e:
            print(f"    실패: {e}")

    print("  Split CSV 미발견 — 해시 기반 자동 분할 사용")
    return None


def assign_split_hash(subject_id):
    """MD5 해시 기반 환자 분할 (70/10/20, 결정적)"""
    h = int(hashlib.md5(str(subject_id).encode()).hexdigest(), 16) % 100
    if h < 70:
        return 'train'
    elif h < 80:
        return 'validate'
    else:
        return 'test'


def parse_image_id(image_id):
    """CheXmask ImageID에서 subject_id, study_id, dicom_id 추출"""
    parts = str(image_id).split('/')
    # files/p10/p10000032/s50414267/xxx.jpg
    subject_id = int(parts[2][1:])
    study_id = int(parts[3][1:])
    dicom_id = os.path.splitext(parts[4])[0]
    return subject_id, study_id, dicom_id


def download_needed_images(df, bucket, local_dir, max_workers=32):
    """Manifest에 있는 이미지만 S3에서 선택 다운로드"""
    s3 = boto3.client('s3')
    S3_PREFIX = 'data/mimic-cxr-jpg/'

    to_download = []
    for _, row in df.iterrows():
        img_rel = row['image_path']  # files/p10/p10000032/s.../xxx.jpg
        s3_key = S3_PREFIX + img_rel  # data/mimic-cxr-jpg/files/p10/...
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
    done = [0, 0]  # [success, error]

    def _dl(item):
        key, path = item
        try:
            s3.download_file(bucket, key, path)
            return True
        except Exception:
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


def prepare_data(args):
    """
    Phase 1: 전체 데이터 준비.
    Returns: (DataFrame, image_base_dir)
    """
    print("=" * 60)
    print("Phase 1: 데이터 준비")
    print("=" * 60)

    chexmask_path = os.path.join(DATA_DIR, 'chexmask.csv')
    images_dir = os.path.join(DATA_DIR, 'images_cache')
    os.makedirs(images_dir, exist_ok=True)

    # 1. CheXmask CSV 확보
    print("\n[1/4] CheXmask CSV")
    download_chexmask(args.work_bucket, chexmask_path)

    # 2. CheXmask 로드 + 필터
    print("\n[2/4] CheXmask 로드 + 품질 필터")
    start = time.time()

    # 컬럼명 탐지
    sample = pd.read_csv(chexmask_path, nrows=2)
    id_col = sample.columns[0]
    dice_cols = [c for c in sample.columns if 'dice' in c.lower() and 'mean' in c.lower()]
    dice_col = dice_cols[0] if dice_cols else None

    # Landmarks 제외하고 로드 (메모리 절약)
    use_cols = [id_col, 'Left Lung', 'Right Lung', 'Heart', 'Height', 'Width']
    if dice_col:
        use_cols.insert(1, dice_col)

    print(f"  로드 중 (Landmarks 제외)...")
    df = pd.read_csv(chexmask_path, usecols=use_cols)
    print(f"  전체: {len(df):,}행 ({(time.time()-start)/60:.1f}분)")

    # 품질 필터
    if dice_col:
        before = len(df)
        df = df[df[dice_col] >= 0.7].copy()
        print(f"  품질 필터 ({dice_col} >= 0.7): {before:,} → {len(df):,}")

    # image_path = ImageID (S3 key)
    df['image_path'] = df[id_col].astype(str)

    # subject_id, dicom_id 추출
    parsed = df['image_path'].apply(lambda x: parse_image_id(x))
    df['subject_id'] = parsed.apply(lambda x: x[0])
    df['study_id'] = parsed.apply(lambda x: x[1])
    df['dicom_id'] = parsed.apply(lambda x: x[2])

    # 3. Split 할당
    print("\n[3/4] Split 할당")
    split_df = load_split_csv(args.image_bucket, args.work_bucket)
    if split_df is not None:
        df = df.merge(split_df[['dicom_id', 'split']], on='dicom_id', how='inner')
        print(f"  공식 Split 병합: {len(df):,}행")
    else:
        df['split'] = df['subject_id'].apply(assign_split_hash)
        print(f"  해시 기반 Split 할당: {len(df):,}행")

    print(f"  분포: {df['split'].value_counts().to_dict()}")

    # 4. 이미지 다운로드
    print(f"\n[4/4] S3 이미지 다운로드 (s3://{args.image_bucket}/)")
    download_needed_images(df, args.image_bucket, images_dir)

    # ID 컬럼 정리
    df = df.reset_index(drop=True)

    return df, images_dir


# ============================================================
# RLE 디코딩 (실시간)
# ============================================================
def rle_to_mask(rle_string, height, width):
    if pd.isna(rle_string) or str(rle_string).strip() in ('', 'nan'):
        return np.zeros((height, width), dtype=np.uint8)
    runs = np.array([int(x) for x in str(rle_string).split()])
    starts, lengths = runs[0::2], runs[1::2]
    mask = np.zeros(height * width, dtype=np.uint8)
    for s, l in zip(starts, lengths):
        mask[s - 1:s - 1 + l] = 1
    return mask.reshape((height, width))


def decode_combined_mask(row, target_size=512):
    """3개 장기 RLE → combined mask (0:BG, 1:LL, 2:RL, 3:Heart)"""
    h, w = int(row['Height']), int(row['Width'])
    ll = rle_to_mask(row['Left Lung'], h, w)
    rl = rle_to_mask(row['Right Lung'], h, w)
    ht = rle_to_mask(row['Heart'], h, w)

    if h != target_size or w != target_size:
        ll = np.array(Image.fromarray(ll).resize((target_size, target_size), Image.NEAREST))
        rl = np.array(Image.fromarray(rl).resize((target_size, target_size), Image.NEAREST))
        ht = np.array(Image.fromarray(ht).resize((target_size, target_size), Image.NEAREST))

    combined = np.zeros((target_size, target_size), dtype=np.uint8)
    combined[ll > 0] = 1
    combined[rl > 0] = 2
    combined[ht > 0] = 3  # 심장이 폐와 겹치면 심장 우선
    return combined


# ============================================================
# Dataset (실시간 RLE 디코딩 — NPZ 불필요)
# ============================================================
class UNetSegDataset(Dataset):
    """
    이미지: 로컬 캐시 (S3에서 다운로드 완료)
    마스크: DataFrame의 RLE 컬럼에서 실시간 디코딩 (~1ms/장)
    """
    def __init__(self, df, image_base_dir, split, target_size=512, augment=False):
        self.df = df[df['split'] == split].reset_index(drop=True)
        self.image_base_dir = image_base_dir
        self.target_size = target_size

        if augment:
            self.transform = A.Compose([
                A.Resize(target_size, target_size),
                A.HorizontalFlip(p=0.5),
                A.ShiftScaleRotate(shift_limit=0.05, scale_limit=0.1,
                                   rotate_limit=10, p=0.5),
                A.RandomBrightnessContrast(brightness_limit=0.1,
                                           contrast_limit=0.1, p=0.3),
                A.Normalize(mean=[0.485, 0.456, 0.406],
                           std=[0.229, 0.224, 0.225]),
                ToTensorV2(),
            ])
        else:
            self.transform = A.Compose([
                A.Resize(target_size, target_size),
                A.Normalize(mean=[0.485, 0.456, 0.406],
                           std=[0.229, 0.224, 0.225]),
                ToTensorV2(),
            ])

    def __len__(self):
        return len(self.df)

    def __getitem__(self, idx):
        row = self.df.iloc[idx]

        # 이미지 로드
        img_path = os.path.join(self.image_base_dir, row['image_path'])
        try:
            image = np.array(Image.open(img_path).convert('RGB'))
        except Exception as e:
            print(f"  [WARN] 이미지 로드 실패: {img_path} — {e}")
            image = np.zeros((self.target_size, self.target_size, 3), dtype=np.uint8)

        # 마스크 실시간 디코딩
        try:
            mask = decode_combined_mask(row, self.target_size)
        except Exception as e:
            print(f"  [WARN] 마스크 디코딩 실패: {row['dicom_id']} — {e}")
            mask = np.zeros((self.target_size, self.target_size), dtype=np.uint8)

        transformed = self.transform(image=image, mask=mask)
        return transformed['image'], transformed['mask'].long()


# ============================================================
# Loss: Dice + CrossEntropy
# ============================================================
class DiceCELoss(nn.Module):
    def __init__(self, num_classes=4, dice_weight=0.5, ce_weight=0.5):
        super().__init__()
        self.ce = nn.CrossEntropyLoss()
        self.num_classes = num_classes
        self.dice_weight = dice_weight
        self.ce_weight = ce_weight

    def dice_loss(self, pred, target):
        target_onehot = torch.zeros_like(pred)
        target_onehot.scatter_(1, target.unsqueeze(1), 1)
        smooth = 1e-5
        dims = (0, 2, 3)
        intersection = (pred * target_onehot).sum(dim=dims)
        union = pred.sum(dim=dims) + target_onehot.sum(dim=dims)
        dice = (2 * intersection + smooth) / (union + smooth)
        return 1 - dice[1:].mean()  # 배경 제외

    def forward(self, logits, target):
        ce_loss = self.ce(logits, target)
        pred_soft = torch.softmax(logits, dim=1)
        d_loss = self.dice_loss(pred_soft, target)
        return self.ce_weight * ce_loss + self.dice_weight * d_loss


# ============================================================
# Dice Score 계산 (평가용)
# ============================================================
def compute_dice_scores(pred, target, num_classes=4):
    pred_classes = pred.argmax(dim=1)
    scores = {}
    for c in range(1, num_classes):
        pred_c = (pred_classes == c).float()
        target_c = (target == c).float()
        intersection = (pred_c * target_c).sum()
        union = pred_c.sum() + target_c.sum()
        scores[c] = (2 * intersection / union).item() if union > 0 else 1.0
    return scores


# ============================================================
# 학습/검증 함수
# ============================================================
def train_one_epoch(model, loader, criterion, optimizer, device, epoch, total_epochs):
    model.train()
    running_loss = 0.0
    total_batches = len(loader)
    epoch_start = time.time()

    for batch_idx, (images, masks) in enumerate(loader):
        images = images.to(device)
        masks = masks.to(device)

        optimizer.zero_grad()
        outputs = model(images)
        loss = criterion(outputs, masks)
        loss.backward()
        optimizer.step()

        running_loss += loss.item()

        if (batch_idx + 1) % 20 == 0 or (batch_idx + 1) == total_batches:
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
    all_dice = {1: [], 2: [], 3: []}

    with torch.no_grad():
        for images, masks in loader:
            images = images.to(device)
            masks = masks.to(device)
            outputs = model(images)
            loss = criterion(outputs, masks)
            running_loss += loss.item()
            dice = compute_dice_scores(outputs, masks)
            for c in [1, 2, 3]:
                all_dice[c].append(dice[c])

    avg_loss = running_loss / len(loader)
    avg_dice = {c: np.mean(all_dice[c]) for c in [1, 2, 3]}
    mean_dice = np.mean(list(avg_dice.values()))
    return avg_loss, mean_dice, avg_dice


# ============================================================
# 체크포인트 (스팟 대응)
# ============================================================
def save_checkpoint(state, checkpoint_dir):
    os.makedirs(checkpoint_dir, exist_ok=True)
    torch.save(state, os.path.join(checkpoint_dir, 'checkpoint.pth'))


def load_checkpoint(checkpoint_dir, device):
    filepath = os.path.join(checkpoint_dir, 'checkpoint.pth')
    if os.path.exists(filepath):
        print("  체크포인트 발견! 이어서 학습합니다.")
        return torch.load(filepath, map_location=device)
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
    print("Phase 2: U-Net 학습")
    print("=" * 60)

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"\nDevice: {device}")
    if torch.cuda.is_available():
        print(f"GPU: {torch.cuda.get_device_name(0)}")
        gpu_mem = torch.cuda.get_device_properties(0).total_memory / 1024**3
        print(f"GPU Memory: {gpu_mem:.1f}GB")

    # Dataset & DataLoader
    train_ds = UNetSegDataset(df, images_dir, 'train',
                              target_size=args.image_size, augment=True)
    val_ds = UNetSegDataset(df, images_dir, 'validate',
                            target_size=args.image_size, augment=False)
    test_ds = UNetSegDataset(df, images_dir, 'test',
                             target_size=args.image_size, augment=False)

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True,
                              num_workers=args.num_workers, pin_memory=True, drop_last=True)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False,
                            num_workers=args.num_workers, pin_memory=True)
    test_loader = DataLoader(test_ds, batch_size=args.batch_size, shuffle=False,
                             num_workers=args.num_workers, pin_memory=True)

    print(f"\n데이터 — train: {len(train_ds):,}장 ({len(train_loader)} batches)")
    print(f"         val: {len(val_ds):,}장 / test: {len(test_ds):,}장")
    print(f"Batch size: {args.batch_size}, Image size: {args.image_size}")

    # 모델
    model = smp.Unet(
        encoder_name='efficientnet-b4',
        encoder_weights='imagenet',
        in_channels=3,
        classes=NUM_CLASSES,
    ).to(device)

    total_params = sum(p.numel() for p in model.parameters())
    print(f"\nModel: U-Net + EfficientNet-B4 ({total_params:,} params)")

    # Loss & Optimizer
    criterion = DiceCELoss(num_classes=NUM_CLASSES)
    optimizer = optim.Adam(model.parameters(), lr=args.lr)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode='min', factor=0.5, patience=3, verbose=True)

    # 체크포인트 복원
    start_epoch = 0
    best_val_dice = 0.0
    ckpt = load_checkpoint(CHECKPOINT_DIR, device)
    if ckpt:
        model.load_state_dict(ckpt['model_state_dict'])
        optimizer.load_state_dict(ckpt['optimizer_state_dict'])
        scheduler.load_state_dict(ckpt['scheduler_state_dict'])
        start_epoch = ckpt['epoch'] + 1
        best_val_dice = ckpt['best_val_dice']
        print(f"  → epoch {start_epoch}부터 재개, best_dice: {best_val_dice:.4f}")

    # 학습 루프
    train_start = time.time()
    total_epochs = args.epochs

    for epoch in range(start_epoch, total_epochs):
        epoch_start = time.time()

        print(f"\n{'─'*50}")
        print(f"[Epoch {epoch+1}/{total_epochs}]")
        train_loss = train_one_epoch(
            model, train_loader, criterion, optimizer, device, epoch, total_epochs)

        val_loss, val_dice, val_dice_per_class = validate(
            model, val_loader, criterion, device)
        scheduler.step(val_loss)

        epoch_time = time.time() - epoch_start
        remaining = epoch_time * (total_epochs - epoch - 1)

        print(f"\n  Train Loss: {train_loss:.4f} | Val Loss: {val_loss:.4f}")
        print(f"  Val Dice: {val_dice:.4f} "
              f"(LL:{val_dice_per_class[1]:.4f} "
              f"RL:{val_dice_per_class[2]:.4f} "
              f"Heart:{val_dice_per_class[3]:.4f})")
        print(f"  LR: {optimizer.param_groups[0]['lr']:.2e} | "
              f"소요: {epoch_time:.0f}s | 남은 예상: ~{remaining/60:.1f}분")

        if val_dice > best_val_dice:
            best_val_dice = val_dice
            os.makedirs(SM_MODEL_DIR, exist_ok=True)
            torch.save(model.state_dict(),
                       os.path.join(SM_MODEL_DIR, 'best_model.pth'))
            print(f"  ★ Best 모델 저장! (dice: {val_dice:.4f})")

        save_checkpoint({
            'epoch': epoch,
            'model_state_dict': model.state_dict(),
            'optimizer_state_dict': optimizer.state_dict(),
            'scheduler_state_dict': scheduler.state_dict(),
            'best_val_dice': best_val_dice,
        }, CHECKPOINT_DIR)

    # 테스트
    total_train_time = time.time() - train_start
    print(f"\n{'='*60}")
    print(f"학습 완료! ({total_train_time/60:.1f}분)")

    best_path = os.path.join(SM_MODEL_DIR, 'best_model.pth')
    if os.path.exists(best_path):
        model.load_state_dict(torch.load(best_path, map_location=device))

    test_loss, test_dice, test_dice_per_class = validate(
        model, test_loader, criterion, device)

    print(f"\n테스트 결과:")
    print(f"  Mean Dice: {test_dice:.4f}")
    print(f"  Left Lung:  {test_dice_per_class[1]:.4f}")
    print(f"  Right Lung: {test_dice_per_class[2]:.4f}")
    print(f"  Heart:      {test_dice_per_class[3]:.4f}")

    # 결과 저장
    results = {
        'test_loss': float(test_loss),
        'mean_dice': float(test_dice),
        'per_class_dice': {
            'left_lung': float(test_dice_per_class[1]),
            'right_lung': float(test_dice_per_class[2]),
            'heart': float(test_dice_per_class[3]),
        },
        'best_val_dice': float(best_val_dice),
        'total_epochs': total_epochs,
        'batch_size': args.batch_size,
        'image_size': args.image_size,
        'learning_rate': args.lr,
        'training_time_minutes': total_train_time / 60,
        'total_time_minutes': (time.time() - total_start) / 60,
        'data_count': {'train': len(train_ds), 'val': len(val_ds), 'test': len(test_ds)},
    }

    os.makedirs(SM_MODEL_DIR, exist_ok=True)
    with open(os.path.join(SM_MODEL_DIR, 'results.json'), 'w') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    deploy_info = {
        'encoder_name': 'efficientnet-b4',
        'num_classes': NUM_CLASSES,
        'image_size': args.image_size,
        'class_map': {0: 'background', 1: 'left_lung', 2: 'right_lung', 3: 'heart'},
    }
    with open(os.path.join(SM_MODEL_DIR, 'model_info.json'), 'w') as f:
        json.dump(deploy_info, f, indent=2)

    print(f"\n전체 완료! (총 {(time.time()-total_start)/60:.1f}분)")


# ============================================================
# SageMaker 진입점
# ============================================================
if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    # 하이퍼파라미터
    parser.add_argument('--epochs', type=int, default=50)
    parser.add_argument('--batch-size', type=int, default=8)
    parser.add_argument('--lr', type=float, default=1e-4)
    parser.add_argument('--image-size', type=int, default=512)
    parser.add_argument('--num-workers', type=int, default=4)

    # S3 설정
    parser.add_argument('--image-bucket', type=str, default='say1-pre-project-5',
                        help='CXR 이미지 S3 버킷')
    parser.add_argument('--work-bucket', type=str,
                        default='pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an',
                        help='작업 S3 버킷 (CheXmask 캐시용)')

    # SageMaker 경로 (사용하지 않지만 호환성 유지)
    parser.add_argument('--masks-dir', type=str,
                        default=os.environ.get('SM_CHANNEL_MASKS', ''))
    parser.add_argument('--manifest-dir', type=str,
                        default=os.environ.get('SM_CHANNEL_MANIFEST', ''))
    parser.add_argument('--model-dir', type=str,
                        default=os.environ.get('SM_MODEL_DIR', '/opt/ml/model'))

    args = parser.parse_args()
    main(args)
