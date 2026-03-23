"""
02. Grad-CAM++ 시각화
DenseNet-121이 흉부 X-Ray에서 어느 부분을 보고 질환을 판단했는지 히트맵으로 시각화

=== Grad-CAM++ 원리 ===
1. 이미지를 모델에 통과시킴 (Forward pass)
2. 특정 질환(예: Pleural Effusion)에 대한 출력값을 역전파 (Backward pass)
3. 마지막 합성곱 층(DenseNet-121의 features.denseblock4)의 gradient를 추출
4. Gradient의 2차, 3차 도함수를 이용해 pixel-wise 가중치 계산 (Grad-CAM++의 핵심)
   - 기존 Grad-CAM: gradient의 전역 평균만 사용 → 큰 영역만 강조
   - Grad-CAM++: pixel별 중요도 가중치 → 작은 병변도 정확히 포착
5. 가중치 × feature map → ReLU → 히트맵 생성
6. 히트맵을 원본 이미지에 오버레이

=== 파이프라인에서의 역할 ===
DenseNet-121 (질환 분류) → [Grad-CAM++ 히트맵] → PubMedBERT RAG → Bedrock 소견서
                              ↑ 지금 여기
히트맵의 위치 정보가 "좌측 하폐야에 경화 소견" 같은 텍스트 생성의 근거가 됨
"""

# ============================================================
# 1. 환경 설정
# ============================================================
import os
import io
import json
import tarfile
import numpy as np
import pandas as pd
from datetime import datetime

import torch
import torch.nn as nn
from torchvision import models, transforms
from PIL import Image
import matplotlib.pyplot as plt
import matplotlib.cm as cm

# pytorch-grad-cam 라이브러리 (없으면 설치)
try:
    from pytorch_grad_cam import GradCAMPlusPlus
    from pytorch_grad_cam.utils.image import show_cam_on_image
    print("pytorch-grad-cam 로드 완료")
except ImportError:
    print("pytorch-grad-cam 설치 중...")
    import subprocess
    subprocess.check_call(['pip', 'install', 'grad-cam', '-q'])
    from pytorch_grad_cam import GradCAMPlusPlus
    from pytorch_grad_cam.utils.image import show_cam_on_image
    print("pytorch-grad-cam 설치 & 로드 완료")


class MultiLabelTarget:
    """
    멀티레이블 분류에서 Grad-CAM++ 타겟
    모델 출력 (1, 14) 중 특정 질환 인덱스의 값을 스칼라로 반환
    → backward()가 이 스칼라에 대해 gradient를 계산
    """
    def __init__(self, category):
        self.category = category
    def __call__(self, model_output):
        if len(model_output.shape) == 1:
            return model_output[self.category]
        return model_output[:, self.category].sum()

import boto3

# ============================================================
# 2. 설정값
# ============================================================
S3_BUCKET = "pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an"
TRAINING_JOB_NAME = "densenet121-mimic-cxr-v1"

# 모델 아티팩트 경로 (Training Job 완료 후 자동 생성됨)
MODEL_S3_KEY = f"output/{TRAINING_JOB_NAME}/output/model.tar.gz"

# CSV 경로
CSV_S3_KEY = "preprocessing/p10_train_ready_resplit.csv"

# 이미지 경로 prefix
IMAGE_S3_PREFIX = "data/p10_pa"

# 14개 질환 라벨
LABEL_COLS = [
    'Atelectasis', 'Cardiomegaly', 'Consolidation', 'Edema',
    'Enlarged Cardiomediastinum', 'Fracture', 'Lung Lesion', 'Lung Opacity',
    'No Finding', 'Pleural Effusion', 'Pleural Other', 'Pneumonia',
    'Pneumothorax', 'Support Devices'
]
NUM_CLASSES = 14

# 시각화할 테스트 이미지 수
NUM_VISUALIZE = 10

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print(f"Device: {device}")

# ============================================================
# 3. 모델 로드 (S3에서 다운로드)
# ============================================================
print("\n모델 다운로드 중...")
s3 = boto3.client('s3')

# model.tar.gz 다운로드 & 압축 해제
s3.download_file(S3_BUCKET, MODEL_S3_KEY, '/tmp/model.tar.gz')
with tarfile.open('/tmp/model.tar.gz', 'r:gz') as tar:
    tar.extractall('/tmp/model')

print("압축 해제 완료:", os.listdir('/tmp/model'))

# results.json 확인 (학습 결과 요약)
results_path = '/tmp/model/results.json'
if os.path.exists(results_path):
    with open(results_path) as f:
        results = json.load(f)
    print(f"\n학습 결과:")
    print(f"  Test Loss: {results['test_loss']:.4f}")
    print(f"  Mean AUROC: {results['mean_auroc']:.4f}")
    print(f"  학습 시간: {results['training_time_minutes']:.1f}분")

# DenseNet-121 모델 구성 & 가중치 로드
model = models.densenet121(weights=None)
model.classifier = nn.Linear(model.classifier.in_features, NUM_CLASSES)
model.load_state_dict(torch.load('/tmp/model/best_model.pth', map_location=device))
model = model.to(device)
model.eval()
print("\n모델 로드 완료!")

# ============================================================
# 4. Grad-CAM++ 설정
# ============================================================
"""
DenseNet-121 구조:
  model.features
    ├── conv0, norm0, relu0, pool0   (초기 합성곱)
    ├── denseblock1 (6 layers)
    ├── transition1
    ├── denseblock2 (12 layers)
    ├── transition2
    ├── denseblock3 (24 layers)
    ├── transition3
    └── denseblock4 (16 layers)       ← Grad-CAM++ 타겟 레이어
  model.classifier (1024 → 14)

norm5를 타겟으로 선택하는 이유:
- denseblock4 바로 뒤의 BatchNorm 레이어
- 가장 고수준(high-level)의 특징 + 최적의 공간 해상도(7×7) 균형
- 의료 영상 논문에서 DenseNet-121의 표준 Grad-CAM 타겟 레이어
- denseblock4보다 norm5가 더 안정적인 gradient를 제공
"""
target_layer = model.features.norm5

# Grad-CAM++ 객체 생성
cam = GradCAMPlusPlus(
    model=model,
    target_layers=[target_layer],
)
print("Grad-CAM++ 초기화 완료 (target: features.norm5)")

# ============================================================
# 5. 테스트 이미지 로드
# ============================================================
# CSV 다운로드
s3.download_file(S3_BUCKET, CSV_S3_KEY, '/tmp/p10_train_ready_resplit.csv')
df = pd.read_csv('/tmp/p10_train_ready_resplit.csv')

# 테스트셋에서 양성 라벨이 있는 이미지 우선 선택 (시각화에 의미 있는 것)
test_df = df[df['split'] == 'test'].copy()
test_df['positive_count'] = test_df[LABEL_COLS].sum(axis=1)
test_df = test_df.sort_values('positive_count', ascending=False)

# 상위 N개 선택
viz_df = test_df.head(NUM_VISUALIZE)
print(f"\n시각화 대상: {len(viz_df)}개 이미지 (양성 라벨이 많은 순)")

# ============================================================
# 6. 전처리 함수
# ============================================================
# 모델 추론용 전처리 (ImageNet 정규화)
inference_transform = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
])


def load_image_from_s3(s3_client, bucket, image_path):
    """S3에서 이미지를 로드하여 (원본 PIL, 정규화된 텐서) 반환"""
    s3_key = f"{IMAGE_S3_PREFIX}/{image_path}"
    response = s3_client.get_object(Bucket=bucket, Key=s3_key)
    img_bytes = response['Body'].read()
    image = Image.open(io.BytesIO(img_bytes)).convert('RGB')

    # 원본 (시각화용) — 0~1 범위 numpy array
    original_resized = image.resize((224, 224))
    original_np = np.array(original_resized).astype(np.float32) / 255.0

    # 모델 입력용 텐서
    input_tensor = inference_transform(image).unsqueeze(0)

    return original_np, input_tensor


# ============================================================
# 7. Grad-CAM++ 시각화 생성
# ============================================================
def visualize_gradcam(model, cam, image_np, input_tensor, true_labels, label_cols,
                      save_path=None):
    """
    하나의 이미지에 대해 Grad-CAM++ 히트맵 생성

    Parameters:
        image_np: 원본 이미지 (224x224, 0~1 범위)
        input_tensor: 모델 입력 텐서 (1, 3, 224, 224)
        true_labels: 실제 라벨 dict {질환명: 0 or 1}
        save_path: 저장 경로 (None이면 화면 출력)
    """
    input_tensor = input_tensor.to(device)

    # 모델 예측
    with torch.no_grad():
        output = model(input_tensor)
        probs = torch.sigmoid(output).cpu().numpy()[0]

    # 양성 예측 질환 (확률 > 0.5) + 실제 양성 질환
    positive_preds = [(i, label_cols[i], probs[i])
                      for i in range(len(label_cols)) if probs[i] > 0.5]
    positive_trues = [label_cols[i]
                      for i in range(len(label_cols)) if true_labels[label_cols[i]] == 1]

    # 시각화할 질환 선택: 실제 양성 + 예측 양성 합집합 (최대 6개)
    viz_diseases = set()
    for name in positive_trues:
        viz_diseases.add(name)
    for _, name, _ in sorted(positive_preds, key=lambda x: -x[2]):
        viz_diseases.add(name)
    viz_diseases = list(viz_diseases)[:6]

    if not viz_diseases:
        # 양성이 없으면 가장 높은 확률 3개
        top3 = sorted(range(len(probs)), key=lambda i: -probs[i])[:3]
        viz_diseases = [label_cols[i] for i in top3]

    # 서브플롯 구성: 원본 + 각 질환별 히트맵
    n_cols = len(viz_diseases) + 1
    fig, axes = plt.subplots(1, n_cols, figsize=(4 * n_cols, 4))

    # 원본 이미지
    axes[0].imshow(image_np)
    axes[0].set_title("Original", fontsize=11, fontweight='bold')
    # 실제 라벨 표시
    true_text = "\n".join([f"✓ {d}" for d in positive_trues]) if positive_trues else "No Finding"
    axes[0].text(5, 210, true_text, fontsize=7, color='lime',
                 bbox=dict(boxstyle='round', facecolor='black', alpha=0.7))
    axes[0].axis('off')

    # 각 질환별 Grad-CAM++ 히트맵
    for idx, disease_name in enumerate(viz_diseases):
        disease_idx = label_cols.index(disease_name)

        # Grad-CAM++ 계산
        targets = [MultiLabelTarget(disease_idx)]
        grayscale_cam = cam(input_tensor=input_tensor, targets=targets)
        grayscale_cam = grayscale_cam[0, :]  # (224, 224)

        # 히트맵 오버레이
        visualization = show_cam_on_image(image_np, grayscale_cam, use_rgb=True)

        ax = axes[idx + 1]
        ax.imshow(visualization)

        # 제목: 질환명 + 예측 확률 + 실제 라벨
        prob = probs[disease_idx]
        is_true = true_labels[disease_name] == 1
        color = 'green' if is_true else 'red'
        marker = "●" if is_true else "○"
        ax.set_title(f"{marker} {disease_name}\nP={prob:.2f}",
                     fontsize=10, color=color, fontweight='bold')
        ax.axis('off')

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"  저장: {save_path}")
    else:
        plt.show()

    return probs


# ============================================================
# 8. 전체 테스트 이미지 배치 처리
# ============================================================
print("\n" + "=" * 60)
print("Grad-CAM++ 시각화 시작")
print("=" * 60)

output_dir = '/tmp/gradcam_results'
os.makedirs(output_dir, exist_ok=True)

all_results = []

for i, (_, row) in enumerate(viz_df.iterrows()):
    print(f"\n[{i+1}/{len(viz_df)}] {row['image_path']}")

    # 이미지 로드
    original_np, input_tensor = load_image_from_s3(s3, S3_BUCKET, row['image_path'])

    # 실제 라벨
    true_labels = {col: int(row[col]) for col in LABEL_COLS}
    positive_diseases = [col for col, val in true_labels.items() if val == 1]
    print(f"  실제 양성: {positive_diseases if positive_diseases else ['No Finding']}")

    # Grad-CAM++ 시각화
    save_path = os.path.join(output_dir, f"gradcam_{i+1:02d}.png")
    probs = visualize_gradcam(
        model, cam, original_np, input_tensor, true_labels, LABEL_COLS,
        save_path=save_path
    )

    # 결과 기록
    result = {
        'image_path': row['image_path'],
        'true_labels': positive_diseases,
        'predictions': {LABEL_COLS[j]: float(probs[j]) for j in range(NUM_CLASSES)}
    }
    all_results.append(result)

# ============================================================
# 9. 결과 저장 & S3 업로드
# ============================================================
# 결과 JSON 저장
results_json_path = os.path.join(output_dir, 'gradcam_results.json')
with open(results_json_path, 'w', encoding='utf-8') as f:
    json.dump(all_results, f, indent=2, ensure_ascii=False)

# S3 업로드
print("\n" + "=" * 60)
print("결과 S3 업로드 중...")
print("=" * 60)

s3_output_prefix = f"output/{TRAINING_JOB_NAME}/gradcam"
for filename in os.listdir(output_dir):
    local_path = os.path.join(output_dir, filename)
    s3_key = f"{s3_output_prefix}/{filename}"
    s3.upload_file(local_path, S3_BUCKET, s3_key)
    print(f"  업로드: s3://{S3_BUCKET}/{s3_key}")

print(f"\n완료! 총 {len(all_results)}개 이미지 시각화")
print(f"S3 경로: s3://{S3_BUCKET}/{s3_output_prefix}/")

# ============================================================
# 10. 정리
# ============================================================
del model, cam
import gc
gc.collect()
if torch.cuda.is_available():
    torch.cuda.empty_cache()
print("\nGPU 메모리 정리 완료")
