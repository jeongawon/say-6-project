# U-Net Segmentation Planning Document

> **Summary**: CXR 이미지에서 폐/심장 해부학 구조를 세그멘테이션하여 Clinical Logic Layer의 기반 수치(CTR, 폐 면적 등)를 제공
>
> **Project**: Dr. AI Radiologist (MIMIC-CXR)
> **Author**: hyunwoo
> **Date**: 2026-03-21
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | Grad-CAM만으로는 해부학적 위치 특정 불가. CTR, 종격동 너비 등 정량 수치 산출에 폐/심장 마스크가 필수 |
| **Solution** | U-Net + EfficientNet-B4 encoder로 폐(좌/우)/심장 세그멘테이션 모델 학습, CheXmask 데이터셋 활용 |
| **Function/UX Effect** | 프론트엔드에 심장/폐 윤곽선 오버레이 + CTR 수치 표시. "CTR 0.54 → 심비대" 같은 정량적 근거 제공 |
| **Core Value** | 14개 질환 Clinical Logic의 공통 기반. 이것 없이는 Phase 1 MVP의 어떤 Rule도 동작 불가 |

---

## 1. Overview

### 1.1 Purpose

흉부 X-Ray 이미지에서 **폐(좌/우)**와 **심장** 영역을 픽셀 단위로 분리하여:
1. CTR(Cardiothoracic Ratio) 자동 계산 → Cardiomegaly 판정
2. 종격동 너비 측정 → Enlarged Cardiomediastinum 판정
3. 좌/우 폐 면적 비율 → Atelectasis 기초 수치
4. CP angle 영역 추출 → Pleural Effusion 판정
5. 기관 중심선 추출 → Tension Pneumothorax 판정

### 1.2 Background

- 현재 DenseNet-121(v1)은 14-label 확률만 출력 → "어디에" 이상이 있는지 모름
- Grad-CAM++은 7x7 해상도 블롭 → 임상적 활용 불가 (벤치마크 분석 결과 확인됨)
- CHEST_MODAL_V2_REDESIGN.md의 Layer 1이 세그멘테이션
- **Layer 2~6 전부가 Layer 1의 마스크에 의존** → 최우선 구현 대상

### 1.3 Related Documents

- `CHEST_MODAL_V2_REDESIGN.md` — Section 2 (Layer 1), Section 4 (모델+데이터셋 매핑)
- `MODEL_BENCHMARK.md` — DenseNet-121 v1 성능 벤치마크
- `deploy/handler.py` — Lambda 파이프라인 내 Layer 1 위치

---

## 2. Scope

### 2.1 In Scope

- [x] 데이터셋 선택 및 확보 (CheXmask 또는 JSRT)
- [ ] U-Net 모델 아키텍처 구성 (EfficientNet-B4 encoder)
- [ ] SageMaker Training Job으로 학습
- [ ] 추론 코드 (`layer1_segmentation/segment_anatomy.py`)
- [ ] CTR 자동 계산 로직 (`layer3_clinical_logic/rules/cardiomegaly.py`)
- [ ] 종격동 너비 측정 로직 (`layer3_clinical_logic/rules/enlarged_cm.py`)
- [ ] 좌/우 폐 면적 비율 계산
- [ ] Lambda handler에 Layer 1 통합
- [ ] 성능 평가 (Dice score)

### 2.2 Out of Scope

- 뼈(늑골/쇄골) 세그멘테이션 (Phase 2에서 골절 탐지 시 필요하면 추가)
- 폐엽(lobe) 단위 세분화 (Phase 2 YOLOv8 bbox → 폐엽 매핑으로 대체)
- 기관(trachea) 세그멘테이션 (폐 마스크에서 간접 추출)

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | CXR 이미지 입력 시 좌폐/우폐/심장 3-class 마스크 출력 | High | Pending |
| FR-02 | 마스크에서 CTR 자동 계산 (심장 가로폭 / 흉곽 가로폭) | High | Pending |
| FR-03 | 마스크에서 종격동 너비 자동 측정 (좌폐~우폐 사이 공간) | High | Pending |
| FR-04 | 좌/우 폐 면적 비율 계산 | Medium | Pending |
| FR-05 | Lambda CPU 환경에서 추론 가능 (GPU 불필요) | High | Pending |
| FR-06 | 추론 시간 3초 이내 (CPU, 512x512 입력) | Medium | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| 정확도 | Dice score ≥ 0.95 (폐), ≥ 0.90 (심장) | Test set 평가 |
| 추론 속도 | < 3초 (CPU, Lambda 4GB RAM) | 실측 |
| 모델 크기 | < 150MB (S3 다운로드 + /tmp 캐시) | 파일 크기 |
| 입력 해상도 | 512x512 (224x224보다 높은 해상도로 경계 정밀도 확보) | - |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] U-Net 모델 학습 완료 (Dice ≥ 0.95 폐 / ≥ 0.90 심장)
- [ ] CTR 자동 계산 정확도 검증 (수동 측정 대비 오차 ≤ 0.03)
- [ ] Lambda handler에 Layer 1 통합 완료
- [ ] 테스트 이미지 5장에 대해 마스크 + CTR 시각화 확인

### 4.2 Quality Criteria

- [ ] Dice score 목표 달성
- [ ] CPU 추론 3초 이내
- [ ] 모델 가중치 150MB 이내

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| CheXmask 데이터 접근 불가 (PhysioNet 승인 필요) | High | Medium | JSRT(247장)로 대체 학습. 정확도 다소 낮지만 MVP 가능 |
| 교육 계정 SageMaker 제약 (이전 경험) | Medium | High | boto3로 Training Job 생성 (DenseNet 때와 동일 우회) |
| U-Net 512x512 입력 시 GPU 메모리 부족 (g4dn T4 16GB) | Medium | Low | batch_size 줄이거나 g5.xlarge 사용 |
| Lambda /tmp 용량 초과 (모델 3개 + FAISS 캐시) | Medium | Low | Ephemeral Storage 2GB 설정, 모델 크기 최적화 |
| CTR 자동 측정 정확도 부족 | Medium | Medium | 마스크 후처리(morphological ops)로 경계 보정 |

---

## 6. Architecture Considerations

### 6.1 모델 선택

| Option | 장점 | 단점 | 선택 |
|--------|------|------|:----:|
| **U-Net + EfficientNet-B4** | 높은 정확도, 의료영상 표준 | 모델 크기 ~100MB | **O** |
| U-Net + ResNet-34 | 가벼움 (~50MB) | 정확도 다소 낮음 | |
| DeepLabV3+ | 멀티스케일 강점 | 의료영상에서 U-Net 대비 이점 불명확 | |
| HybridGNet (CheXmask 논문) | CheXmask 생성에 사용된 모델 | 구현 복잡, 코드 비공개 | |

### 6.2 데이터셋 선택

| Dataset | 크기 | 마스크 대상 | 품질 | 접근성 | 선택 |
|---------|------|-----------|------|--------|:----:|
| **CheXmask** | 676K장 | 폐+심장 | HybridGNet 생성 (검증됨) | PhysioNet 승인 필요 | 1순위 |
| **JSRT** | 247장 | 폐+심장+쇄골 | 수동 어노테이션 (Gold standard) | 공개 | 2순위 (대체) |
| Montgomery | 138장 | 폐 only | 수동 어노테이션 | 공개 | 보조 |

### 6.3 학습 환경

| 항목 | 값 |
|------|-----|
| SageMaker Training Job | `unet-lung-heart-v1` |
| 인스턴스 | ml.g4dn.xlarge (T4 16GB) 또는 ml.g5.xlarge |
| 입력 해상도 | 512x512 |
| 출력 | 3-class mask (배경/폐/심장) 또는 별도 binary mask |
| Loss | Dice Loss + BCE (combo) |
| Optimizer | Adam, lr=1e-4 |
| 에폭 | 50 |
| 예상 학습 시간 | CheXmask 전체: 2~4시간 / JSRT: 30분 |

### 6.4 파이프라인 통합

```
deploy/handler.py
  └── run_pipeline()
       ├── Layer 1: segment_anatomy(image)     ← 이번에 구현
       │   ├── lung_mask (좌/우 분리)
       │   ├── heart_mask
       │   └── measurements (CTR, 폐 면적 등)
       ├── Layer 2: densenet + yolo
       ├── Layer 3: clinical_logic(anatomy_masks, ...)  ← CTR Rule 구현
       └── ...
```

---

## 7. Convention Prerequisites

### 7.1 코드 구조

```
layer1_segmentation/
├── train_unet.py              # SageMaker 학습 스크립트
├── segment_anatomy.py         # 추론 코드 (Lambda에서 호출)
├── preprocessing.py           # 마스크 데이터 전처리
└── sagemaker/
    └── training_job_config.json
```

### 7.2 환경 변수

| Variable | Purpose | Scope |
|----------|---------|-------|
| MODEL_BUCKET | S3 모델 가중치 버킷 | Lambda |
| MODEL_PREFIX | S3 모델 경로 prefix | Lambda |
| UNET_MODEL_KEY | U-Net 가중치 S3 키 | Lambda |

---

## 8. Next Steps

1. [x] CheXmask 데이터 접근 확인 — **공개 데이터셋 확인 완료**
   - Preprocessed/MIMIC-CXR-JPG.csv (4.4 GB, 1024x1024 균일 해상도)
   - RLE 인코딩, 좌폐/우폐/심장 3-class
   - Dice RCA Mean ≥ 0.7 품질 필터 적용
2. [x] 데이터 전처리 코드 작성 (`layer1_segmentation/preprocessing.py`)
   - RLE 디코딩 (CheXmask 공식 코드 기반)
   - p10 서브셋 필터링 + split 매핑
   - NPZ/PNG 저장 (512x512 리사이즈)
3. [ ] **SageMaker 노트북에서 CheXmask 다운로드 → S3 업로드**
4. [ ] SageMaker에서 전처리 실행 (preprocessing.py)
5. [ ] U-Net 학습 코드 작성 (`layer1_segmentation/train_unet.py`)
6. [ ] SageMaker Training Job 실행
7. [ ] 추론 코드 작성 (`layer1_segmentation/segment_anatomy.py`)
8. [ ] CTR 계산 Rule 구현 (`layer3_clinical_logic/rules/cardiomegaly.py`)
9. [ ] Lambda handler 통합
10. [ ] Design document 작성 → `/pdca design unet-segmentation`

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-21 | Initial draft | hyunwoo |
| 0.2 | 2026-03-21 | CheXmask 데이터 포맷 조사 완료, 전처리 코드 작성 | hyunwoo |
