"""
Layer 2 Detection 테스트 — Gradio 웹 앱
SageMaker 노트북에서 실행: python test_layer2_app.py

pip install gradio 필요

사용법:
  1) 학습 완료 후 model.tar.gz에서 best_model.pth 자동 다운로드
  2) 또는 체크포인트 사용: python test_layer2_app.py --checkpoint
"""
import os
import sys
import json
import argparse
import numpy as np
import torch
import boto3
import gradio as gr
from PIL import Image, ImageDraw, ImageFont

# Layer 2 모듈 import — 여러 경로 시도
_script_dir = os.path.dirname(os.path.abspath(__file__))
for _candidate in [
    _script_dir,                                                    # 프로젝트 루트
    os.path.join(_script_dir, 'layer2_detection', 'densenet'),      # 하위 폴더
]:
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

try:
    from layer2_detection.densenet.detection_model import DetectionModel, LABEL_COLS
except ModuleNotFoundError:
    from detection_model import DetectionModel, LABEL_COLS

# ============================================================
# 설정
# ============================================================
WORK_BUCKET = 'pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an'
IMAGE_BUCKET = 'say1-pre-project-5'

# 모델 경로 (학습 완료 후)
MODEL_S3_OUTPUT = 'output/densenet121-full-pa-v6-multigpu/output/model.tar.gz'
# 체크포인트 경로 (학습 중)
CHECKPOINT_S3_PREFIX = 'checkpoints/densenet121-full-pa-v6-multigpu/'

MODEL_LOCAL = '/tmp/densenet121_model'
SAMPLE_LOCAL = '/tmp/cxr_samples_layer2'

s3 = boto3.client('s3', region_name='ap-northeast-2')
detector = None


# ============================================================
# 모델 로드
# ============================================================
def find_best_model(use_checkpoint=False):
    """S3에서 best_model.pth 찾기 (완료 모델 또는 체크포인트)"""
    os.makedirs(MODEL_LOCAL, exist_ok=True)
    local_pth = os.path.join(MODEL_LOCAL, 'best_model.pth')

    if os.path.exists(local_pth):
        print(f'[Layer 2] 로컬 모델 캐시 사용: {local_pth}')
        return local_pth

    if use_checkpoint:
        # 체크포인트에서 가져오기
        print('[Layer 2] 체크포인트에서 모델 검색 중...')
        try:
            resp = s3.list_objects_v2(
                Bucket=WORK_BUCKET,
                Prefix=CHECKPOINT_S3_PREFIX
            )
            pth_files = [
                obj for obj in resp.get('Contents', [])
                if obj['Key'].endswith('.pth')
            ]
            if pth_files:
                # 가장 최근 체크포인트
                latest = sorted(pth_files, key=lambda x: x['LastModified'])[-1]
                print(f'[Layer 2] 체크포인트 다운로드: {latest["Key"]}')
                s3.download_file(WORK_BUCKET, latest['Key'], local_pth)
                print(f'[Layer 2] 다운로드 완료: {local_pth}')
                return local_pth
            else:
                print('[Layer 2] 체크포인트 없음')
        except Exception as e:
            print(f'[Layer 2] 체크포인트 검색 실패: {e}')
    else:
        # 학습 완료 모델 (model.tar.gz)
        print('[Layer 2] 학습 완료 모델 다운로드 중...')
        tar_local = os.path.join(MODEL_LOCAL, 'model.tar.gz')
        try:
            s3.download_file(WORK_BUCKET, MODEL_S3_OUTPUT, tar_local)
            print(f'[Layer 2] model.tar.gz 다운로드 완료')

            # 압축 해제
            import tarfile
            with tarfile.open(tar_local, 'r:gz') as tar:
                tar.extractall(MODEL_LOCAL)

            # best_model.pth 찾기
            for fname in ['best_model.pth', 'model.pth']:
                candidate = os.path.join(MODEL_LOCAL, fname)
                if os.path.exists(candidate):
                    return candidate

            # .pth 파일 아무거나
            for f in os.listdir(MODEL_LOCAL):
                if f.endswith('.pth'):
                    return os.path.join(MODEL_LOCAL, f)

            raise FileNotFoundError('model.tar.gz에 .pth 파일 없음')
        except Exception as e:
            print(f'[Layer 2] 모델 다운로드 실패: {e}')
            print('[Layer 2] 체크포인트로 폴백...')
            return find_best_model(use_checkpoint=True)

    return None


def load_detector(use_checkpoint=False):
    """DetectionModel 로드"""
    global detector
    if detector is not None and detector.model is not None:
        return detector

    model_path = find_best_model(use_checkpoint)
    if model_path is None:
        raise RuntimeError(
            '모델을 찾을 수 없습니다.\n'
            '학습이 완료되지 않았다면 --checkpoint 옵션을 사용하세요.'
        )

    detector = DetectionModel(model_path=model_path)
    detector.load()
    return detector


# ============================================================
# 샘플 이미지 (MIMIC-CXR PA test set에서)
# ============================================================
def download_samples():
    """테스트셋 샘플 이미지 다운로드"""
    os.makedirs(SAMPLE_LOCAL, exist_ok=True)
    samples = []

    # samples.json 로드 (미리 업로드 해둔 경우)
    try:
        resp = s3.get_object(
            Bucket=WORK_BUCKET,
            Key='web/test-layer2/samples.json'
        )
        sample_info = json.loads(resp['Body'].read())
    except Exception:
        # 없으면 테스트 CSV에서 몇 장 가져오기
        sample_info = get_test_samples_from_csv()

    for info in sample_info:
        local_path = os.path.join(SAMPLE_LOCAL, info['filename'])
        if not os.path.exists(local_path):
            try:
                s3_key = info.get('s3_key', f'files/{info["filename"]}')
                bucket = info.get('bucket', IMAGE_BUCKET)
                s3.download_file(bucket, s3_key, local_path)
            except Exception as e:
                print(f'  {info["filename"]} 다운로드 실패: {e}')
                continue

        label_text = ', '.join(info.get('labels', []))
        samples.append((local_path, label_text or 'Unknown'))

    return samples


def get_test_samples_from_csv():
    """테스트 CSV에서 샘플 정보 추출 (최대 6장)"""
    try:
        import pandas as pd
        csv_key = 'mimic-cxr-csv/mimic_cxr_pa_final.csv'
        csv_local = '/tmp/mimic_cxr_pa_final.csv'

        if not os.path.exists(csv_local):
            s3.download_file(WORK_BUCKET, csv_key, csv_local)

        df = pd.read_csv(csv_local)
        test_df = df[df['split'] == 'test'].head(6)

        samples = []
        for _, row in test_df.iterrows():
            dicom_id = row['dicom_id']
            subject_id = str(row['subject_id'])
            study_id = str(row['study_id'])

            # MIMIC-CXR S3 경로
            p_prefix = f'p{subject_id[:2]}'
            s3_key = f'files/{p_prefix}/p{subject_id}/s{study_id}/{dicom_id}.jpg'

            # 양성 라벨
            labels = [col for col in LABEL_COLS if col in row and row[col] == 1.0]

            samples.append({
                'filename': f'{dicom_id}.jpg',
                'bucket': IMAGE_BUCKET,
                's3_key': s3_key,
                'labels': labels,
            })

        return samples
    except Exception as e:
        print(f'[Layer 2] 테스트 CSV 로드 실패: {e}')
        return []


# ============================================================
# 추론 함수
# ============================================================
def run_detection(input_image):
    """Gradio에서 호출되는 메인 추론 함수"""
    if input_image is None:
        return None, "이미지를 선택하세요"

    try:
        det = load_detector()
    except RuntimeError as e:
        return None, f"**모델 로드 실패**\n\n{e}"

    # 추론
    if isinstance(input_image, np.ndarray):
        img = Image.fromarray(input_image)
    else:
        img = input_image

    result = det.predict(img)

    # --- 결과 오버레이 이미지 ---
    overlay = create_result_overlay(img, result)

    # --- 결과 텍스트 (마크다운) ---
    result_text = format_result_markdown(result)

    return overlay, result_text


def create_result_overlay(img, result):
    """이미지 위에 탐지 결과 오버레이"""
    img_rgb = img.convert('RGB')
    overlay = img_rgb.copy()
    draw = ImageDraw.Draw(overlay)

    # 상단에 요약 텍스트
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 13)
    except Exception:
        font = ImageFont.load_default()
        font_small = font

    # 배경 박스
    w, h = overlay.size
    box_h = min(h, 30 + len(result['positive_findings']) * 18 + 10)
    draw.rectangle([0, 0, w, box_h], fill=(0, 0, 0, 180))

    # 요약
    summary = result['summary']
    draw.text((10, 5), summary, fill='white', font=font)

    # 양성 질환 나열
    y = 28
    for disease in result['positive_findings']:
        if disease == 'No Finding':
            continue
        prob = result['probabilities'][disease]
        bar_len = int(prob * 100)
        color = (231, 76, 60) if prob >= 0.7 else (243, 156, 18) if prob >= 0.5 else (46, 204, 113)
        text = f"  {disease}: {prob:.1%}"
        draw.text((10, y), text, fill=color, font=font_small)
        y += 18

    return np.array(overlay)


def format_result_markdown(result):
    """결과를 마크다운 테이블로 포맷"""
    # 양성 소견
    pos = result['positive_findings']
    neg = result['negative_findings']
    probs = result['probabilities']

    md = f"## 탐지 결과\n\n"
    md += f"**{result['summary']}**\n\n"

    # 양성 테이블
    if pos and not (len(pos) == 1 and pos[0] == 'No Finding'):
        md += "### 양성 소견 (Positive Findings)\n\n"
        md += "| 질환 | 확률 | 판정 |\n"
        md += "|------|------|------|\n"
        for f in result['findings']:
            if f['positive'] and f['disease'] != 'No Finding':
                p = f['probability']
                severity = "🔴 높음" if p >= 0.7 else "🟡 중간" if p >= 0.5 else "🟢 낮음"
                md += f"| **{f['disease']}** | **{p:.1%}** | {severity} |\n"
        md += "\n"

    # 전체 14개 질환 확률
    md += "### 전체 질환 확률\n\n"
    md += "| 질환 | 확률 | 양성/음성 |\n"
    md += "|------|------|----------|\n"
    for f in result['findings']:
        status = "**양성**" if f['positive'] else "음성"
        p = f['probability']
        bar = "█" * int(p * 20) + "░" * (20 - int(p * 20))
        md += f"| {f['disease']} | {p:.1%} {bar} | {status} |\n"

    md += f"\n---\n"
    md += f"*DenseNet-121 | MIMIC-CXR PA 94K 학습 | threshold: 0.5*\n"

    return md


# ============================================================
# Gradio 앱
# ============================================================
def main():
    parser = argparse.ArgumentParser(description='Layer 2 Detection Test App')
    parser.add_argument('--checkpoint', action='store_true',
                        help='학습 중 체크포인트 사용 (학습 미완료 시)')
    parser.add_argument('--model-path', type=str, default=None,
                        help='로컬 모델 경로 직접 지정')
    parser.add_argument('--port', type=int, default=7861,
                        help='Gradio 포트 (기본 7861, Layer 1은 7860)')
    args = parser.parse_args()

    # 모델 경로 직접 지정 시
    if args.model_path:
        global detector
        detector = DetectionModel(model_path=args.model_path)

    print('=' * 60)
    print(' Layer 2: 14-Disease Detection Test App')
    print('=' * 60)

    # 샘플 이미지 준비
    print('\n[1/3] 샘플 이미지 다운로드 중...')
    try:
        samples = download_samples()
        print(f'  {len(samples)}장 준비 완료')
    except Exception as e:
        print(f'  샘플 다운로드 실패 (직접 업로드 가능): {e}')
        samples = []

    # 모델 로드
    print('\n[2/3] 모델 로드 중...')
    try:
        load_detector(use_checkpoint=args.checkpoint)
        print('  모델 로드 완료!')
    except Exception as e:
        print(f'  모델 로드 실패 (앱 실행 후 수동 로드): {e}')

    # Gradio UI
    print('\n[3/3] Gradio 앱 빌드 중...')

    with gr.Blocks(
        title="Layer 2: 14-Disease Detection",
        theme=gr.themes.Base(primary_hue="red", neutral_hue="slate"),
    ) as app:
        gr.Markdown("""
        # Layer 2: 14-Disease Multi-label Detection Test
        **모델**: DenseNet-121 (ImageNet → MIMIC-CXR PA 94K Fine-tuned)

        14개 CheXpert 질환을 동시 탐지합니다. 아래 샘플 이미지를 클릭하거나 직접 업로드하세요.

        | 질환 목록 |
        |-----------|
        | Atelectasis, Cardiomegaly, Consolidation, Edema, Enlarged Cardiomediastinum |
        | Fracture, Lung Lesion, Lung Opacity, No Finding, Pleural Effusion |
        | Pleural Other, Pneumonia, Pneumothorax, Support Devices |
        """)

        with gr.Row():
            with gr.Column(scale=1):
                input_image = gr.Image(
                    label="CXR 이미지 (흉부 X-Ray)",
                    type="numpy",
                    height=450,
                )

                if samples:
                    gr.Markdown("### 샘플 이미지 (클릭하여 선택)")
                    gallery = gr.Gallery(
                        value=samples,
                        label="MIMIC-CXR PA 테스트 샘플",
                        columns=3,
                        height=200,
                        object_fit="cover",
                    )

                    def on_gallery_select(evt: gr.SelectData):
                        path = samples[evt.index][0]
                        return np.array(Image.open(path).convert('RGB'))

                    gallery.select(on_gallery_select, outputs=input_image)

                analyze_btn = gr.Button(
                    "14-Disease 탐지 실행",
                    variant="primary",
                    size="lg",
                )

            with gr.Column(scale=1):
                output_image = gr.Image(
                    label="탐지 결과 오버레이",
                    height=450,
                )
                output_text = gr.Markdown(label="탐지 결과")

        analyze_btn.click(
            fn=run_detection,
            inputs=input_image,
            outputs=[output_image, output_text],
        )

        input_image.change(
            fn=run_detection,
            inputs=input_image,
            outputs=[output_image, output_text],
        )

        gr.Markdown("""
        ---
        **참고**: threshold 0.5 기준 양성/음성 판정. 임상적 판단은 전문의 검토 필요.
        """)

    print('\n' + '=' * 60)
    print('Gradio 앱 시작!')
    print(f'브라우저에서 http://0.0.0.0:{args.port} 으로 접속')
    print('=' * 60)

    app.launch(
        server_name='0.0.0.0',
        server_port=args.port,
        share=True,
    )


if __name__ == '__main__':
    main()
