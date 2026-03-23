"""
SageMaker 노트북에서 실행: CheXmask 다운로드 + 전처리

실행 순서:
    Step 1: PhysioNet에서 CheXmask Preprocessed CSV 다운로드
    Step 2: preprocessing.py로 p10 필터링 + RLE 디코딩 + NPZ 저장
    Step 3: S3에 업로드

SageMaker 노트북에서 셀 단위로 실행 (Jupyter에 복붙)
"""

# ============================================================
# Cell 1: 환경 설정
# ============================================================
import os
import subprocess
import time

WORK_DIR = '/home/ec2-user/SageMaker/unet_data'
os.makedirs(WORK_DIR, exist_ok=True)
os.chdir(WORK_DIR)

BUCKET = 'pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an'
S3_PREFIX = 'data/unet_masks'

print(f"작업 디렉토리: {WORK_DIR}")
print(f"S3 대상: s3://{BUCKET}/{S3_PREFIX}/")


# ============================================================
# Cell 2: CheXmask Preprocessed CSV 다운로드 (~4.4 GB, ~5-10분)
# ============================================================
CHEXMASK_URL = (
    "https://physionet.org/files/chexmask-cxr-segmentation-data/1.0.0/"
    "Preprocessed/MIMIC-CXR-JPG.csv"
)
CSV_PATH = os.path.join(WORK_DIR, 'MIMIC-CXR-JPG.csv')

if os.path.exists(CSV_PATH):
    size_gb = os.path.getsize(CSV_PATH) / (1024**3)
    print(f"이미 다운로드됨: {CSV_PATH} ({size_gb:.1f} GB)")
else:
    print("CheXmask CSV 다운로드 시작 (~4.4 GB)...")
    print(f"URL: {CHEXMASK_URL}")
    start = time.time()

    # wget으로 다운로드 (진행률 표시)
    subprocess.run([
        'wget', '-O', CSV_PATH,
        '--progress=bar:force',
        CHEXMASK_URL
    ], check=True)

    elapsed = time.time() - start
    size_gb = os.path.getsize(CSV_PATH) / (1024**3)
    print(f"다운로드 완료: {size_gb:.1f} GB ({elapsed:.0f}초)")


# ============================================================
# Cell 3: MIMIC-CXR split CSV 복사 (S3에서)
# ============================================================
SPLIT_CSV_PATH = os.path.join(WORK_DIR, 'mimic-cxr-2.0.0-split.csv')

if not os.path.exists(SPLIT_CSV_PATH):
    print("Split CSV 다운로드 중 (S3)...")
    subprocess.run([
        'aws', 's3', 'cp',
        f's3://{BUCKET}/data/mimic-cxr-csv/mimic-cxr-2.0.0-split.csv',
        SPLIT_CSV_PATH
    ], check=True)
    print("Split CSV 준비 완료")
else:
    print(f"이미 존재: {SPLIT_CSV_PATH}")


# ============================================================
# Cell 4: 전처리 코드 복사 (로컬 프로젝트에서 S3를 경유)
#
# 방법 1: 로컬에서 S3 업로드 후 SageMaker에서 다운로드
#   aws s3 cp layer1_segmentation/preprocessing.py s3://BUCKET/code/preprocessing.py
#
# 방법 2: SageMaker 노트북에 직접 복사
# ============================================================
print("전처리 코드가 SageMaker에 있는지 확인...")
PREPROC_PATH = '/home/ec2-user/SageMaker/forpreproject/layer1_segmentation/preprocessing.py'

if os.path.exists(PREPROC_PATH):
    print(f"코드 존재: {PREPROC_PATH}")
else:
    # S3에서 다운로드 시도
    print("S3에서 코드 다운로드 시도...")
    subprocess.run([
        'aws', 's3', 'cp',
        f's3://{BUCKET}/code/layer1_segmentation/preprocessing.py',
        os.path.join(WORK_DIR, 'preprocessing.py')
    ])
    PREPROC_PATH = os.path.join(WORK_DIR, 'preprocessing.py')


# ============================================================
# Cell 5: 전처리 실행 (p10 필터 + RLE 디코딩 + NPZ 저장)
# ============================================================
import sys
sys.path.insert(0, os.path.dirname(PREPROC_PATH))

from preprocessing import prepare_training_data

OUTPUT_DIR = os.path.join(WORK_DIR, 'masks_512')

prepare_training_data(
    chexmask_csv_path=CSV_PATH,
    split_csv_path=SPLIT_CSV_PATH,
    output_base_dir=OUTPUT_DIR,
    target_size=512,
    quality_threshold=0.7,
    format='npz',
)


# ============================================================
# Cell 6: 결과 확인
# ============================================================
for split in ['train', 'validate', 'test']:
    split_dir = os.path.join(OUTPUT_DIR, split)
    if os.path.exists(split_dir):
        count = len([f for f in os.listdir(split_dir) if f.endswith('.npz')])
        print(f"  {split}: {count:,}개 마스크")
    else:
        print(f"  {split}: 디렉토리 없음")


# ============================================================
# Cell 7: 샘플 시각화 (마스크 + 원본 이미지 비교)
# ============================================================
import numpy as np
import matplotlib.pyplot as plt

sample_dir = os.path.join(OUTPUT_DIR, 'train')
if os.path.exists(sample_dir):
    npz_files = [f for f in os.listdir(sample_dir) if f.endswith('.npz')]
    if npz_files:
        data = np.load(os.path.join(sample_dir, npz_files[0]))

        fig, axes = plt.subplots(1, 4, figsize=(20, 5))

        axes[0].imshow(data['combined'], cmap='nipy_spectral', vmin=0, vmax=3)
        axes[0].set_title('Combined (0:BG, 1:LL, 2:RL, 3:Heart)')

        axes[1].imshow(data['left_lung'], cmap='gray')
        axes[1].set_title('Left Lung')

        axes[2].imshow(data['right_lung'], cmap='gray')
        axes[2].set_title('Right Lung')

        axes[3].imshow(data['heart'], cmap='gray')
        axes[3].set_title('Heart')

        for ax in axes:
            ax.axis('off')

        plt.suptitle(f"Image: {str(data['image_id'])}")
        plt.tight_layout()
        plt.savefig(os.path.join(WORK_DIR, 'sample_masks.png'), dpi=100)
        plt.show()
        print("시각화 저장: sample_masks.png")


# ============================================================
# Cell 8: S3 업로드
# ============================================================
print("S3 업로드 시작...")
start = time.time()

subprocess.run([
    'aws', 's3', 'sync',
    OUTPUT_DIR,
    f's3://{BUCKET}/{S3_PREFIX}/',
    '--quiet'
], check=True)

elapsed = time.time() - start
print(f"S3 업로드 완료 ({elapsed:.0f}초)")
print(f"경로: s3://{BUCKET}/{S3_PREFIX}/")


# ============================================================
# Cell 9: 정리 (선택사항 - 디스크 공간 확보)
# ============================================================
# CheXmask CSV는 4.4GB이므로 노트북 디스크 확보 필요시 삭제
# os.remove(CSV_PATH)
# print("CheXmask CSV 삭제 완료")
