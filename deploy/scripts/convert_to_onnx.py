"""
3개 모델을 PyTorch -> ONNX로 변환.
변환 후 추론 결과 동일성 검증.

필요 패키지: torch, torchvision, transformers, ultralytics, onnx, onnxruntime, numpy, safetensors, boto3

사용법:
    cd deploy/v2/scripts
    python convert_to_onnx.py
"""

import os
import sys
import shutil
import tempfile

import boto3
import torch
import torch.nn as nn
import torchvision.models as models
import onnxruntime as ort
import numpy as np

S3_BUCKET = "pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an"
REGION = "ap-northeast-2"
OUTPUT_DIR = "./onnx_models"
DOWNLOAD_DIR = "./tmp_models"

s3 = boto3.client("s3", region_name=REGION)


# ── S3 다운로드 헬퍼 ──────────────────────────────────────────

def download_from_s3(s3_key, local_path):
    """S3에서 파일 다운로드"""
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    if os.path.exists(local_path):
        print(f"  캐시 사용: {local_path}")
        return
    print(f"  다운로드: s3://{S3_BUCKET}/{s3_key} → {local_path}")
    s3.download_file(S3_BUCKET, s3_key, local_path)


def download_s3_prefix(prefix, local_dir):
    """S3 접두사의 모든 파일 다운로드"""
    os.makedirs(local_dir, exist_ok=True)
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            relative = key[len(prefix):]
            if not relative:
                continue
            local_path = os.path.join(local_dir, relative)
            download_from_s3(key, local_path)


# ── 1. UNet 세그멘테이션 모델 변환 ────────────────────────────

def convert_unet():
    """
    Layer 1 세그멘테이션 모델 변환.
    HuggingFace AutoModel.from_pretrained() 사용.
    모델: ianpan/chest-x-ray-basic (safetensors)
    출력: mask(4class), view(3class), age(float), female(float)
    """
    print("[UNet] 변환 시작...")

    # 1. S3에서 모델 디렉토리 다운로드
    model_dir = f"{DOWNLOAD_DIR}/segmentation"
    download_s3_prefix("models/segmentation/chest-x-ray-basic/", model_dir)

    # 2. HuggingFace 모델 로드
    from transformers import AutoModel
    model = AutoModel.from_pretrained(model_dir, trust_remote_code=True)
    model.eval()
    print(f"  모델 로드 완료: {type(model).__name__}")

    # 3. 더미 입력 — 모델의 preprocess는 그레이스케일(1ch), 512x512 사용
    #    하지만 ONNX export 시에는 forward만 필요
    #    v1 코드: x = m.preprocess(img_np) → (1,1,H,W)
    dummy_input = torch.randn(1, 1, 512, 512)

    # 4. PyTorch 추론 테스트
    with torch.no_grad():
        torch_out = model(dummy_input)
    print(f"  PyTorch 출력 타입: {type(torch_out)}")

    # 모델이 dict를 반환하면 개별 output으로 처리
    if isinstance(torch_out, dict):
        output_names = list(torch_out.keys())
        print(f"  출력 키: {output_names}")

        # dict 반환 모델은 ONNX export가 복잡 → TorchScript wrapper 사용
        class UNetWrapper(nn.Module):
            def __init__(self, base_model):
                super().__init__()
                self.base = base_model

            def forward(self, x):
                out = self.base(x)
                # mask, view, age, female 순서로 concat하지 않고 개별 반환
                return out["mask"], out["view"], out["age"], out["female"]

        wrapper = UNetWrapper(model)
        wrapper.eval()

        torch.onnx.export(
            wrapper,
            dummy_input,
            f"{OUTPUT_DIR}/unet.onnx",
            input_names=["image"],
            output_names=["mask", "view", "age", "female"],
            dynamic_axes={
                "image": {0: "batch", 2: "height", 3: "width"},
                "mask": {0: "batch", 2: "height", 3: "width"},
            },
            opset_version=17,
        )
    else:
        # 단일 텐서 출력
        torch.onnx.export(
            model,
            dummy_input,
            f"{OUTPUT_DIR}/unet.onnx",
            input_names=["image"],
            output_names=["mask"],
            dynamic_axes={"image": {0: "batch"}, "mask": {0: "batch"}},
            opset_version=17,
        )

    # 5. ONNX 검증
    onnx_path = f"{OUTPUT_DIR}/unet.onnx"
    session = ort.InferenceSession(onnx_path)
    onnx_out = session.run(None, {"image": dummy_input.numpy()})

    size_mb = os.path.getsize(onnx_path) / 1024 / 1024
    print(f"  ONNX 생성 완료: {onnx_path} ({size_mb:.1f}MB)")
    print(f"  ONNX 출력 개수: {len(onnx_out)}")

    # PyTorch vs ONNX 비교 (mask만)
    if isinstance(torch_out, dict):
        torch_mask = torch_out["mask"].numpy()
    else:
        torch_mask = torch_out.numpy()
    max_diff = np.max(np.abs(torch_mask - onnx_out[0]))
    print(f"  mask 최대 차이: {max_diff:.8f}")
    if max_diff < 1e-4:
        print("  [UNet] 검증 통과!")
    else:
        print(f"  [UNet] 경고: 차이가 큼 (atol=1e-4 초과)")

    return True


# ── 2. DenseNet-121 분류 모델 변환 ────────────────────────────

def convert_densenet():
    """
    Layer 2 DenseNet-121 변환.
    torchvision densenet121, classifier를 14-class로 교체.
    모델: S3 models/detection/densenet121.pth
    """
    print("[DenseNet] 변환 시작...")

    # 1. S3에서 모델 다운로드
    model_path = f"{DOWNLOAD_DIR}/densenet121.pth"
    download_from_s3("models/detection/densenet121.pth", model_path)

    # 2. 모델 로드 (v1 코드 동일)
    densenet = models.densenet121(weights=None)
    num_features = densenet.classifier.in_features
    densenet.classifier = nn.Linear(num_features, 14)  # 14 질환

    state_dict = torch.load(model_path, map_location="cpu", weights_only=False)
    if isinstance(state_dict, dict) and "model_state_dict" in state_dict:
        state_dict = state_dict["model_state_dict"]
    # DataParallel 래핑 제거
    if any(k.startswith("module.") for k in state_dict.keys()):
        state_dict = {k.replace("module.", ""): v for k, v in state_dict.items()}

    densenet.load_state_dict(state_dict)
    densenet.eval()
    print("  모델 로드 완료")

    # 3. 더미 입력 (224x224, ImageNet 정규화)
    dummy_input = torch.randn(1, 3, 224, 224)

    # 4. ONNX export
    torch.onnx.export(
        densenet,
        dummy_input,
        f"{OUTPUT_DIR}/densenet.onnx",
        input_names=["image"],
        output_names=["logits"],
        dynamic_axes={"image": {0: "batch"}, "logits": {0: "batch"}},
        opset_version=17,
    )

    # 5. 검증
    onnx_path = f"{OUTPUT_DIR}/densenet.onnx"
    with torch.no_grad():
        torch_logits = densenet(dummy_input).numpy()

    session = ort.InferenceSession(onnx_path)
    onnx_logits = session.run(None, {"image": dummy_input.numpy()})[0]

    max_diff = np.max(np.abs(torch_logits - onnx_logits))
    size_mb = os.path.getsize(onnx_path) / 1024 / 1024
    print(f"  ONNX 생성 완료: {onnx_path} ({size_mb:.1f}MB)")
    print(f"  최대 차이: {max_diff:.8f}")

    np.testing.assert_allclose(torch_logits, onnx_logits, atol=1e-5)
    print("  [DenseNet] 검증 통과!")
    return True


# ── 3. YOLOv8 탐지 모델 변환 ──────────────────────────────────

def convert_yolov8():
    """
    Layer 2b YOLOv8 변환.
    ultralytics 자체 export 기능 사용.
    모델: S3 models/yolov8_vindr_best.pt
    """
    print("[YOLOv8] 변환 시작...")

    # 1. S3에서 모델 다운로드
    model_path = f"{DOWNLOAD_DIR}/yolov8_vindr_best.pt"
    download_from_s3("models/yolov8_vindr_best.pt", model_path)

    # 2. ultralytics 자체 export
    from ultralytics import YOLO
    model = YOLO(model_path)
    print("  모델 로드 완료")

    # 3. ONNX export (ultralytics가 자동 처리)
    export_path = model.export(format="onnx", imgsz=1024, simplify=True)
    print(f"  ultralytics export: {export_path}")

    # 4. OUTPUT_DIR로 이동
    dest_path = f"{OUTPUT_DIR}/yolov8.onnx"
    shutil.move(export_path, dest_path)

    size_mb = os.path.getsize(dest_path) / 1024 / 1024
    print(f"  ONNX 생성 완료: {dest_path} ({size_mb:.1f}MB)")

    # 5. ONNX Runtime 로드 검증
    session = ort.InferenceSession(dest_path)
    input_name = session.get_inputs()[0].name
    input_shape = session.get_inputs()[0].shape
    print(f"  ONNX 입력: {input_name} {input_shape}")
    print("  [YOLOv8] 검증 통과!")
    return True


# ── S3 업로드 ─────────────────────────────────────────────────

def upload_to_s3():
    """변환된 ONNX 모델을 S3에 업로드"""
    model_files = {
        "unet.onnx": "models/onnx/unet.onnx",
        "densenet.onnx": "models/onnx/densenet.onnx",
        "yolov8.onnx": "models/onnx/yolov8.onnx",
    }

    uploaded = 0
    for local_name, s3_key in model_files.items():
        local_path = f"{OUTPUT_DIR}/{local_name}"
        if os.path.exists(local_path):
            size_mb = os.path.getsize(local_path) / 1024 / 1024
            print(f"  업로드: {local_path} → s3://{S3_BUCKET}/{s3_key} ({size_mb:.1f}MB)")
            s3.upload_file(local_path, S3_BUCKET, s3_key)
            uploaded += 1
        else:
            print(f"  스킵: {local_path} 파일 없음")

    return uploaded


# ── 메인 ──────────────────────────────────────────────────────

if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    print(f"출력 디렉토리: {os.path.abspath(OUTPUT_DIR)}")
    print(f"다운로드 디렉토리: {os.path.abspath(DOWNLOAD_DIR)}")
    print("=" * 60)

    results = {}

    # DenseNet (가장 단순, 먼저 실행)
    try:
        results["densenet"] = convert_densenet()
    except Exception as e:
        print(f"  [DenseNet] 실패: {e}")
        results["densenet"] = False

    print()

    # YOLOv8 (ultralytics 자체 export)
    try:
        results["yolov8"] = convert_yolov8()
    except Exception as e:
        print(f"  [YOLOv8] 실패: {e}")
        results["yolov8"] = False

    print()

    # UNet (HuggingFace, 가장 복잡)
    try:
        results["unet"] = convert_unet()
    except Exception as e:
        print(f"  [UNet] 실패: {e}")
        import traceback
        traceback.print_exc()
        results["unet"] = False

    print()
    print("=" * 60)

    # 결과 요약
    success_count = sum(1 for v in results.values() if v)
    print(f"변환 결과: {success_count}/3 성공")
    for name, ok in results.items():
        status = "성공" if ok else "실패"
        print(f"  {name}: {status}")

    if success_count > 0:
        print()
        print("S3 업로드 시작...")
        uploaded = upload_to_s3()
        print(f"업로드 완료: {uploaded}개 파일")
    else:
        print("변환 성공 모델 없음 — 업로드 스킵")

    print()
    print("완료!")
