"""
CheXmask RLE → NumPy 마스크 변환 + 학습용 데이터 준비

CheXmask CSV 포맷:
- 컬럼: ImageID, Dice_RCA_Max, Dice_RCA_Mean, Landmarks, Left Lung, Right Lung, Heart, Height, Width
- 마스크: RLE(Run-Length Encoding) 공백 구분 문자열
- RLE: "start1 len1 start2 len2 ..." (1-indexed)

사용법 (SageMaker 노트북):
    1. PhysioNet에서 CheXmask CSV 다운로드
    2. MIMIC-CXR 이미지 경로와 매핑
    3. 학습/검증/테스트 split
    4. NPZ 또는 PNG로 저장 → S3 업로드
"""

import numpy as np
import pandas as pd
import os
from PIL import Image


# ============================================================
# RLE 디코딩 (CheXmask 공식 코드 기반)
# ============================================================
def rle_to_mask(rle_string, height, width):
    """
    RLE 문자열 → 바이너리 마스크 (H x W, uint8)

    Args:
        rle_string: "start1 len1 start2 len2 ..." (1-indexed, 공백 구분)
        height: 마스크 높이
        width: 마스크 너비

    Returns:
        np.ndarray: shape (height, width), dtype uint8, 값 0 또는 1
    """
    if pd.isna(rle_string) or rle_string == '' or rle_string == 'nan':
        return np.zeros((height, width), dtype=np.uint8)

    runs = np.array([int(x) for x in str(rle_string).split()])
    starts = runs[0::2]    # 짝수 인덱스: 시작 위치 (1-indexed)
    lengths = runs[1::2]   # 홀수 인덱스: 연속 길이

    mask = np.zeros(height * width, dtype=np.uint8)
    for start, length in zip(starts, lengths):
        start -= 1  # 1-indexed → 0-indexed
        mask[start:start + length] = 1

    return mask.reshape((height, width))


def mask_to_rle(mask):
    """
    바이너리 마스크 → RLE 문자열 (디버깅/검증용)

    Args:
        mask: np.ndarray, shape (H, W), 값 0 또는 1

    Returns:
        str: RLE 문자열
    """
    flat = mask.flatten()
    # 변화점 찾기
    padded = np.concatenate([[0], flat, [0]])
    diff = np.diff(padded)
    starts = np.where(diff == 1)[0] + 1   # 1-indexed
    ends = np.where(diff == -1)[0] + 1
    lengths = ends - starts + 1

    rle_pairs = []
    for s, l in zip(starts, lengths):
        rle_pairs.extend([str(s), str(l)])

    return ' '.join(rle_pairs)


# ============================================================
# CheXmask CSV 로드 + 필터링
# ============================================================
def load_chexmask_csv(csv_path, quality_threshold=0.7):
    """
    CheXmask CSV 로드 및 품질 필터링

    Args:
        csv_path: CheXmask CSV 파일 경로
        quality_threshold: Dice RCA Mean 최소값 (기본 0.7)

    Returns:
        pd.DataFrame: 필터링된 데이터프레임
    """
    print(f"CSV 로드 중: {csv_path}")
    df = pd.read_csv(csv_path)
    print(f"  전체 행: {len(df):,}")

    # 컬럼명 확인 및 표준화
    print(f"  컬럼: {list(df.columns)}")

    # 품질 필터 (Dice RCA Mean ≥ threshold)
    dice_col = None
    for col in df.columns:
        if 'dice' in col.lower() and 'mean' in col.lower():
            dice_col = col
            break

    if dice_col:
        before = len(df)
        df = df[df[dice_col] >= quality_threshold]
        print(f"  품질 필터 (Dice Mean ≥ {quality_threshold}): {before:,} → {len(df):,}")

    return df


def filter_p10_subset(df, image_id_col=None):
    """
    p10 그룹만 필터링 (MIMIC-CXR의 우리 학습 데이터)

    MIMIC-CXR ImageID 형식: "files/p10/p10000032/s50414267/02aa804e-bde0afdd-112c0b34-7bc16630-4e384014.jpg"
    또는 "p10000032_s50414267_02aa804e-..." 등

    Args:
        df: CheXmask 데이터프레임
        image_id_col: ImageID 컬럼명 (None이면 자동 탐지)

    Returns:
        pd.DataFrame: p10 서브셋
    """
    # ImageID 컬럼 자동 탐지
    if image_id_col is None:
        for col in df.columns:
            if 'image' in col.lower() or 'id' in col.lower():
                image_id_col = col
                break
        if image_id_col is None:
            image_id_col = df.columns[0]

    print(f"  ImageID 컬럼: {image_id_col}")
    print(f"  샘플: {df[image_id_col].iloc[0]}")

    # p10 필터 (경로에 'p10/' 또는 'p10' 포함)
    before = len(df)
    mask = df[image_id_col].astype(str).str.contains('p10', case=False)
    df_p10 = df[mask].copy()
    print(f"  p10 필터: {before:,} → {len(df_p10):,}")

    return df_p10


# ============================================================
# 마스크 추출 + 저장
# ============================================================
def decode_all_masks(row, target_size=512):
    """
    한 행에서 좌폐/우폐/심장 3채널 마스크 추출

    Args:
        row: DataFrame 행 (Left Lung, Right Lung, Heart, Height, Width 컬럼)
        target_size: 리사이즈 목표 크기

    Returns:
        dict: {
            'left_lung': np.ndarray (target_size, target_size),
            'right_lung': np.ndarray (target_size, target_size),
            'heart': np.ndarray (target_size, target_size),
            'combined': np.ndarray (target_size, target_size) - 0:배경, 1:좌폐, 2:우폐, 3:심장
        }
    """
    height = int(row['Height'])
    width = int(row['Width'])

    # RLE 디코딩
    left_lung = rle_to_mask(row.get('Left Lung', ''), height, width)
    right_lung = rle_to_mask(row.get('Right Lung', ''), height, width)
    heart = rle_to_mask(row.get('Heart', ''), height, width)

    # 리사이즈 (Nearest Neighbor — 마스크는 보간하면 안 됨)
    if height != target_size or width != target_size:
        left_lung = np.array(
            Image.fromarray(left_lung).resize((target_size, target_size), Image.NEAREST)
        )
        right_lung = np.array(
            Image.fromarray(right_lung).resize((target_size, target_size), Image.NEAREST)
        )
        heart = np.array(
            Image.fromarray(heart).resize((target_size, target_size), Image.NEAREST)
        )

    # Combined mask: 0=배경, 1=좌폐, 2=우폐, 3=심장
    # 겹치는 영역은 심장 우선 (심장이 폐 위에 있으므로)
    combined = np.zeros((target_size, target_size), dtype=np.uint8)
    combined[left_lung > 0] = 1
    combined[right_lung > 0] = 2
    combined[heart > 0] = 3

    return {
        'left_lung': left_lung,
        'right_lung': right_lung,
        'heart': heart,
        'combined': combined,
    }


def save_masks_as_npz(df, output_dir, target_size=512, max_workers=4):
    """
    DataFrame의 모든 행에서 마스크를 추출하여 NPZ 파일로 저장

    각 이미지당 1개의 .npz 파일 생성:
        {image_id}.npz → combined_mask (H, W), left_lung, right_lung, heart

    Args:
        df: CheXmask 필터링된 DataFrame
        output_dir: 저장 디렉토리
        target_size: 마스크 해상도
        max_workers: 병렬 처리 수 (미사용, 순차 처리)
    """
    os.makedirs(output_dir, exist_ok=True)

    total = len(df)
    saved = 0
    errors = 0

    # ImageID 컬럼 탐지
    id_col = df.columns[0]

    for idx, (_, row) in enumerate(df.iterrows()):
        try:
            masks = decode_all_masks(row, target_size)

            # 파일명: ImageID에서 안전한 이름 추출
            image_id = str(row[id_col])
            # 경로 구분자 → 언더스코어, 확장자 제거
            safe_name = image_id.replace('/', '_').replace('\\', '_')
            safe_name = os.path.splitext(safe_name)[0]

            npz_path = os.path.join(output_dir, f"{safe_name}.npz")
            np.savez_compressed(
                npz_path,
                combined=masks['combined'],
                left_lung=masks['left_lung'],
                right_lung=masks['right_lung'],
                heart=masks['heart'],
                image_id=image_id,
            )
            saved += 1

        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"  [오류] {idx}: {e}")

        # 진행률 표시
        if (idx + 1) % 500 == 0 or idx == total - 1:
            pct = (idx + 1) / total * 100
            print(f"  진행: {idx + 1:,}/{total:,} ({pct:.1f}%) | 저장: {saved:,} | 오류: {errors}")

    print(f"\n완료: {saved:,}개 저장, {errors}개 오류")
    return saved, errors


def save_masks_as_png(df, output_dir, target_size=512):
    """
    마스크를 PNG로 저장 (시각화/디버깅용)
    Combined mask: 0=검정, 85=좌폐, 170=우폐, 255=심장
    """
    os.makedirs(output_dir, exist_ok=True)

    id_col = df.columns[0]
    total = len(df)

    for idx, (_, row) in enumerate(df.iterrows()):
        try:
            masks = decode_all_masks(row, target_size)

            # 시각화용 마스크 (클래스별 다른 밝기)
            vis = np.zeros((target_size, target_size), dtype=np.uint8)
            vis[masks['combined'] == 1] = 85    # 좌폐: 어두운 회색
            vis[masks['combined'] == 2] = 170   # 우폐: 밝은 회색
            vis[masks['combined'] == 3] = 255   # 심장: 흰색

            image_id = str(row[id_col])
            safe_name = image_id.replace('/', '_').replace('\\', '_')
            safe_name = os.path.splitext(safe_name)[0]

            Image.fromarray(vis).save(os.path.join(output_dir, f"{safe_name}.png"))

        except Exception as e:
            if idx < 3:
                print(f"  [오류] {idx}: {e}")

        if (idx + 1) % 500 == 0 or idx == total - 1:
            pct = (idx + 1) / total * 100
            print(f"  진행: {idx + 1:,}/{total:,} ({pct:.1f}%)")


# ============================================================
# 학습/검증/테스트 매핑
# ============================================================
def merge_with_split(chexmask_df, split_csv_path, image_id_col=None):
    """
    CheXmask 마스크 데이터와 MIMIC-CXR split 정보 병합

    Args:
        chexmask_df: CheXmask 필터링된 DataFrame
        split_csv_path: mimic-cxr-2.0.0-split.csv 경로
        image_id_col: CheXmask의 ImageID 컬럼명

    Returns:
        pd.DataFrame: split 정보가 추가된 DataFrame
    """
    split_df = pd.read_csv(split_csv_path)
    print(f"Split CSV 로드: {len(split_df):,}행")

    # CheXmask의 ImageID에서 dicom_id 추출
    if image_id_col is None:
        image_id_col = chexmask_df.columns[0]

    # ImageID 형식 분석 (첫 번째 행 확인 후 파싱 로직 결정)
    sample_id = str(chexmask_df[image_id_col].iloc[0])
    print(f"ImageID 샘플: {sample_id}")

    # dicom_id 추출 (파일명에서 .jpg 제거)
    chexmask_df = chexmask_df.copy()
    chexmask_df['dicom_id'] = chexmask_df[image_id_col].apply(
        lambda x: os.path.splitext(os.path.basename(str(x)))[0]
    )

    # split_df와 병합
    merged = chexmask_df.merge(
        split_df[['dicom_id', 'split']],
        on='dicom_id',
        how='inner'
    )
    print(f"병합 결과: {len(merged):,}행")
    print(f"  Split 분포: {merged['split'].value_counts().to_dict()}")

    return merged


# ============================================================
# 메인 워크플로우 (SageMaker 노트북에서 실행)
# ============================================================
def prepare_training_data(
    chexmask_csv_path,
    split_csv_path,
    output_base_dir,
    target_size=512,
    quality_threshold=0.7,
    format='npz'
):
    """
    전체 전처리 파이프라인

    SageMaker 노트북에서 실행:
        prepare_training_data(
            chexmask_csv_path='/home/ec2-user/SageMaker/data/MIMIC-CXR-JPG.csv',
            split_csv_path='/home/ec2-user/SageMaker/data/mimic-cxr-2.0.0-split.csv',
            output_base_dir='/home/ec2-user/SageMaker/data/unet_masks',
            target_size=512,
        )
    """
    print("=" * 60)
    print("U-Net 학습 데이터 준비")
    print("=" * 60)

    # 1. CSV 로드 + 품질 필터
    df = load_chexmask_csv(chexmask_csv_path, quality_threshold)

    # 2. p10 서브셋 필터
    df = filter_p10_subset(df)

    # 3. Split 정보 병합
    df = merge_with_split(df, split_csv_path)

    # 4. Split별로 마스크 저장
    for split_name in ['train', 'validate', 'test']:
        split_df = df[df['split'] == split_name]
        if len(split_df) == 0:
            print(f"\n[{split_name}] 데이터 없음, 스킵")
            continue

        output_dir = os.path.join(output_base_dir, split_name)
        print(f"\n{'='*40}")
        print(f"[{split_name}] {len(split_df):,}개 처리 중...")
        print(f"저장 경로: {output_dir}")

        if format == 'npz':
            save_masks_as_npz(split_df, output_dir, target_size)
        else:
            save_masks_as_png(split_df, output_dir, target_size)

    print(f"\n{'='*60}")
    print("전처리 완료!")
    print(f"출력 디렉토리: {output_base_dir}")
    print("다음 단계: train_unet.py로 학습 시작")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='CheXmask 전처리')
    parser.add_argument('--csv', required=True, help='CheXmask CSV 경로')
    parser.add_argument('--split', required=True, help='MIMIC-CXR split CSV 경로')
    parser.add_argument('--output', required=True, help='출력 디렉토리')
    parser.add_argument('--size', type=int, default=512, help='마스크 해상도 (기본 512)')
    parser.add_argument('--quality', type=float, default=0.7, help='최소 Dice RCA Mean')
    parser.add_argument('--format', choices=['npz', 'png'], default='npz')

    args = parser.parse_args()
    prepare_training_data(
        args.csv, args.split, args.output,
        target_size=args.size,
        quality_threshold=args.quality,
        format=args.format,
    )
