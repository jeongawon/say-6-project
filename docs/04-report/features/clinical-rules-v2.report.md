# PDCA Report: clinical-rules-v2

> Layer 3 Clinical Logic Rules 내부 로직 개선
> 완료일: 2026-03-25
> 선행: chest-svc-improvement (임계값, pertinent negative, Bedrock 간결화)

---

## Executive Summary

### 1.1 프로젝트 개요

| 항목 | 내용 |
|------|------|
| **Feature** | clinical-rules-v2 |
| **PDCA** | Plan → Do (4 에이전트 병렬) → Test → Report |
| **수정 파일** | 11개 (engine.py + 8 rules + differential.py + models.py + pipeline.py + schemas.py + main.py) |

### 1.2 결과 요약 (전체 3단계 개선 누적)

| 항목 | v2 원본 | 1차 개선 | 2차 개선 (이번) |
|------|---------|---------|-----------------|
| 양성 소견 | 11/14 | 9/14 | **9 (독립 7 + 동반 2)** |
| 독립 소견 | 11 | 9 | **7** |
| 동반 소견 | 0 | 0 | **2** (Enlarged_CM, Lung_Opacity) |
| 감별진단 | 3 (중복) | 3 (중복) | **2** (CHF 통합) |
| confidence "low" | 0 | 0 | **3** (Enlarged_CM, Lung_Opacity, Pleural_Other) |
| 응답 시간 | 48.7초 | 14.5초 | **12.9초** |
| Rule 실행 순서 | 미보장 | 미보장 | **Phase 1→2→3** |

### 1.3 Value Delivered

| 관점 | 결과 |
|------|------|
| **Problem** | 독립 소견과 동반 소견 미구분으로 심각도 과장, 감별진단 중복 |
| **Solution** | 3단계 Rule 실행 + 교차 의존 처리 + 감별진단 중복 제거 + confidence 통일 |
| **Function UX Effect** | 독립 7개만 주요 소견으로 표시, 동반 2개는 secondary 플래그, 정확한 감별진단 |
| **Core Value** | 소견 간 인과관계를 반영한 정밀 임상 판정 — 의사가 보는 판독문 수준 |

---

## 2. 개선 항목별 결과

### 개선 1: engine.py 3단계 실행 ✅

```
Phase 1 (독립): Cardiomegaly, Pleural_Effusion, Pneumothorax,
                Atelectasis, Fracture, Support_Devices, Lung_Lesion
Phase 2 (교차): Enlarged_CM(→Cardiomegaly), Consolidation,
                Edema(→Atelectasis), Pleural_Other
Phase 3 (종합): Lung_Opacity(→Consolidation), Pneumonia, No_Finding
```

`_call_analyze()` 헬퍼로 `other_results` 파라미터 안전 전달 (inspect.signature 사용).

### 개선 2: enlarged_cm.py — 심비대 동반 소견 처리 ✅

- Cardiomegaly 양성 → `secondary_to_cardiomegaly=True`, confidence "low"
- DenseNet > 0.75 + 종격동 명확 확대 → 독립 가능성 유지 (confidence "medium")
- 결과: **Enlarged_CM이 secondary=True로 표시됨**

### 개선 3: edema.py — 무기폐 보정 ✅

- Atelectasis 동반 시 폐면적비 기반 대칭성 판정 불가 → DenseNet 확률 기반 전환
- DenseNet Edema 0.80 > 0.70 → bilateral 추정
- 결과: **Edema 위치가 "unilateral"(오분류) → "bilateral"(정확)으로 변경, confidence "high"**

### 개선 4: lung_opacity.py — 원인 귀속 ✅

- primary_cause="Consolidation" → `independent=False`, confidence "low"
- 결과: **Lung_Opacity가 secondary=True로 표시됨**

### 개선 5: pleural_other.py — DenseNet 단독 하향 ✅

- DenseNet만 양성 (YOLO 없음) → confidence "low"
- 결과: **Pleural_Other confidence 0.40 (low)**

### 개선 6: consolidation.py — 위치 추정 ✅

- YOLO bbox 없을 때 폐면적비로 위치 추정 (ratio 1.325 → "right")
- 결과: **Consolidation 위치 "우측 (폐 면적비 기반 추정)"**

### 개선 7: support_devices.py — 동적 환산 ✅

- `PX_TO_CM_APPROX = 0.014` → `estimate_px_to_cm(w, h)` (35x43cm 카세트 기반)
- `original_image_size` 필드 ClinicalLogicInput에 추가

### 개선 8: differential.py — 중복 제거 ✅

- DIAGNOSIS_GROUPS: CHF (심부전/폐부종 통합), Pneumonia, Malignancy
- `deduplicate_differentials()` → 3개(중복) → **2개**
- "울혈성 심부전"과 "심인성 폐부종"이 같은 CHF 그룹으로 통합

### 개선 9: no_finding.py — 범위 수정 ✅

- `0.80 <= ratio <= 1.05` → `0.85 <= ratio <= 1.15`
- 해부학적으로 좌폐가 약간 작은 것이 정상

### 개선 10: confidence 주석 통일 ✅

- 10개 Rule 파일에 공통 기준 주석 추가
- high (2+ 소스 일치) / medium (1소스 + 근거) / low (1소스 + 약한 근거)

---

## 3. 실측 데이터 (096052b7.jpg, 67세 M 호흡곤란)

```
독립 소견 7개:
  * Cardiomegaly: conf=0.40 — CTR 0.52
  * Pleural_Effusion: conf=0.70
  * Atelectasis: conf=0.70 — 우측 24.5% 감소
  * Fracture: conf=0.70
  * Consolidation: conf=0.70 — 우측 (면적비 추정)
  * Edema: conf=0.90 — bilateral (무기폐 보정)
  * Pleural_Other: conf=0.40 (DenseNet 단독 → low)

동반 소견 2개 (secondary=True):
  ~ Enlarged_CM: conf=0.40 — 심비대에 의한 종격동 확대
  ~ Lung_Opacity: conf=0.40 — Consolidation에 의한 음영

감별진단 2개 (중복 제거):
  1. 심인성 폐부종 (high)
  2. 무기폐 (high)

응답: 12.9초, risk: critical
pertinent_negatives: ["기흉 없음"]
next_actions: 4개
```

---

## 4. 수정 파일 목록

| # | 파일 | 변경 내용 |
|---|------|----------|
| 1 | `engine.py` | 3단계 Phase 실행 + deduplicate_differentials 호출 |
| 2 | `enlarged_cm.py` | other_results + secondary_to_cardiomegaly 플래그 |
| 3 | `edema.py` | other_results + 무기폐 대칭성 보정 |
| 4 | `lung_opacity.py` | independent 플래그 + 원인 귀속 시 confidence "low" |
| 5 | `pleural_other.py` | DenseNet 단독 → confidence "low" |
| 6 | `consolidation.py` | YOLO 없을 때 폐면적비 위치 추정 |
| 7 | `support_devices.py` | 동적 px→cm 환산 |
| 8 | `differential.py` | DIAGNOSIS_GROUPS + deduplicate 함수 |
| 9 | `no_finding.py` | 폐면적비 범위 0.85~1.15 |
| 10 | `models.py` | ClinicalLogicInput에 original_image_size 추가 |
| 11 | `pipeline.py` | original_image_size 전달 + secondary 플래그 구성 |
| 12 | `schemas.py` | Finding에 secondary 필드 추가 |
| 13 | `main.py` | Finding 생성 시 secondary 전달 |
| + | 10개 Rule 파일 | confidence 기준 주석 추가 |

---

## 5. Lessons Learned

| # | 교훈 |
|---|------|
| 1 | **Rule 실행 순서가 결과를 바꾼다** — Phase 분리 없이는 교차 의존 처리가 불가능. inspect.signature로 안전하게 파라미터 전달 |
| 2 | **양성 수 줄이기 ≠ 소견 제거** — detected는 유지하되 secondary 플래그로 독립/동반 구분. 오케스트레이터가 판단 |
| 3 | **스키마 동기화 3곳** — Finding(schemas.py) + pipeline.py(dict) + main.py(변환) 모두 일치해야 API에 반영 |
| 4 | **감별진단 중복은 그룹화로 해결** — 키워드 매칭 + 그룹별 첫 번째만 유지 |
| 5 | **무기폐가 있으면 대칭성 지표를 쓸 수 없다** — 다른 소견이 측정값을 왜곡할 수 있음. 교차 참조 필수 |
