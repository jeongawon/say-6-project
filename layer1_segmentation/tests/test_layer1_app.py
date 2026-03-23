"""
Layer 1 Segmentation 테스트 — Gradio 웹 앱
SageMaker 노트북에서 실행: python test_layer1_app.py

pip install gradio 필요
"""
import os
import io
import json
import numpy as np
import torch
import boto3
import gradio as gr
from PIL import Image
from transformers import AutoModel

# ============================================================
# 설정
# ============================================================
WORK_BUCKET = 'pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an'
MODEL_S3_PREFIX = 'models/segmentation/chest-x-ray-basic'
SAMPLE_S3_PREFIX = 'web/test-layer1/samples'
MODEL_LOCAL = '/tmp/chest-x-ray-basic'
SAMPLE_LOCAL = '/tmp/cxr_samples'

s3 = boto3.client('s3', region_name='ap-northeast-2')
model = None


# ============================================================
# 모델 로드
# ============================================================
def load_model():
    global model
    if model is not None:
        return model

    # S3에서 다운로드
    if not os.path.exists(os.path.join(MODEL_LOCAL, 'config.json')):
        os.makedirs(MODEL_LOCAL, exist_ok=True)
        print('모델 S3에서 다운로드 중...')
        paginator = s3.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=WORK_BUCKET, Prefix=MODEL_S3_PREFIX):
            for obj in page.get('Contents', []):
                rel = obj['Key'][len(MODEL_S3_PREFIX) + 1:]
                if not rel:
                    continue
                local_path = os.path.join(MODEL_LOCAL, rel)
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                s3.download_file(WORK_BUCKET, obj['Key'], local_path)
        print('다운로드 완료')

    model = AutoModel.from_pretrained(MODEL_LOCAL, trust_remote_code=True)
    model.eval()
    print('모델 로드 완료')
    return model


# ============================================================
# 샘플 이미지 다운로드
# ============================================================
def download_samples():
    os.makedirs(SAMPLE_LOCAL, exist_ok=True)
    samples = []

    # samples.json 로드
    try:
        resp = s3.get_object(Bucket=WORK_BUCKET, Key=f'{SAMPLE_S3_PREFIX}/samples.json')
        sample_info = json.loads(resp['Body'].read())
    except Exception:
        sample_info = [{'filename': f'sample_{i}.jpg', 'labels': []} for i in range(1, 6)]

    for info in sample_info:
        local_path = os.path.join(SAMPLE_LOCAL, info['filename'])
        if not os.path.exists(local_path):
            try:
                s3.download_file(
                    WORK_BUCKET,
                    f'{SAMPLE_S3_PREFIX}/{info["filename"]}',
                    local_path
                )
            except Exception as e:
                print(f'  {info["filename"]} 다운로드 실패: {e}')
                continue

        label_text = ', '.join(info.get('labels', ['Unknown']))
        samples.append((local_path, label_text))

    return samples


# ============================================================
# 추론 함수
# ============================================================
def max_horizontal_width(binary_mask):
    if not binary_mask.any():
        return 0
    rows = binary_mask.any(axis=1)
    mw = 0
    for r in np.where(rows)[0]:
        cols = np.where(binary_mask[r])[0]
        mw = max(mw, cols[-1] - cols[0] + 1)
    return mw


def run_segmentation(input_image):
    """Gradio에서 호출되는 메인 추론 함수"""
    if input_image is None:
        return None, "이미지를 선택하세요"

    m = load_model()

    # PIL Image로 변환
    if isinstance(input_image, np.ndarray):
        img = Image.fromarray(input_image)
    else:
        img = input_image

    # Grayscale 변환 + 추론
    img_gray = np.array(img.convert('L'))
    original_size = img_gray.shape[:2]

    x = m.preprocess(img_gray)
    x = torch.from_numpy(x).unsqueeze(0).unsqueeze(0).float()

    with torch.inference_mode():
        out = m(x)

    # 마스크
    mask = out['mask'].argmax(dim=1).squeeze(0).cpu().numpy()
    if mask.shape != original_size:
        mask = np.array(
            Image.fromarray(mask.astype(np.uint8)).resize(
                (original_size[1], original_size[0]), Image.NEAREST
            )
        )

    # 측정값 계산
    right_lung = (mask == 1)
    left_lung = (mask == 2)
    heart = (mask == 3)
    thorax = right_lung | left_lung | heart

    hw = max_horizontal_width(heart)
    tw = max_horizontal_width(thorax)
    ctr = hw / tw if tw > 0 else 0.0

    rl_area = int(right_lung.sum())
    ll_area = int(left_lung.sum())
    h_area = int(heart.sum())

    if ctr >= 0.60:
        ctr_status = "Severe Cardiomegaly"
    elif ctr >= 0.50:
        ctr_status = "Cardiomegaly"
    else:
        ctr_status = "Normal"

    lung_ratio = ll_area / rl_area if rl_area > 0 else 0.0

    # View / Age / Sex
    view_idx = out['view'].argmax(dim=-1).item()
    view = {0: 'AP', 1: 'PA', 2: 'lateral'}.get(view_idx, '?')
    age = out['age'].item()
    sex = 'F' if out['female'].item() >= 0.5 else 'M'

    # 오버레이 이미지 생성
    img_rgb = np.array(img.convert('RGB'))
    overlay = img_rgb.copy().astype(np.float32)

    # 반투명 마스크 오버레이
    alpha = 0.35
    overlay[right_lung] = overlay[right_lung] * (1 - alpha) + np.array([41, 128, 185]) * alpha
    overlay[left_lung] = overlay[left_lung] * (1 - alpha) + np.array([39, 174, 96]) * alpha
    overlay[heart] = overlay[heart] * (1 - alpha) + np.array([231, 76, 60]) * alpha

    # 경계선 추가
    from scipy import ndimage
    for m_bin, color in [(right_lung, [41, 128, 185]), (left_lung, [39, 174, 96]), (heart, [231, 76, 60])]:
        if m_bin.any():
            edges = ndimage.binary_dilation(m_bin, iterations=1) ^ m_bin
            overlay[edges] = color

    overlay = np.clip(overlay, 0, 255).astype(np.uint8)

    # 결과 텍스트
    result_text = f"""## 분석 결과

### CTR (Cardiothoracic Ratio)
| 항목 | 값 |
|------|-----|
| **CTR** | **{ctr:.4f}** |
| **판정** | **{ctr_status}** |
| 심장 가로폭 | {hw} px |
| 흉곽 가로폭 | {tw} px |

### 뷰 / 환자 예측
| 항목 | 값 |
|------|-----|
| 촬영 방향 | {view} |
| 예측 나이 | {age:.1f}세 |
| 예측 성별 | {'남성(M)' if sex == 'M' else '여성(F)'} |

### 폐 측정
| 항목 | 값 |
|------|-----|
| 우폐 면적 | {rl_area:,} px² |
| 좌폐 면적 | {ll_area:,} px² |
| 심장 면적 | {h_area:,} px² |
| 좌/우 면적비 | {lung_ratio:.4f} |
| 총 폐 면적 | {rl_area + ll_area:,} px² |

---
*범례: 🔵 우폐 / 🟢 좌폐 / 🔴 심장*
"""

    return overlay, result_text


# ============================================================
# Gradio 앱
# ============================================================
def main():
    print('샘플 이미지 다운로드 중...')
    samples = download_samples()
    print(f'  {len(samples)}장 준비 완료')

    print('모델 사전 로드...')
    load_model()

    with gr.Blocks(
        title="Layer 1: Anatomy Segmentation",
        theme=gr.themes.Base(primary_hue="blue", neutral_hue="slate"),
    ) as app:
        gr.Markdown("""
        # Layer 1: Anatomy Segmentation Test
        **모델**: ianpan/chest-x-ray-basic (EfficientNetV2-S + U-Net, CheXmask 33.5만장 학습)

        아래 샘플 이미지를 클릭하거나 직접 업로드하세요.
        """)

        with gr.Row():
            with gr.Column(scale=1):
                input_image = gr.Image(
                    label="CXR 이미지",
                    type="numpy",
                    height=400,
                )

                # 샘플 이미지 갤러리
                if samples:
                    gr.Markdown("### 샘플 이미지 (클릭하여 선택)")
                    gallery = gr.Gallery(
                        value=samples,
                        label="MIMIC-CXR PA 샘플",
                        columns=3,
                        height=200,
                        object_fit="cover",
                    )

                    def on_gallery_select(evt: gr.SelectData):
                        path = samples[evt.index][0]
                        return np.array(Image.open(path).convert('RGB'))

                    gallery.select(on_gallery_select, outputs=input_image)

                analyze_btn = gr.Button("분석하기", variant="primary", size="lg")

            with gr.Column(scale=1):
                output_image = gr.Image(
                    label="세그멘테이션 결과",
                    height=400,
                )
                output_text = gr.Markdown(label="측정값")

        analyze_btn.click(
            fn=run_segmentation,
            inputs=input_image,
            outputs=[output_image, output_text],
        )

        # 이미지 변경 시 자동 분석
        input_image.change(
            fn=run_segmentation,
            inputs=input_image,
            outputs=[output_image, output_text],
        )

    print('\n' + '=' * 60)
    print('Gradio 앱 시작!')
    print('브라우저에서 아래 URL로 접속:')
    print('=' * 60)

    app.launch(
        server_name='0.0.0.0',
        server_port=7860,
        share=False,
    )


if __name__ == '__main__':
    main()
