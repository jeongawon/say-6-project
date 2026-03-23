"""
Layer 2: 14-Disease Multi-label Detection — DenseNet-121 기반

모델: DenseNet-121 (ImageNet pretrained → MIMIC-CXR PA 94K Fine-tuned)

기능:
  1. 14개 흉부 질환 동시 탐지 (Multi-label)
  2. 질환별 확률(0~1) + 양성/음성 판정
  3. 배치 추론 지원

질환 목록 (CheXpert 14-label):
  Atelectasis, Cardiomegaly, Consolidation, Edema,
  Enlarged Cardiomediastinum, Fracture, Lung Lesion, Lung Opacity,
  No Finding, Pleural Effusion, Pleural Other, Pneumonia,
  Pneumothorax, Support Devices
"""

import os
import numpy as np
import torch
import torch.nn as nn
from torchvision import models, transforms
from PIL import Image


LABEL_COLS = [
    'Atelectasis', 'Cardiomegaly', 'Consolidation', 'Edema',
    'Enlarged Cardiomediastinum', 'Fracture', 'Lung Lesion', 'Lung Opacity',
    'No Finding', 'Pleural Effusion', 'Pleural Other', 'Pneumonia',
    'Pneumothorax', 'Support Devices'
]

# 임상적으로 의미 있는 기본 threshold (질환별 조정 가능)
DEFAULT_THRESHOLDS = {
    'Atelectasis': 0.5,
    'Cardiomegaly': 0.5,
    'Consolidation': 0.5,
    'Edema': 0.5,
    'Enlarged Cardiomediastinum': 0.5,
    'Fracture': 0.5,
    'Lung Lesion': 0.5,
    'Lung Opacity': 0.5,
    'No Finding': 0.5,
    'Pleural Effusion': 0.5,
    'Pleural Other': 0.5,
    'Pneumonia': 0.5,
    'Pneumothorax': 0.5,
    'Support Devices': 0.5,
}


class DetectionModel:
    """DenseNet-121 14-Disease Multi-label 탐지 모델 래퍼"""

    def __init__(self, model_path=None, device=None, thresholds=None):
        """
        Args:
            model_path: best_model.pth 경로 (로컬 파일 또는 S3 URI)
                - 로컬: './best_model.pth'
                - S3:   's3://bucket/output/.../model.tar.gz'
            device: 'cuda' / 'cpu' / None(자동)
            thresholds: 질환별 양성 판정 threshold dict (기본 0.5)
        """
        self.model_path = model_path
        self.device = device or ('cuda' if torch.cuda.is_available() else 'cpu')
        self.thresholds = thresholds or DEFAULT_THRESHOLDS
        self.model = None

        self.transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                 std=[0.229, 0.224, 0.225])
        ])

    def load(self, model_path=None):
        """모델 로드 (최초 1회)"""
        if self.model is not None:
            return

        path = model_path or self.model_path
        if path is None:
            raise ValueError("model_path를 지정해주세요")

        # S3 URI인 경우 다운로드
        if path.startswith('s3://'):
            path = self._download_from_s3(path)

        # model.tar.gz인 경우 압축 해제
        if path.endswith('.tar.gz'):
            path = self._extract_tar_gz(path)

        print(f"[Layer 2] DenseNet-121 모델 로드: {path}")

        # 모델 구조 생성
        model = models.densenet121(weights=None)
        num_features = model.classifier.in_features
        model.classifier = nn.Linear(num_features, len(LABEL_COLS))

        # 가중치 로드
        state_dict = torch.load(path, map_location=self.device, weights_only=False)

        # DataParallel로 저장된 경우 module. 접두사 제거
        if any(k.startswith('module.') for k in state_dict.keys()):
            state_dict = {k.replace('module.', ''): v for k, v in state_dict.items()}

        model.load_state_dict(state_dict)
        model = model.eval().to(self.device)
        self.model = model

        print(f"[Layer 2] 로드 완료 (device: {self.device}, 질환: {len(LABEL_COLS)}개)")

    def predict(self, image_input):
        """
        단일 이미지에서 14개 질환 탐지

        Args:
            image_input: PIL.Image, numpy array (H,W) or (H,W,3), 또는 파일 경로

        Returns:
            dict: {
                'findings': [
                    {'disease': str, 'probability': float, 'positive': bool},
                    ...  (14개)
                ],
                'positive_findings': [str, ...],    # 양성 판정된 질환명 리스트
                'negative_findings': [str, ...],    # 음성 판정된 질환명 리스트
                'probabilities': {str: float, ...}, # 질환별 확률 dict
                'num_positive': int,
                'summary': str,                     # 한줄 요약
            }
        """
        self.load()

        # 입력 → PIL → 텐서
        img = self._to_pil(image_input)
        x = self.transform(img).unsqueeze(0).to(self.device)

        # 추론
        with torch.inference_mode():
            logits = self.model(x)
            probs = torch.sigmoid(logits).squeeze(0).cpu().numpy()

        # 결과 구성
        findings = []
        positive = []
        negative = []
        prob_dict = {}

        for i, disease in enumerate(LABEL_COLS):
            p = float(probs[i])
            is_pos = p >= self.thresholds.get(disease, 0.5)
            findings.append({
                'disease': disease,
                'probability': round(p, 4),
                'positive': is_pos,
            })
            prob_dict[disease] = round(p, 4)
            if is_pos:
                positive.append(disease)
            else:
                negative.append(disease)

        # 양성 확률 높은 순 정렬
        findings.sort(key=lambda x: x['probability'], reverse=True)

        # 요약
        if not positive or (len(positive) == 1 and positive[0] == 'No Finding'):
            summary = "특이 소견 없음 (No significant findings)"
        else:
            real_findings = [f for f in positive if f != 'No Finding']
            summary = f"{len(real_findings)}개 이상 소견: {', '.join(real_findings)}"

        return {
            'findings': findings,
            'positive_findings': positive,
            'negative_findings': negative,
            'probabilities': prob_dict,
            'num_positive': len(positive),
            'summary': summary,
        }

    def predict_batch(self, image_inputs):
        """
        여러 이미지 배치 추론

        Args:
            image_inputs: list of (PIL.Image / numpy / 파일경로)

        Returns:
            list of predict() 결과 dict
        """
        self.load()

        # 전처리
        tensors = []
        for img_input in image_inputs:
            img = self._to_pil(img_input)
            tensors.append(self.transform(img))

        batch = torch.stack(tensors).to(self.device)

        # 배치 추론
        with torch.inference_mode():
            logits = self.model(batch)
            probs_batch = torch.sigmoid(logits).cpu().numpy()

        # 결과 구성
        results = []
        for probs in probs_batch:
            findings = []
            positive = []
            negative = []
            prob_dict = {}

            for i, disease in enumerate(LABEL_COLS):
                p = float(probs[i])
                is_pos = p >= self.thresholds.get(disease, 0.5)
                findings.append({
                    'disease': disease,
                    'probability': round(p, 4),
                    'positive': is_pos,
                })
                prob_dict[disease] = round(p, 4)
                if is_pos:
                    positive.append(disease)
                else:
                    negative.append(disease)

            findings.sort(key=lambda x: x['probability'], reverse=True)

            if not positive or (len(positive) == 1 and positive[0] == 'No Finding'):
                summary = "특이 소견 없음 (No significant findings)"
            else:
                real_findings = [f for f in positive if f != 'No Finding']
                summary = f"{len(real_findings)}개 이상 소견: {', '.join(real_findings)}"

            results.append({
                'findings': findings,
                'positive_findings': positive,
                'negative_findings': negative,
                'probabilities': prob_dict,
                'num_positive': len(positive),
                'summary': summary,
            })

        return results

    def _to_pil(self, image_input):
        """다양한 입력을 RGB PIL.Image로 변환"""
        if isinstance(image_input, str):
            return Image.open(image_input).convert('RGB')
        elif isinstance(image_input, Image.Image):
            return image_input.convert('RGB')
        elif isinstance(image_input, np.ndarray):
            if image_input.ndim == 2:
                # grayscale → RGB
                image_input = np.stack([image_input]*3, axis=-1)
            return Image.fromarray(image_input.astype(np.uint8)).convert('RGB')
        else:
            raise ValueError(f"지원하지 않는 입력 타입: {type(image_input)}")

    def _download_from_s3(self, s3_uri):
        """S3에서 모델 다운로드"""
        import boto3

        parts = s3_uri.replace('s3://', '').split('/', 1)
        bucket, key = parts[0], parts[1]
        local_path = os.path.join('/tmp', os.path.basename(key))

        if not os.path.exists(local_path):
            print(f"[Layer 2] S3 다운로드: {s3_uri}")
            s3 = boto3.client('s3')
            s3.download_file(bucket, key, local_path)
            print(f"[Layer 2] 다운로드 완료: {local_path}")

        return local_path

    def _extract_tar_gz(self, tar_path):
        """model.tar.gz 압축 해제 → best_model.pth 반환"""
        import tarfile

        extract_dir = tar_path.replace('.tar.gz', '')
        if not os.path.exists(extract_dir):
            os.makedirs(extract_dir, exist_ok=True)
            print(f"[Layer 2] 모델 압축 해제: {tar_path}")
            with tarfile.open(tar_path, 'r:gz') as tar:
                tar.extractall(extract_dir)

        # best_model.pth 찾기
        for fname in ['best_model.pth', 'model.pth']:
            candidate = os.path.join(extract_dir, fname)
            if os.path.exists(candidate):
                return candidate

        # 못 찾으면 .pth 파일 아무거나
        for f in os.listdir(extract_dir):
            if f.endswith('.pth'):
                return os.path.join(extract_dir, f)

        raise FileNotFoundError(f"모델 파일을 찾을 수 없습니다: {extract_dir}")
