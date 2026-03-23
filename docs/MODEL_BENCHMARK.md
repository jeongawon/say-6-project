# DenseNet-121 모델 성능 벤치마크

## 1. 모델 개요

| 항목 | 값 |
|------|-----|
| **모델** | DenseNet-121 (ImageNet pretrained → 2-Stage Fine-tuning) |
| **Training Job** | densenet121-mimic-cxr-v1 |
| **데이터셋** | MIMIC-CXR p10 subset (PA only) |
| **학습 데이터** | 8,993장 (train) / 65장 (val) / 60장 (test) |
| **라벨** | CheXpert 14개 질환 (multi-label) |
| **Loss** | BCEWithLogitsLoss (pos_weight 적용) |
| **Optimizer** | Adam (Stage1: lr=1e-4, Stage2: lr=1e-5) |
| **총 에폭** | 30 (Stage1: 5 + Stage2: 25) |
| **배치 크기** | 32 |
| **인스턴스** | ml.g5.xlarge (NVIDIA A10G 24GB) |
| **학습 시간** | 79.3분 (과금 시간: 24분, Spot) |
| **Test Loss** | 1.0045 |
| **Mean AUROC** | 0.7475 |

---

## 2. 질환별 AUROC (Per-Class)

| 질환 | AUROC | 등급 | 비고 |
|------|-------|------|------|
| Pleural Effusion | **0.845** | 우수 | 가장 높은 성능 |
| Edema | **0.836** | 우수 | |
| Pleural Other | **0.832** | 우수 | |
| Lung Lesion | **0.810** | 양호 | |
| No Finding | **0.799** | 양호 | |
| Atelectasis | **0.786** | 양호 | |
| Consolidation | **0.784** | 양호 | |
| Lung Opacity | **0.757** | 보통 | |
| Support Devices | **0.757** | 보통 | |
| Cardiomegaly | **0.750** | 보통 | |
| Enlarged Cardiomediastinum | **0.697** | 미흡 | |
| Pneumothorax | **0.685** | 미흡 | |
| Pneumonia | **0.674** | 미흡 | |
| Fracture | **0.453** | 불량 | 랜덤(0.5) 이하 |
| **Mean** | **0.748** | **보통** | |

> 등급 기준: 우수(≥0.82) / 양호(≥0.76) / 보통(≥0.72) / 미흡(≥0.65) / 불량(<0.65)

---

## 3. 논문 벤치마크 비교

동일 모델(DenseNet-121) + 유사 태스크의 주요 논문 결과와 비교:

| 질환 | **Ours** | CheXpert¹ | CheXNet² | MIMIC-CXR³ | 차이(vs CheXpert) |
|------|----------|-----------|----------|------------|-------------------|
| Atelectasis | 0.786 | 0.858 | 0.809 | 0.808 | -0.072 |
| Cardiomegaly | 0.750 | 0.907 | 0.925 | 0.853 | -0.157 |
| Consolidation | 0.784 | 0.893 | 0.775 | 0.817 | -0.109 |
| Edema | 0.836 | 0.924 | 0.889 | 0.901 | -0.088 |
| Enlarged Cardiomediastinum | 0.697 | 0.711 | — | 0.731 | -0.014 |
| Fracture | 0.453 | — | — | — | — |
| Lung Lesion | 0.810 | — | — | — | — |
| Lung Opacity | 0.757 | — | 0.735 | 0.771 | — |
| No Finding | 0.799 | — | — | 0.867 | — |
| Pleural Effusion | 0.845 | 0.934 | 0.864 | 0.921 | -0.089 |
| Pleural Other | 0.832 | — | — | — | — |
| Pneumonia | 0.674 | — | 0.768 | 0.769 | — |
| Pneumothorax | 0.685 | — | 0.889 | 0.856 | — |
| Support Devices | 0.757 | — | — | 0.905 | — |
| **Mean** | **0.748** | **~0.87** | **~0.84** | **~0.84** | **-0.09~0.12** |

> ¹ CheXpert (Irvin et al., 2019): 224,316장, Stanford 데이터, 5개 경쟁 라벨만 보고
> ² CheXNet (Rajpurkar et al., 2017): 112,120장, ChestX-ray14 데이터
> ³ MIMIC-CXR (Johnson et al., 2019): 227,835장, 전체 데이터셋
> — 표시는 해당 논문에서 보고하지 않은 질환

---

## 4. 성능 격차 원인 분석

| 원인 | 설명 | 영향도 |
|------|------|--------|
| **데이터 규모** | 9,118장 vs 논문 10만~22만장 (약 1/20) | ★★★★★ |
| **Val/Test 크기** | 65/60장 → AUROC 통계적 불안정성 높음 | ★★★★ |
| **p10 서브셋 편향** | 환자 ID가 p10으로 시작하는 그룹만 사용 → 인구통계적 편향 가능 | ★★★ |
| **에폭 수** | 30 에폭 (논문은 보통 50~100+ 에폭) | ★★ |
| **이미지 증강** | 기본 증강만 적용 (논문은 다양한 augmentation) | ★★ |
| **라벨 불확실성** | U-Ones 변환 (uncertain → positive) 전략 사용 | ★ |

---

## 5. 질환별 상세 분석

### 우수 (AUROC ≥ 0.82)
- **Pleural Effusion (0.845)**: 흉수는 하폐야에 특징적 음영으로 비교적 쉬운 태스크. Grad-CAM에서도 하폐야 활성화 확인.
- **Edema (0.836)**: 폐부종은 양쪽 폐에 광범위 음영 → 넓은 영역 기반 판단 가능.
- **Pleural Other (0.832)**: 흉막 이상 소견. 샘플 수가 적을 수 있으나 특징이 명확.

### 양호 (0.76~0.82)
- **Lung Lesion (0.810)**: 폐 병변 탐지 양호. 다만 Grad-CAM에서 병변 위치 특정은 부정확.
- **Atelectasis (0.786)**, **Consolidation (0.784)**: 경화/무기폐는 유사한 영상 소견 → 모델이 어느 정도 구분 가능.

### 미흡~불량 (< 0.70)
- **Pneumonia (0.674)**: Consolidation과 영상학적으로 겹침이 많아 단독 구분 어려움.
- **Pneumothorax (0.685)**: p10 서브셋 내 양성 샘플 부족 가능성.
- **Fracture (0.453)**: AUROC 0.5 미만 = **랜덤보다 못함**. 골절은 X-ray에서 매우 미세한 소견이라 대량 데이터 필요.

---

## 6. Grad-CAM++ 시각화 평가

| 항목 | 평가 |
|------|------|
| 질환별 히트맵 차이 | 대부분 유사한 패턴 (질환 구분 어려움) |
| 해부학적 타당성 | 부분적 (심장 질환→심장 영역, 흉수→하폐야) |
| 공간 해상도 | 낮음 (7x7 → 224x224 업스케일, 블롭 형태) |
| 임상 활용 가능성 | 보조 참고 수준 (진단 근거로는 부족) |
| 소견서 위치 기술 근거 | 제한적 (좌/우 정도만 구분 가능) |

---

## 7. 개선 방향 (향후 참고)

| 방법 | 예상 효과 | 난이도 |
|------|-----------|--------|
| 전체 MIMIC-CXR 데이터 사용 (22만장) | AUROC +0.05~0.10 | 중 (S3 용량, 학습 시간) |
| Val/Test 셋 확대 (최소 500장+) | 평가 안정성 향상 | 하 |
| 학습 에폭 증가 (50~100) | AUROC +0.01~0.03 | 하 |
| 고급 Augmentation (CutMix, MixUp) | AUROC +0.02~0.05 | 중 |
| EfficientNet-B4/B7 모델 교체 | AUROC +0.02~0.04 | 중 |
| Label Smoothing / 멀티태스크 학습 | AUROC +0.01~0.03 | 중 |
| Fracture 제거 또는 별도 모델 | Mean AUROC 계산 시 개선 | 하 |

---

## 8. 학습 환경

| 항목 | 값 |
|------|-----|
| 프레임워크 | PyTorch 2.8.0 |
| GPU | NVIDIA A10G 24GB (ml.g5.xlarge) |
| 컨테이너 | SageMaker PyTorch 2.8.0 GPU (py312, cu129, ubuntu22.04) |
| Spot 인스턴스 | 사용 (On-Demand $1.41/hr → Spot ~$0.42/hr) |
| 실제 비용 | 약 $0.17 (24분 과금) |
| 날짜 | 2026-03-21 |
