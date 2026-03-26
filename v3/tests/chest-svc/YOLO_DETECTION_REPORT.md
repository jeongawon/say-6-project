# YOLO + DenseNet + Segmentation 검출 분석 보고서

> 분석일: 2026-03-26
> 테스트 이미지: 105건 (기본 5건 + MIMIC-CXR S3 샘플 100건)
> 모델: YOLOv8 (VinDr-CXR 14cls), DenseNet-121 (CheXpert 14cls), UNet Segmentation

---

## 1. 핵심 발견사항

### 1.1 YOLO 클래스 매핑 오류 (수정 완료)
- **문제**: 코드에 19개 클래스가 정의되어 있었으나 모델은 14개 클래스로 학습됨
- **영향**: 인덱스 4번부터 전체 클래스 엇갈림 → Pneumothorax(12→Nodule/Mass), ILD(5→Consolidation) 등 잘못 매핑
- **수정**: `VINDR_CLASSES`를 ONNX metadata 기준 14개로 교정
- **결과**: Pneumothorax, Pleural_effusion 등 검출 복원

### 1.2 마스크 정렬 오류 (수정 완료)
- **문제**: 320x320 정사각형 마스크가 비정사각형 원본 이미지 위에 object-fit:contain으로 표시될 때 종횡비 불일치
- **수정**: 마스크를 원본 비율로 리사이즈 후 PNG 인코딩 (최대 1024px)

### 1.3 좌우 폐 마스크 겹침 (수정 완료)
- **문제**: Normal 케이스에서 class 1(left_lung)이 x=[21-268]로 거의 전폭 차지, class 2와 겹침
- **수정**: 심장 중심선 기준으로 좌우 폐 강제 분리 (`_cleanup_lung_mask`)

### 1.4 YOLO bbox 위치 오류 (수정 완료)
- **문제**: Cardiomegaly bbox가 심장이 아닌 횡격막/복부에 위치 (center y=89%)
- **수정**: 세그멘테이션 마스크 기반 bbox 후처리 (`yolo_postprocess.py`)

### 1.5 측정값 SVG 미표시 (수정 완료)
- **문제**: 백엔드가 flat 스칼라값만 반환, 프론트엔드는 구조화된 좌표 객체 필요
- **수정**: `_build_structured_measurements()`로 mediastinum/trachea/cp_angle/diaphragm 좌표 구조체 반환

---

## 2. 105건 검출 통계

### 2.1 YOLO (conf > 0.25)

| 클래스 | 검출 수 | 전체 대비 |
|--------|---------|-----------|
| **Cardiomegaly** | **35건** | 33% |
| Other_lesion | 25건 | 24% |
| Aortic_enlargement | 11건 | 10% |
| Pleural_effusion | 3건 | 3% |
| ILD | 1건 | 1% |
| Pulmonary_fibrosis | 1건 | 1% |
| Pneumothorax | 1건 | 1% |
| **미검출** | **53건** | **50%** |

**검출율: 52/105 (50%)**

**미검출 클래스 (7/14)**:
Atelectasis, Calcification, Consolidation, Infiltration, Lung_Opacity, Nodule_Mass, Pleural_thickening

### 2.2 DenseNet (prob > 0.5)

| 클래스 | 검출 수 | 전체 대비 |
|--------|---------|-----------|
| Atelectasis | 63건 | 60% |
| Lung_Opacity | 60건 | 57% |
| Pneumonia | 59건 | 56% |
| Consolidation | 51건 | 49% |
| Support_Devices | 48건 | 46% |
| Lung_Lesion | 46건 | 44% |
| Cardiomegaly | 44건 | 42% |
| Pleural_Effusion | 44건 | 42% |
| Edema | 43건 | 41% |
| Fracture | 36건 | 34% |
| Enlarged_Cardiomediastinum | 33건 | 31% |
| No_Finding | 30건 | 29% |
| Pneumothorax | 25건 | 24% |
| Pleural_Other | 19건 | 18% |

**양성 이미지: 104/105 (99%)** ← 과검출 경향

### 2.3 CTR (세그멘테이션 기반)

| 항목 | 수치 |
|------|------|
| Cardiomegaly (CTR ≥ 0.5) | 73/105 (70%) |
| Normal (CTR < 0.5) | 32/105 (30%) |

---

## 3. Cardiomegaly 교차검증

| 조합 | 건수 | 해석 |
|------|------|------|
| **YOLO + DenseNet + CTR 모두 일치** | **22건** | 높은 확신 |
| YOLO + CTR (DenseNet 미검출) | 10건 | DenseNet 미검출 |
| DenseNet + CTR (YOLO 미검출) | 15건 | YOLO 민감도 부족 |
| CTR만 양성 | 26건 | 세그 모델 CTR 과다 추정? |
| DenseNet만 양성 | 6건 | DenseNet 과검출? |
| YOLO만 양성 | 2건 | YOLO 오진 의심 |

---

## 4. 모델별 문제점 분석

### 4.1 YOLO — 낮은 검출율 + 편향
- **50%만 검출**: 나머지 50%는 아무것도 못 잡음
- **Cardiomegaly 편향**: 전체 검출의 45%가 Cardiomegaly
- **Other_lesion 과다**: 비특이적 "기타 병변" 32% 차지
- **근본 원인**: VinDr-CXR 데이터셋 클래스 불균형 + 학습 부족

### 4.2 DenseNet — 과검출 경향
- **99% 양성**: 거의 모든 이미지에서 무언가를 검출
- **No_Finding이 30건**: 정상인데도 다른 질환과 동시에 양성
- **근본 원인**:
  - threshold 0.5가 이 모델에 너무 낮을 수 있음
  - MIMIC-CXR 이미지가 대부분 입원 환자 → 실제 이상 소견 비율이 높음
  - 그래도 60%에서 Atelectasis는 과다 (입원 환자 baseline?)

### 4.3 CTR (세그멘테이션) — 70% Cardiomegaly
- 입원 환자 X-ray에서 심비대 비율이 높은 것은 자연스러움
- 다만 320x320 리사이즈 시 종횡비 왜곡으로 CTR 오차 가능
- AP view에서는 심장이 더 크게 보임 (magnification effect)

---

## 5. 개선 권장사항

### 즉시 적용 가능 (코드 수정)
| # | 항목 | 우선도 |
|---|------|--------|
| 1 | DenseNet threshold 0.5 → 0.6~0.7로 상향 (과검출 감소) | 높음 |
| 2 | YOLO confidence threshold 0.25 → 0.20으로 하향 (미검출 감소) | 중간 |
| 3 | No_Finding과 다른 질환 동시 양성 시 로직 보정 | 중간 |
| 4 | AP view 보정: CTR에 0.9 계수 적용 (AP magnification) | 낮음 |

### 모델 재학습 필요
| # | 항목 | 효과 |
|---|------|------|
| 1 | YOLO: 학습 데이터 augmentation 강화 + epoch 증가 | 검출율 향상 |
| 2 | DenseNet: CheXpert U-ignore 라벨 처리 개선 | 과검출 감소 |
| 3 | YOLO: MIMIC-CXR 데이터로 fine-tuning | 도메인 적응 |

---

## 6. 수정 파일 목록

| 파일 | 변경 내용 |
|------|-----------|
| `layer2_detection/yolo.py` | VINDR_CLASSES 19→14개 매핑 교정 |
| `layer2_detection/yolo_postprocess.py` | 세그멘테이션 기반 YOLO bbox 후처리 (신규) |
| `layer1_segmentation/model.py` | 마스크 원본비율 리사이즈 + 좌우폐 분리 + 측정 좌표 구조체 |
| `pipeline.py` | YOLO 후처리 연결 + yolo_postprocess import |
| `static/index.html` | 드롭다운 UI + S3 100건 + RAG/Bedrock 스킵 토글 |
