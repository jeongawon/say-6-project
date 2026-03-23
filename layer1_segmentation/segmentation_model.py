"""
Layer 1: Anatomy Segmentation — HuggingFace 사전학습 모델 기반
모델: ianpan/chest-x-ray-basic (EfficientNetV2-S + U-Net, CheXmask 33.5만장 학습)

기능:
  1. 폐(좌/우) + 심장 세그멘테이션 마스크
  2. CTR (Cardiothoracic Ratio) 자동 계산
  3. 폐 면적 비율, 심장 면적 등 정량 측정
  4. AP/PA 뷰 분류, 나이/성별 예측 (보너스)

성능 (논문 검증):
  - Right Lung Dice: 0.957
  - Left Lung Dice: 0.948
  - Heart Dice: 0.943
"""

import os
import numpy as np
import torch
from PIL import Image


# 마스크 클래스 매핑 (모델 출력 argmax 기준)
MASK_CLASSES = {
    0: "background",
    1: "right_lung",
    2: "left_lung",
    3: "heart",
}


class SegmentationModel:
    """HuggingFace 사전학습 세그멘테이션 모델 래퍼"""

    def __init__(self, device=None, model_name="ianpan/chest-x-ray-basic"):
        self.model_name = model_name
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model = None

    def load(self):
        """모델 로드 (최초 1회)"""
        if self.model is not None:
            return

        from transformers import AutoModel

        print(f"[Layer 1] 세그멘테이션 모델 로드: {self.model_name}")
        self.model = AutoModel.from_pretrained(
            self.model_name, trust_remote_code=True
        )
        self.model = self.model.eval().to(self.device)
        print(f"[Layer 1] 로드 완료 (device: {self.device})")

    def predict(self, image_input):
        """
        이미지에서 세그멘테이션 + 측정값 추출

        Args:
            image_input: PIL.Image, numpy array (H,W) or (H,W,3), 또는 파일 경로

        Returns:
            dict: {
                'mask': np.ndarray (H, W) — 0:BG, 1:right_lung, 2:left_lung, 3:heart
                'measurements': {
                    'ctr': float,           # Cardiothoracic Ratio
                    'ctr_status': str,      # 'normal' / 'cardiomegaly' / 'severe_cardiomegaly'
                    'heart_width_px': int,
                    'thorax_width_px': int,
                    'left_lung_area_px': int,
                    'right_lung_area_px': int,
                    'heart_area_px': int,
                    'lung_area_ratio': float,  # left/right 면적 비율
                },
                'view': str,              # 'AP' / 'PA' / 'lateral'
                'age_pred': float,        # 예측 나이
                'sex_pred': str,          # 'M' / 'F'
                'original_size': (H, W),
            }
        """
        self.load()

        # 입력 정규화
        img_np = self._to_grayscale_numpy(image_input)
        original_size = img_np.shape[:2]

        # 모델 전처리 + 추론
        x = self.model.preprocess(img_np)
        x = torch.from_numpy(x).unsqueeze(0).unsqueeze(0).float()

        with torch.inference_mode():
            out = self.model(x.to(self.device))

        # 마스크 추출 (argmax)
        mask_tensor = out["mask"]
        if mask_tensor.dim() == 4:
            mask = mask_tensor.argmax(dim=1).squeeze(0).cpu().numpy()
        else:
            mask = mask_tensor.squeeze(0).cpu().numpy()

        # 원본 크기로 리사이즈
        if mask.shape != original_size:
            mask = np.array(
                Image.fromarray(mask.astype(np.uint8)).resize(
                    (original_size[1], original_size[0]), Image.NEAREST
                )
            )

        # 측정값 계산
        measurements = self._compute_measurements(mask)

        # 뷰 분류
        view_logits = out["view"]
        if isinstance(view_logits, torch.Tensor):
            view_idx = view_logits.argmax(dim=-1).item()
        else:
            view_idx = int(np.argmax(view_logits))
        view_map = {0: "AP", 1: "PA", 2: "lateral"}
        view = view_map.get(view_idx, "unknown")

        # 나이 예측
        age_pred = out["age"]
        if isinstance(age_pred, torch.Tensor):
            age_pred = age_pred.item()
        else:
            age_pred = float(age_pred)

        # 성별 예측
        female_prob = out["female"]
        if isinstance(female_prob, torch.Tensor):
            female_prob = female_prob.item()
        else:
            female_prob = float(female_prob)
        sex_pred = "F" if female_prob >= 0.5 else "M"

        return {
            "mask": mask.astype(np.uint8),
            "measurements": measurements,
            "view": view,
            "age_pred": round(age_pred, 1),
            "sex_pred": sex_pred,
            "original_size": original_size,
        }

    def _to_grayscale_numpy(self, image_input):
        """다양한 입력을 grayscale numpy array로 변환"""
        if isinstance(image_input, str):
            # 파일 경로
            img = Image.open(image_input)
            return np.array(img.convert("L"))
        elif isinstance(image_input, Image.Image):
            return np.array(image_input.convert("L"))
        elif isinstance(image_input, np.ndarray):
            if image_input.ndim == 3:
                # RGB → grayscale
                return np.dot(image_input[..., :3], [0.2989, 0.5870, 0.1140]).astype(
                    np.uint8
                )
            return image_input.astype(np.uint8)
        else:
            raise ValueError(f"지원하지 않는 입력 타입: {type(image_input)}")

    def _compute_measurements(self, mask):
        """마스크에서 CTR 및 정량 측정값 계산"""
        right_lung = (mask == 1)
        left_lung = (mask == 2)
        heart = (mask == 3)

        # 면적 (픽셀 수)
        right_lung_area = int(right_lung.sum())
        left_lung_area = int(left_lung.sum())
        heart_area = int(heart.sum())
        total_lung_area = right_lung_area + left_lung_area

        # CTR 계산: 심장 최대 가로폭 / 흉곽 최대 가로폭
        heart_width = self._max_horizontal_width(heart)
        thorax_mask = right_lung | left_lung | heart
        thorax_width = self._max_horizontal_width(thorax_mask)

        if thorax_width > 0:
            ctr = heart_width / thorax_width
        else:
            ctr = 0.0

        # CTR 상태 판정
        if ctr >= 0.60:
            ctr_status = "severe_cardiomegaly"
        elif ctr >= 0.50:
            ctr_status = "cardiomegaly"
        else:
            ctr_status = "normal"

        # 폐 면적 비율 (좌/우)
        if right_lung_area > 0:
            lung_area_ratio = left_lung_area / right_lung_area
        else:
            lung_area_ratio = 0.0

        return {
            "ctr": round(ctr, 4),
            "ctr_status": ctr_status,
            "heart_width_px": heart_width,
            "thorax_width_px": thorax_width,
            "left_lung_area_px": left_lung_area,
            "right_lung_area_px": right_lung_area,
            "heart_area_px": heart_area,
            "total_lung_area_px": total_lung_area,
            "lung_area_ratio": round(lung_area_ratio, 4),
        }

    @staticmethod
    def _max_horizontal_width(binary_mask):
        """바이너리 마스크에서 각 행의 가로폭 중 최대값 반환"""
        if not binary_mask.any():
            return 0

        rows_with_content = binary_mask.any(axis=1)
        if not rows_with_content.any():
            return 0

        max_width = 0
        for row_idx in np.where(rows_with_content)[0]:
            row = binary_mask[row_idx]
            cols = np.where(row)[0]
            width = cols[-1] - cols[0] + 1
            max_width = max(max_width, width)

        return int(max_width)
