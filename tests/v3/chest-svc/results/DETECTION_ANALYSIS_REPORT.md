# chest-svc 5건 전수 검사 오탐 분석 보고서

**작성일**: 2026-03-26
**테스트 환경**: chest-svc v3 (UNet + DenseNet + YOLOv8), RAG/Bedrock 스킵
**테스트 건수**: 5건 (기본 테스트 케이스)

---

## 1. 전체 요약

| Case ID | 병변 | CTR | CTR 판정 | YOLO 검출 | 마스크 정확도 | 종합 판정 |
|---------|------|-----|---------|----------|------------|----------|
| 096052b7 | 심부전(CHF) | 0.520 | cardiomegaly ✅ | Cardiomegaly 42% | ⭕ 양호 | ⚠️ YOLO bbox 위치 약간 낮음 |
| 174413ec | 폐렴(Pneumonia) | 0.798 | cardiomegaly ❌ | 없음 ❌ | ❌ 심각 오류 | ❌ 마스크 완전 이탈, 오탐 |
| 2a2277a9 | 긴장성기흉(PTX) | 0.415 | normal ✅ | 없음 ❌ | ⭕ 양호 | ⚠️ YOLO 미검출 |
| 68b5c4b1 | 정상(Normal) | 0.419 | normal ✅ | Other_lesion 34% ❌ | ⭕ 양호 | ❌ 정상인데 False Positive |
| e084de3b | 다중소견(Multi) | 0.717 | cardiomegaly ❌ | 없음 ❌ | ❌ 심각 오류 | ❌ Lateral View 미처리 |

**정상 작동: 1/5 (20%) — 심각한 개선 필요**

---

## 2. 케이스별 상세 분석

### Case 1: 096052b7 — 심부전(CHF) ⚠️

**이미지**: 3056x2544 (가로 > 세로, AP view)

**마스크 (Segmentation)**
- R Lung (파랑): ✅ 해부학적으로 정확한 위치
- L Lung (초록): ✅ 정확
- Heart (빨강): ✅ 심장 위치에 정확히 오버레이
- **마스크 리사이즈 수정 후 정렬 개선됨** (320x320 → 원본 비율 복원)

**YOLO**
- Cardiomegaly 42% — bbox=[1242, 1280, 2349, 2170]
- ⚠️ bbox가 심장 하부에 치우쳐 있음 (y 중심 ≈ 68% 위치)
- 심장 마스크 중심은 약 55% 위치 → **약 13% 하방 편차**

**CTR**
- 0.520 (cardiomegaly) ✅ 정확
- Heart=1096px, Thorax=2111px

**DenseNet**: 9건 탐지 (finding 이름 미표시 — 스키마 확인 필요)

---

### Case 2: 174413ec — 폐렴(Pneumonia) ❌❌❌

**이미지**: 2544x3056 (세로 > 가로)

**마스크 (Segmentation) — 심각한 오류**
- ❌ Heart 마스크 파편이 이미지 **좌상단 모서리**와 **우하단 모서리**에 잘못 표시
- ❌ 마스크가 전체적으로 이미지 **중앙 대비 위쪽으로 편향**
- 원인 추정: 이미지가 약간 기울어져 있거나, 320x320 리사이즈 시 비율 왜곡

**YOLO**
- ❌ **0건 검출** — 폐렴(Consolidation/Opacity 등) 미검출
- YOLO 모델의 VinDr 14클래스에 "Pneumonia" 자체가 없음
- 관련 가능 클래스: Consolidation, Lung_Opacity → 어느 것도 미검출

**CTR**
- ❌ 0.798 (cardiomegaly) — **비정상적으로 높음**
- Heart=1256px, Thorax=1574px
- 마스크 오류로 인해 CTR 계산도 부정확

**핵심 문제**: 마스크 세그멘테이션 자체가 이 이미지에서 실패

---

### Case 3: 2a2277a9 — 긴장성기흉(Tension PTX) ⚠️

**이미지**: 2544x3056 (세로 > 가로)

**마스크 (Segmentation)**
- ✅ R Lung, L Lung, Heart 위치 정확
- 긴장성 기흉 특유의 한쪽 폐 과팽창이 마스크에 반영됨 (R Lung이 L Lung보다 큼)

**YOLO**
- ❌ **0건 검출** — Pneumothorax 미검출
- YOLO VinDr 14클래스에 **Pneumothorax가 포함되어 있음에도 미검출**
- conf_threshold(0.25) 미만일 가능성 높음

**CTR**
- ✅ 0.415 (normal) — 정상 범위

**핵심 문제**: YOLO 모델이 Pneumothorax에 대한 검출 성능 부족

---

### Case 4: 68b5c4b1 — 정상(Normal) ❌

**이미지**: 2539x2705

**마스크 (Segmentation)**
- ⭕ R Lung, L Lung, Heart 위치 대체로 양호
- "PORTABLE SEMI-ERECT" 텍스트가 있는 포터블 X-ray

**YOLO**
- ❌ **Other_lesion 34%** — bbox=[0, 1193, 383, 2602]
- 이미지 **좌측 가장자리** (x=0~383) 전체를 감싼 박스
- **정상 이미지인데 False Positive** — 이미지 경계/콜리메이터를 병변으로 오인
- 포터블 X-ray의 검은 배경 경계가 "Other_lesion"으로 검출됨

**CTR**
- ✅ 0.419 (normal) — 정상

**핵심 문제**: YOLO가 이미지 아티팩트(콜리메이터/경계)를 병변으로 오검출

---

### Case 5: e084de3b — 다중소견(Multi) ❌❌❌

**이미지**: 2544x3056 (세로 > 가로)

**마스크 (Segmentation) — 심각한 오류**
- ❌ **Lateral View(측면 촬영)인데 PA/AP View로 처리**
- 마스크가 측면 이미지에 부적절하게 오버레이됨
- 파랑/초록/빨강이 겹치며 해부학적으로 무의미한 위치

**YOLO**
- ❌ **0건 검출** — 다중 소견(기침, 체중감소, 흉통)에 대한 어떤 병변도 미검출

**CTR**
- ❌ 0.717 (cardiomegaly) — Lateral View에서 CTR 계산 자체가 **무의미**
- 모델이 View를 "AP"로 잘못 분류한 것으로 추정

**핵심 문제**: Lateral View 감지 및 분기 처리 부재

---

## 3. 공통 문제점 정리

### 🔴 Critical (즉시 수정 필요)

| # | 문제 | 영향 범위 | 원인 | 수정 방향 |
|---|------|----------|------|----------|
| C1 | Lateral View 미처리 | Case 5 | View 분류(AP/PA/Lateral) 결과를 파이프라인에서 사용 안 함 | `view == "Lateral"` 시 CTR 계산 스킵, 마스크 비표시, 경고 표시 |
| C2 | 마스크 이탈 (일부 이미지) | Case 2, 5 | 이미지 프레이밍/회전에 취약한 UNet | 마스크 후처리: 연결 컴포넌트 분석으로 이탈 파편 제거 |
| C3 | CTR 오계산 | Case 2, 5 | 마스크 오류가 CTR에 전파 | 마스크 유효성 검증 후 CTR 계산 (폐/심장 면적비 기준 임계값) |

### 🟡 Major (개선 필요)

| # | 문제 | 영향 범위 | 원인 | 수정 방향 |
|---|------|----------|------|----------|
| M1 | YOLO 검출률 매우 낮음 | 3/5 건 미검출 | VinDr-CXR 학습 데이터 vs MIMIC-CXR 테스트 데이터 도메인 갭 | conf_threshold 조정(0.25→0.15), 또는 모델 파인튜닝 |
| M2 | YOLO False Positive | Case 4 | 이미지 경계/콜리메이터 오검출 | bbox 필터: 이미지 가장자리 10% 영역에만 있는 검출 제외 |
| M3 | YOLO bbox 위치 편차 | Case 1 | 모델 출력 자체 한계 | 세그멘테이션 기반 후처리로 bbox 보정 |
| M4 | DenseNet finding 이름 미표시 | 전체 | findings에 class_name 매핑 누락 | DenseNet 출력 → CheXpert 14 클래스명 매핑 확인 |

### 🟢 Minor (개선 권장)

| # | 문제 | 수정 방향 |
|---|------|----------|
| m1 | 측정 오버레이(SVG) 미표시 | 프론트엔드 drawMeasurements() 함수 디버깅 |
| m2 | 마스크 범례에 CP Angle/Diaphragm 미포함 | 범례 + 측정 결과 카드 UI 추가 |

---

## 4. 우선 수정 로드맵

```
Phase 1 (즉시): C1 Lateral View 분기 + C2 마스크 파편 제거 + M2 YOLO 경계 필터
Phase 2 (1일): M1 YOLO threshold 조정 + M3 세그 기반 bbox 후처리
Phase 3 (2일): C3 CTR 유효성 검증 + M4 DenseNet 클래스명 매핑
Phase 4 (3일): m1 측정 SVG 프론트엔드 수정 + 전체 재테스트
```

---

## 5. 결과 파일 위치

| 파일 | 설명 |
|------|------|
| `results/096052b7_심부전(CHF).jpg` | Case 1 오버레이 이미지 |
| `results/174413ec_폐렴(Pneumonia).jpg` | Case 2 오버레이 이미지 |
| `results/2a2277a9_긴장성기흉(Tension PTX).jpg` | Case 3 오버레이 이미지 |
| `results/68b5c4b1_정상(Normal).jpg` | Case 4 오버레이 이미지 |
| `results/e084de3b_다중소견(Multi).jpg` | Case 5 오버레이 이미지 |
| `results/test_summary.json` | API 응답 요약 JSON |
