"""
YOLOv8s 14-Class Chest X-Ray Detection — Multi-GPU SageMaker 학습 스크립트

ml.g5.12xlarge (A10G x4, 48 vCPU, 192GB RAM) 최적화.
- Ultralytics DDP (device=[0,1,2,3])
- 배치 64 (GPU당 16), 의료 영상 특화 augmentation
- EFA/NCCL/OMP 환경변수 사전 설정 (DenseNet train_multigpu.py 패턴)
- Spot 체크포인트 자동 복구
"""

import argparse
import os
import sys
import json
import time
import shutil
import glob

# ============================================================
# 환경변수 — 반드시 torch import 전에 설정
# ============================================================
os.environ['FI_EFA_FORK_SAFE'] = '1'
os.environ['RDMAV_FORK_SAFE'] = '1'
os.environ['NCCL_IB_DISABLE'] = '1'
os.environ['NCCL_ASYNC_ERROR_HANDLING'] = '1'
os.environ['TORCH_NCCL_ASYNC_ERROR_HANDLING'] = '1'
os.environ['NCCL_SOCKET_IFNAME'] = 'eth0'
os.environ['NCCL_DEBUG'] = 'WARN'
os.environ['OMP_NUM_THREADS'] = '4'

import torch

# ============================================================
# SageMaker 경로
# ============================================================
SM_MODEL_DIR = os.environ.get('SM_MODEL_DIR', '/opt/ml/model')
SM_OUTPUT_DATA_DIR = os.environ.get('SM_OUTPUT_DATA_DIR', '/opt/ml/output/data')
CHECKPOINT_DIR = '/opt/ml/checkpoints'
DATA_DIR = '/opt/ml/input/data/training'
# 스크립트가 위치한 디렉토리 (tar.gz 추출 위치)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--epochs', type=int, default=100)
    p.add_argument('--batch-size', type=int, default=64)
    p.add_argument('--imgsz', type=int, default=1024)
    p.add_argument('--model', type=str, default='yolov8s.pt')
    p.add_argument('--patience', type=int, default=20)
    p.add_argument('--lr0', type=float, default=0.01)
    p.add_argument('--lrf', type=float, default=0.01)
    p.add_argument('--workers', type=int, default=16)
    return p.parse_args()


def find_model_path(model_name):
    """yolov8s.pt를 여러 경로에서 검색"""
    candidates = [
        os.path.join(SCRIPT_DIR, model_name),           # 스크립트 옆
        os.path.join(os.getcwd(), model_name),           # 현재 디렉토리
        os.path.join('/opt/ml/code', model_name),        # SageMaker 기본 코드 경로
        os.path.join('/tmp', model_name),                # /tmp
    ]
    for p in candidates:
        if os.path.exists(p):
            print(f'[MODEL] 발견: {p}')
            return p

    # 재귀 검색
    for root in [SCRIPT_DIR, '/opt/ml/code', '/opt/ml']:
        for pt in glob.glob(f'{root}/**/{model_name}', recursive=True):
            print(f'[MODEL] 발견 (검색): {pt}')
            return pt

    # 디버그: 파일 시스템 상태 출력
    print(f'[ERROR] {model_name} 찾을 수 없음!')
    print(f'  CWD: {os.getcwd()}')
    print(f'  SCRIPT_DIR: {SCRIPT_DIR}')
    print(f'  SCRIPT_DIR 내용: {os.listdir(SCRIPT_DIR)}')
    if os.path.isdir('/opt/ml/code'):
        print(f'  /opt/ml/code 내용: {os.listdir("/opt/ml/code")}')
    return None


def find_latest_checkpoint():
    """Spot 중단 후 재시작 시 마지막 체크포인트 찾기"""
    for pt_name in ['yolov8_best.pt', 'best.pt', 'last.pt']:
        pt_path = os.path.join(CHECKPOINT_DIR, pt_name)
        if os.path.exists(pt_path):
            print(f'[CHECKPOINT] 복구: {pt_path}')
            return pt_path

    for pattern in ['**/last.pt', '**/best.pt']:
        for pt in glob.glob(os.path.join(CHECKPOINT_DIR, pattern), recursive=True):
            print(f'[CHECKPOINT] 복구: {pt}')
            return pt

    return None


def save_checkpoint(trainer):
    """Ultralytics 학습 결과를 체크포인트로 저장 (Spot 복구용)"""
    os.makedirs(CHECKPOINT_DIR, exist_ok=True)

    for attr, dst_name in [('best', 'yolov8_best.pt'), ('last', 'last.pt')]:
        src = getattr(trainer, attr, None)
        if src and os.path.exists(str(src)):
            dst = os.path.join(CHECKPOINT_DIR, dst_name)
            shutil.copy2(str(src), dst)
            print(f'[CHECKPOINT] {attr} → {dst}')


def main():
    args = parse_args()
    start = time.time()

    # 디버그 정보
    print(f'[INFO] CWD: {os.getcwd()}')
    print(f'[INFO] SCRIPT_DIR: {SCRIPT_DIR}')
    print(f'[INFO] Python: {sys.version}')
    print(f'[INFO] PyTorch: {torch.__version__}')
    print(f'[INFO] CUDA: {torch.version.cuda}')

    # GPU 확인
    n_gpu = torch.cuda.device_count()
    print(f'[INFO] GPU: {n_gpu}개')
    for i in range(n_gpu):
        props = torch.cuda.get_device_properties(i)
        print(f'  [{i}] {props.name} ({props.total_memory / 1e9:.1f}GB)')

    # Ultralytics import
    from ultralytics import YOLO
    import ultralytics
    print(f'[INFO] Ultralytics: {ultralytics.__version__}')

    # data.yaml 확인
    data_yaml = os.path.join(DATA_DIR, 'data.yaml')
    if not os.path.exists(data_yaml):
        print(f'[ERROR] {data_yaml} 없음!')
        if os.path.isdir(DATA_DIR):
            print(f'  DATA_DIR 내용: {os.listdir(DATA_DIR)}')
        sys.exit(1)

    print(f'\n[DATA] {data_yaml}')
    with open(data_yaml) as f:
        print(f.read())

    for split in ['train', 'val']:
        img_dir = os.path.join(DATA_DIR, 'images', split)
        if os.path.isdir(img_dir):
            print(f'  {split}: {len(os.listdir(img_dir)):,}장')

    # 모델 로드
    resume_ckpt = find_latest_checkpoint()
    if resume_ckpt:
        print(f'\n[MODEL] 체크포인트에서 재개: {resume_ckpt}')
        model = YOLO(resume_ckpt)
        resume = True
    else:
        model_path = find_model_path(args.model)
        if model_path is None:
            print(f'[FATAL] 모델 파일을 찾을 수 없어 종료합니다.')
            sys.exit(1)
        print(f'\n[MODEL] {model_path} (COCO pretrained → fine-tune)')
        model = YOLO(model_path)
        resume = False

    # 디바이스 설정
    if n_gpu > 1:
        device = list(range(n_gpu))
        print(f'[MULTI-GPU] DDP mode: device={device}')
    else:
        device = 0

    # 학습 파라미터
    print(f'\n{"="*60}')
    print(f'YOLOv8 학습 시작')
    print(f'  Epochs: {args.epochs}')
    print(f'  Batch: {args.batch_size} (GPU당 {args.batch_size // max(n_gpu, 1)})')
    print(f'  ImgSz: {args.imgsz}')
    print(f'  Patience: {args.patience}')
    print(f'  LR: {args.lr0} → {args.lrf}')
    print(f'  Workers: {args.workers}')
    print(f'  Resume: {resume}')
    print(f'{"="*60}\n')

    # 학습 설정
    train_kwargs = dict(
        data=data_yaml,
        epochs=args.epochs,
        batch=args.batch_size,
        imgsz=args.imgsz,
        device=device,
        workers=args.workers,
        patience=args.patience,
        resume=resume,
        lr0=args.lr0,
        lrf=args.lrf,
        # 의료 영상 augmentation
        hsv_h=0.0,
        hsv_s=0.0,
        hsv_v=0.1,
        degrees=10.0,
        translate=0.1,
        scale=0.2,
        fliplr=0.5,
        flipud=0.0,
        mosaic=0.0,
        mixup=0.0,
        copy_paste=0.0,
        # 출력
        project=SM_OUTPUT_DATA_DIR,
        name='yolov8_vindr',
        exist_ok=True,
        save=True,
        save_period=10,
        plots=True,
        verbose=True,
    )

    results = model.train(**train_kwargs)

    # 체크포인트 저장
    save_checkpoint(model.trainer)

    # 최종 모델 → SM_MODEL_DIR
    os.makedirs(SM_MODEL_DIR, exist_ok=True)

    for attr in ['best', 'last']:
        src = getattr(model.trainer, attr, None)
        if src and os.path.exists(str(src)):
            dst = os.path.join(SM_MODEL_DIR, f'yolov8_vindr_{attr}.pt')
            shutil.copy2(str(src), dst)
            print(f'\n[MODEL] {attr} → {dst}')
            break

    # 학습 결과 복사
    results_dir = os.path.join(SM_OUTPUT_DATA_DIR, 'yolov8_vindr')
    if os.path.isdir(results_dir):
        for f in glob.glob(os.path.join(results_dir, '*.*')):
            shutil.copy2(f, SM_MODEL_DIR)

    elapsed = time.time() - start
    print(f'\n{"="*60}')
    print(f'학습 완료! ({elapsed/3600:.1f}시간)')
    print(f'  모델: {SM_MODEL_DIR}/')
    print(f'  결과: {results_dir}/')
    print(f'{"="*60}')


if __name__ == '__main__':
    main()
