"""
VinDr-CXR (PNG 1024) → YOLOv8 전처리 파이프라인

Kaggle에 이미 PNG 1024x1024로 변환된 데이터셋 사용 (~3.6GB).
원본 DICOM(50GB) 대신 경량 버전 사용.

SageMaker 노트북 인스턴스에서 실행.

실행 전 필수:
  1. Kaggle API 토큰:
     aws s3 cp s3://pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an/config/kaggle.json ~/.kaggle/
     chmod 600 ~/.kaggle/kaggle.json
  2. pip install ensemble-boxes

사용법:
  python preprocess_vindr.py              # 전체 파이프라인 (3단계)
  python preprocess_vindr.py --step download   # Step 1: Kaggle 다운로드
  python preprocess_vindr.py --step merge      # Step 2: WBF 병합
  python preprocess_vindr.py --step yolo       # Step 3: YOLO 변환 + S3 업로드
"""

import os
import sys
import argparse
import time
import json
import glob
import subprocess
from collections import defaultdict

import numpy as np
import pandas as pd

# ============================================================
# 설정
# ============================================================
WORK_BUCKET = 'pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an'

# Kaggle 데이터셋 (PNG 1024x1024, ~3.6GB — 원본 DICOM 50GB 대비 1/14)
KAGGLE_PNG_DATASET = 'xhlulu/vinbigdata-chest-xray-resized-png-1024x1024'
KAGGLE_COMPETITION = 'vinbigdata-chest-xray-abnormalities-detection'

# 로컬 경로 (SageMaker 노트북 EBS)
BASE_DIR = '/home/ec2-user/SageMaker/vindr-cxr'
PNG_DIR = os.path.join(BASE_DIR, 'png_1024')       # PNG 이미지
ANNO_DIR = os.path.join(BASE_DIR, 'annotations')    # CSV
YOLO_DIR = os.path.join(BASE_DIR, 'yolo_dataset')   # 최종 YOLO 포맷

# S3 업로드 경로
S3_PREFIX = 'vindr-cxr/processed'

# 이미지 크기 (PNG 데이터셋 기준)
ORIGINAL_SIZE = 1024  # PNG 다운로드 크기
TARGET_SIZE = 640     # YOLOv8 학습 크기 (리사이즈는 Ultralytics가 자동 처리)

# VinDr-CXR 14 클래스 (No finding 제외)
CLASS_NAMES = [
    'Aortic_enlargement',    # 0
    'Atelectasis',           # 1
    'Calcification',         # 2
    'Cardiomegaly',          # 3
    'Consolidation',         # 4
    'ILD',                   # 5
    'Infiltration',          # 6
    'Lung_Opacity',          # 7
    'Nodule_Mass',           # 8
    'Other_lesion',          # 9
    'Pleural_effusion',      # 10
    'Pleural_thickening',    # 11
    'Pneumothorax',          # 12
    'Pulmonary_fibrosis',    # 13
]
NUM_CLASSES = 14


# ============================================================
# Step 1: Kaggle 다운로드 (PNG 1024 + 어노테이션 CSV)
# ============================================================
def step_download():
    """PNG 1024x1024 이미지 + train.csv 다운로드"""
    print("=" * 60)
    print("Step 1: Kaggle 다운로드 (PNG 1024 + CSV)")
    print("=" * 60)

    # kaggle CLI 설치 + 경로 확인
    subprocess.call([sys.executable, '-m', 'pip', 'install', '-q', 'kaggle'])

    # kaggle CLI 경로 탐색
    kaggle_cmd = None
    for candidate in ['kaggle', os.path.expanduser('~/.local/bin/kaggle'),
                       '/opt/conda/bin/kaggle', '/usr/local/bin/kaggle']:
        if subprocess.call(['which', candidate], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL) == 0:
            kaggle_cmd = candidate
            break
    if not kaggle_cmd:
        # pip show로 설치 위치 확인
        result = subprocess.run([sys.executable, '-m', 'pip', 'show', 'kaggle'],
                               capture_output=True, text=True)
        print("  kaggle 패키지 정보:")
        print(result.stdout)
        # scripts 디렉토리에서 찾기
        import sysconfig
        scripts = sysconfig.get_path('scripts')
        candidate = os.path.join(scripts, 'kaggle')
        if os.path.exists(candidate):
            kaggle_cmd = candidate
        else:
            # 최후의 수단: Kaggle API 직접 사용
            kaggle_cmd = None

    # 토큰 확인
    kaggle_json = os.path.expanduser('~/.kaggle/kaggle.json')
    if not os.path.exists(kaggle_json):
        print("[오류] Kaggle 토큰 없음! 먼저 실행:")
        print(f"  aws s3 cp s3://{WORK_BUCKET}/config/kaggle.json ~/.kaggle/")
        print("  chmod 600 ~/.kaggle/kaggle.json")
        return False

    os.makedirs(PNG_DIR, exist_ok=True)
    os.makedirs(ANNO_DIR, exist_ok=True)

    def kaggle_download(args_list):
        """kaggle CLI 또는 Python API로 다운로드"""
        if kaggle_cmd:
            # CLI 직접 호출
            cmd = [kaggle_cmd] + args_list
            print(f"  실행: {' '.join(cmd)}")
            subprocess.check_call(cmd)
        else:
            # Python API fallback
            from kaggle.api.kaggle_api_extended import KaggleApi
            api = KaggleApi()
            api.authenticate()

            if args_list[0] == 'datasets':
                # kaggle datasets download -d <dataset> -p <path>
                dataset = args_list[args_list.index('-d') + 1]
                path = args_list[args_list.index('-p') + 1]
                print(f"  Python API: datasets.download({dataset})")
                api.dataset_download_files(dataset, path=path, unzip=False)
            elif args_list[0] == 'competitions':
                # kaggle competitions download -c <comp> -p <path>
                comp = args_list[args_list.index('-c') + 1]
                path = args_list[args_list.index('-p') + 1]
                if '-f' in args_list:
                    fname = args_list[args_list.index('-f') + 1]
                    print(f"  Python API: competition_download_file({comp}, {fname})")
                    api.competition_download_file(comp, fname, path=path)
                else:
                    print(f"  Python API: competition_download_files({comp})")
                    api.competition_download_files(comp, path=path)

    # --- 1-1: PNG 1024 이미지 다운로드 (~3.6GB) ---
    print(f"\n[1/2] PNG 1024x1024 다운로드 (~3.6GB)")
    print(f"  데이터셋: {KAGGLE_PNG_DATASET}")
    start = time.time()

    try:
        kaggle_download(['datasets', 'download', '-d', KAGGLE_PNG_DATASET, '-p', PNG_DIR])
    except Exception as e:
        print(f"  [오류] 다운로드 실패: {e}")
        return False

    # zip 압축 해제
    zip_files = glob.glob(os.path.join(PNG_DIR, '*.zip'))
    for zf in zip_files:
        print(f"  압축 해제: {os.path.basename(zf)}...")
        subprocess.check_call(['unzip', '-q', '-o', zf, '-d', PNG_DIR])
        os.remove(zf)

    elapsed = time.time() - start
    print(f"  완료! ({elapsed/60:.1f}분)")

    # --- 1-2: 대회 train.csv 다운로드 (어노테이션) ---
    print(f"\n[2/2] train.csv 다운로드 (어노테이션)")
    try:
        kaggle_download(['competitions', 'download', '-c', KAGGLE_COMPETITION,
                         '-f', 'train.csv', '-p', ANNO_DIR])
    except Exception:
        print("  개별 파일 다운로드 실패. 전체 다운로드 시도...")
        try:
            kaggle_download(['competitions', 'download', '-c', KAGGLE_COMPETITION,
                             '-p', ANNO_DIR])
            zip_files = glob.glob(os.path.join(ANNO_DIR, '*.zip'))
            for zf in zip_files:
                subprocess.call(['unzip', '-q', '-o', zf, 'train.csv', '-d', ANNO_DIR])
                os.remove(zf)
        except Exception as e:
            print(f"  [오류] train.csv 다운로드 실패: {e}")
            print("  수동으로 다운로드 후 여기에 복사하세요:")
            print(f"    {ANNO_DIR}/train.csv")
            return False

    # 결과 확인
    train_dir = _find_train_dir()
    train_csv = _find_train_csv()

    png_count = len(glob.glob(os.path.join(train_dir, '*.png'))) if train_dir else 0
    print(f"\n결과:")
    print(f"  PNG 이미지: {png_count:,}장")
    print(f"  이미지 경로: {train_dir}")
    print(f"  train.csv: {'있음' if train_csv else '없음'}")

    return True


def _find_train_dir():
    """PNG train 이미지 디렉토리 찾기 (하위 폴더 탐색)"""
    # 가능한 경로들
    candidates = [
        os.path.join(PNG_DIR, 'train'),
        os.path.join(PNG_DIR, 'vinbigdata-chest-xray-resized-png-1024x1024', 'train'),
        PNG_DIR,
    ]
    for d in candidates:
        if os.path.isdir(d) and glob.glob(os.path.join(d, '*.png')):
            return d

    # 재귀 탐색
    for root, dirs, files in os.walk(PNG_DIR):
        pngs = [f for f in files if f.endswith('.png')]
        if len(pngs) > 100:
            return root

    return None


def _find_train_csv():
    """train.csv 찾기"""
    candidates = [
        os.path.join(ANNO_DIR, 'train.csv'),
        os.path.join(PNG_DIR, 'train.csv'),
        os.path.join(BASE_DIR, 'train.csv'),
    ]
    for f in candidates:
        if os.path.exists(f):
            return f

    # 재귀 탐색
    for root, dirs, files in os.walk(BASE_DIR):
        if 'train.csv' in files:
            return os.path.join(root, 'train.csv')

    return None


# ============================================================
# Step 2: 다중 어노테이터 WBF 병합
# ============================================================
def step_merge():
    """3명 방사선과 전문의 어노테이션을 WBF로 병합"""
    print("=" * 60)
    print("Step 2: 다중 어노테이터 WBF 병합")
    print("=" * 60)

    try:
        from ensemble_boxes import weighted_boxes_fusion
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-q', 'ensemble-boxes'])
        from ensemble_boxes import weighted_boxes_fusion

    train_csv = _find_train_csv()
    if not train_csv:
        print("[오류] train.csv 없음. Step 1을 먼저 실행하세요.")
        return None

    # CSV 로드
    df = pd.read_csv(train_csv)
    print(f"원본 어노테이션: {len(df):,}행")
    print(f"이미지 수: {df['image_id'].nunique():,}")
    print(f"어노테이터 수: {df['rad_id'].nunique()}")

    # 클래스별 통계
    print(f"\n클래스별 인스턴스 (병합 전):")
    for cid in sorted(df['class_id'].unique()):
        name = df[df['class_id'] == cid]['class_name'].iloc[0]
        count = len(df[df['class_id'] == cid])
        print(f"  [{cid:2d}] {name:<30s} {count:,}")

    # No finding (class_id=14) 분리
    nf_image_ids = df[df['class_id'] == 14]['image_id'].unique()
    df_abnormal = df[df['class_id'] != 14].copy()

    print(f"\nNo finding 이미지: {len(nf_image_ids):,}개")
    print(f"이상 소견 어노테이션: {len(df_abnormal):,}행 ({df_abnormal['image_id'].nunique():,}개 이미지)")

    # 원본 이미지 크기 추정
    # VinDr-CXR 원본은 다양한 크기지만, bbox 좌표는 원본 기준
    # PNG 1024 데이터셋은 리사이즈됨 → bbox도 스케일링 필요
    # train.csv의 bbox 좌표는 원본 DICOM 기준이므로, 이미지별 원본 크기가 필요
    # 하지만 PNG 1024에는 원본 크기 정보가 없음
    # → bbox를 정규화(0~1)할 때 max(x_max, y_max) 기반으로 원본 크기 추정

    # 이미지별 WBF 병합
    merged_results = []
    image_ids = df_abnormal['image_id'].unique()
    start = time.time()

    for idx, image_id in enumerate(image_ids):
        img_df = df_abnormal[df_abnormal['image_id'] == image_id]

        # 원본 이미지 크기 추정 (bbox 좌표 max값 기반)
        max_x = img_df['x_max'].max()
        max_y = img_df['y_max'].max()
        # VinDr-CXR 원본은 대부분 2000~3000px 범위
        orig_w = max(max_x + 10, 1024)
        orig_h = max(max_y + 10, 1024)

        # 어노테이터별 bbox 분리
        rad_ids = img_df['rad_id'].unique()
        boxes_list = []
        scores_list = []
        labels_list = []

        for rad_id in rad_ids:
            rad_df = img_df[img_df['rad_id'] == rad_id]
            boxes = []
            scores = []
            labels = []

            for _, row in rad_df.iterrows():
                cid = int(row['class_id'])
                if cid >= NUM_CLASSES:
                    continue

                # 정규화 (0~1) — 원본 크기 기준
                x1 = max(0, row['x_min'] / orig_w)
                y1 = max(0, row['y_min'] / orig_h)
                x2 = min(1, row['x_max'] / orig_w)
                y2 = min(1, row['y_max'] / orig_h)

                if x2 <= x1 or y2 <= y1:
                    continue

                boxes.append([x1, y1, x2, y2])
                scores.append(1.0)
                labels.append(cid)

            if boxes:
                boxes_list.append(boxes)
                scores_list.append(scores)
                labels_list.append(labels)

        if not boxes_list:
            continue

        # WBF 병합
        # skip_box_thr=0.33 → 3명 중 2명 이상 동의한 bbox만 채택
        try:
            fused_boxes, fused_scores, fused_labels = weighted_boxes_fusion(
                boxes_list, scores_list, labels_list,
                iou_thr=0.5,
                skip_box_thr=0.33,
                weights=None
            )
        except Exception as e:
            print(f"  [WARN] WBF 실패 ({image_id}): {e}")
            continue

        for box, score, label in zip(fused_boxes, fused_scores, fused_labels):
            merged_results.append({
                'image_id': image_id,
                'class_id': int(label),
                'class_name': CLASS_NAMES[int(label)],
                # 정규화 좌표 저장 (0~1) — YOLO 변환 시 그대로 사용
                'x1_norm': float(box[0]),
                'y1_norm': float(box[1]),
                'x2_norm': float(box[2]),
                'y2_norm': float(box[3]),
                'score': float(score),
            })

        if (idx + 1) % 2000 == 0 or (idx + 1) == len(image_ids):
            elapsed = time.time() - start
            pct = (idx + 1) / len(image_ids) * 100
            print(f"  {idx+1:,}/{len(image_ids):,} ({pct:.1f}%) | {elapsed:.0f}s")

    merged_df = pd.DataFrame(merged_results)
    elapsed = time.time() - start

    print(f"\n병합 완료! ({elapsed:.0f}s)")
    print(f"  병합 전: {len(df_abnormal):,}행")
    print(f"  병합 후: {len(merged_df):,}행 ({merged_df['image_id'].nunique():,}개 이미지)")
    print(f"\n클래스별 (병합 후):")
    for cid in range(NUM_CLASSES):
        count = len(merged_df[merged_df['class_id'] == cid])
        print(f"  [{cid:2d}] {CLASS_NAMES[cid]:<25s} {count:,}")

    # 저장
    os.makedirs(ANNO_DIR, exist_ok=True)
    merged_csv = os.path.join(ANNO_DIR, 'train_merged_wbf.csv')
    merged_df.to_csv(merged_csv, index=False)
    print(f"\n저장: {merged_csv}")

    # No finding 이미지 목록
    nf_path = os.path.join(ANNO_DIR, 'no_finding_images.txt')
    with open(nf_path, 'w') as f:
        for img_id in nf_image_ids:
            f.write(f"{img_id}\n")
    print(f"No finding 목록: {nf_path} ({len(nf_image_ids):,}개)")

    return merged_df


# ============================================================
# Step 3: YOLO 포맷 변환 + train/val split + S3 업로드
# ============================================================
def step_yolo():
    """병합 CSV → YOLO txt + train/val 분할 + S3 업로드"""
    print("=" * 60)
    print("Step 3: YOLO 변환 + S3 업로드")
    print("=" * 60)

    # 병합 CSV 로드
    merged_csv = os.path.join(ANNO_DIR, 'train_merged_wbf.csv')
    if not os.path.exists(merged_csv):
        print("[오류] train_merged_wbf.csv 없음. Step 2를 먼저 실행하세요.")
        return False

    merged_df = pd.read_csv(merged_csv)
    train_dir = _find_train_dir()
    if not train_dir:
        print("[오류] PNG 이미지 디렉토리를 찾을 수 없습니다.")
        return False

    print(f"병합 어노테이션: {len(merged_df):,}행")
    print(f"PNG 경로: {train_dir}")

    # YOLO 디렉토리 구조 생성
    for split in ['train', 'val']:
        os.makedirs(os.path.join(YOLO_DIR, 'images', split), exist_ok=True)
        os.makedirs(os.path.join(YOLO_DIR, 'labels', split), exist_ok=True)

    # ---- train/val 분할 (80/20, 이미지 단위) ----
    abnormal_images = sorted(merged_df['image_id'].unique())
    np.random.seed(42)
    np.random.shuffle(abnormal_images)

    split_idx = int(len(abnormal_images) * 0.8)
    train_set = set(abnormal_images[:split_idx])
    val_set = set(abnormal_images[split_idx:])

    # No finding 30%를 배경 네거티브로 포함
    nf_path = os.path.join(ANNO_DIR, 'no_finding_images.txt')
    nf_train, nf_val = [], []
    if os.path.exists(nf_path):
        with open(nf_path) as f:
            nf_all = [line.strip() for line in f if line.strip()]
        np.random.seed(42)
        np.random.shuffle(nf_all)
        nf_use = nf_all[:int(len(nf_all) * 0.3)]
        nf_split = int(len(nf_use) * 0.8)
        nf_train = nf_use[:nf_split]
        nf_val = nf_use[nf_split:]
        print(f"No finding 배경: {len(nf_use):,}개 (전체의 30%)")

    print(f"이상 소견: train {len(train_set):,} / val {len(val_set):,}")
    print(f"배경(NF):  train {len(nf_train):,} / val {len(nf_val):,}")

    # ---- YOLO 라벨 + 이미지 링크 ----
    start = time.time()
    stats = {'train': 0, 'val': 0, 'labels': 0, 'bg_train': 0, 'bg_val': 0, 'skip': 0}

    grouped = merged_df.groupby('image_id')

    for image_id, group in grouped:
        if image_id in train_set:
            split = 'train'
        elif image_id in val_set:
            split = 'val'
        else:
            continue

        # PNG 확인
        src_png = os.path.join(train_dir, f"{image_id}.png")
        if not os.path.exists(src_png):
            stats['skip'] += 1
            continue

        # 이미지 하드링크 (디스크 절약)
        dst_img = os.path.join(YOLO_DIR, 'images', split, f"{image_id}.png")
        if not os.path.exists(dst_img):
            try:
                os.link(src_png, dst_img)
            except OSError:
                # 하드링크 안 되면 심볼릭 링크
                os.symlink(src_png, dst_img)

        # YOLO 라벨 파일 (정규화 좌표 → x_center, y_center, w, h)
        label_path = os.path.join(YOLO_DIR, 'labels', split, f"{image_id}.txt")
        with open(label_path, 'w') as f:
            for _, row in group.iterrows():
                cid = int(row['class_id'])
                x1, y1 = row['x1_norm'], row['y1_norm']
                x2, y2 = row['x2_norm'], row['y2_norm']

                x_center = (x1 + x2) / 2
                y_center = (y1 + y2) / 2
                w = x2 - x1
                h = y2 - y1

                # 클리핑
                x_center = max(0, min(1, x_center))
                y_center = max(0, min(1, y_center))
                w = max(0.001, min(1, w))
                h = max(0.001, min(1, h))

                f.write(f"{cid} {x_center:.6f} {y_center:.6f} {w:.6f} {h:.6f}\n")
                stats['labels'] += 1

        stats[split] += 1

    # 배경 이미지 (빈 라벨)
    for img_list, split, key in [(nf_train, 'train', 'bg_train'), (nf_val, 'val', 'bg_val')]:
        for img_id in img_list:
            src_png = os.path.join(train_dir, f"{img_id}.png")
            if not os.path.exists(src_png):
                continue

            dst_img = os.path.join(YOLO_DIR, 'images', split, f"{img_id}.png")
            if not os.path.exists(dst_img):
                try:
                    os.link(src_png, dst_img)
                except OSError:
                    os.symlink(src_png, dst_img)

            label_path = os.path.join(YOLO_DIR, 'labels', split, f"{img_id}.txt")
            if not os.path.exists(label_path):
                open(label_path, 'w').close()
            stats[key] += 1

    elapsed = time.time() - start
    print(f"\nYOLO 변환 완료! ({elapsed:.0f}s)")
    print(f"  Train: {stats['train']:,} + 배경 {stats['bg_train']:,} = {stats['train']+stats['bg_train']:,}")
    print(f"  Val:   {stats['val']:,} + 배경 {stats['bg_val']:,} = {stats['val']+stats['bg_val']:,}")
    print(f"  라벨:  {stats['labels']:,}개")
    if stats['skip']:
        print(f"  스킵:  {stats['skip']}개 (PNG 없음)")

    # ---- data.yaml 생성 ----
    data_yaml_content = f"""# VinDr-CXR YOLOv8 Dataset (PNG 1024 기반)
# Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}
# Train: {stats['train']+stats['bg_train']:,} images
# Val: {stats['val']+stats['bg_val']:,} images
# Annotations: {stats['labels']:,} boxes

path: /opt/ml/input/data/training
train: images/train
val: images/val

nc: {NUM_CLASSES}
names:
"""
    for i, name in enumerate(CLASS_NAMES):
        data_yaml_content += f"  {i}: {name}\n"

    data_yaml_path = os.path.join(YOLO_DIR, 'data.yaml')
    with open(data_yaml_path, 'w') as f:
        f.write(data_yaml_content)

    # 통계 JSON
    dataset_stats = {
        'train_abnormal': stats['train'],
        'train_background': stats['bg_train'],
        'train_total': stats['train'] + stats['bg_train'],
        'val_abnormal': stats['val'],
        'val_background': stats['bg_val'],
        'val_total': stats['val'] + stats['bg_val'],
        'total_labels': stats['labels'],
        'num_classes': NUM_CLASSES,
        'class_names': CLASS_NAMES,
        'image_size': f'{ORIGINAL_SIZE}x{ORIGINAL_SIZE}',
    }
    stats_path = os.path.join(YOLO_DIR, 'dataset_stats.json')
    with open(stats_path, 'w') as f:
        json.dump(dataset_stats, f, indent=2, ensure_ascii=False)

    print(f"\ndata.yaml: {data_yaml_path}")
    print(f"통계: {stats_path}")

    # ---- 검증 ----
    print(f"\n검증:")
    for split in ['train', 'val']:
        img_dir = os.path.join(YOLO_DIR, 'images', split)
        lbl_dir = os.path.join(YOLO_DIR, 'labels', split)
        imgs = set(os.path.splitext(f)[0] for f in os.listdir(img_dir))
        lbls = set(os.path.splitext(f)[0] for f in os.listdir(lbl_dir))
        only_img = imgs - lbls
        only_lbl = lbls - imgs
        print(f"  {split}: 이미지 {len(imgs):,} / 라벨 {len(lbls):,} | "
              f"불일치: img-only={len(only_img)}, lbl-only={len(only_lbl)}")

    # ---- S3 업로드 ----
    s3_uri = f"s3://{WORK_BUCKET}/{S3_PREFIX}/"
    print(f"\nS3 업로드: {YOLO_DIR} → {s3_uri}")
    print("(파일 수가 많아 몇 분 소요될 수 있습니다...)")

    start = time.time()
    subprocess.check_call([
        'aws', 's3', 'sync', YOLO_DIR, s3_uri,
        '--region', 'ap-northeast-2',
        '--only-show-errors'
    ])
    elapsed = time.time() - start
    print(f"S3 업로드 완료! ({elapsed/60:.1f}분)")

    # 병합 CSV도 업로드
    subprocess.call([
        'aws', 's3', 'cp', merged_csv,
        f"s3://{WORK_BUCKET}/vindr-cxr/annotations/train_merged_wbf.csv",
        '--region', 'ap-northeast-2', '--only-show-errors'
    ])

    print(f"\n최종 데이터 경로: {s3_uri}")
    print("SageMaker 학습 잡에서 이 경로를 InputDataConfig에 설정하세요.")

    return True


# ============================================================
# 메인
# ============================================================
def main():
    parser = argparse.ArgumentParser(description='VinDr-CXR (PNG 1024) → YOLOv8 전처리')
    parser.add_argument('--step', type=str, default='all',
                        choices=['all', 'download', 'merge', 'yolo'],
                        help='실행할 단계')
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"VinDr-CXR → YOLOv8 전처리 (PNG 1024 경량 버전)")
    print(f"{'='*60}")
    print(f"이미지: {KAGGLE_PNG_DATASET} (~3.6GB)")
    print(f"클래스: {NUM_CLASSES}개")
    print(f"BASE_DIR: {BASE_DIR}")
    print()

    steps = {
        'download': step_download,
        'merge': step_merge,
        'yolo': step_yolo,
    }

    if args.step == 'all':
        total_start = time.time()
        for name, func in steps.items():
            result = func()
            if result is False:
                print(f"\n[중단] {name} 실패. --step {name}으로 재시도하세요.")
                return
            print()

        total_elapsed = time.time() - total_start
        print(f"\n전체 완료! (총 {total_elapsed/60:.1f}분)")
        print(f"S3 데이터: s3://{WORK_BUCKET}/{S3_PREFIX}/")
    else:
        steps[args.step]()


if __name__ == '__main__':
    main()
