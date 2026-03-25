# Plan: clinical-rules-v2

> Layer 3 Clinical Logic Rules 내부 로직 개선 (임계값 이후 2차 개선)
> 작성일: 2026-03-25
> 근거: CLINICAL_RULES_IMPROVEMENT_PROMPT_V2.md
> 선행 완료: chest-svc-improvement (임계값, pertinent negative, Bedrock 간결화)

---

## Executive Summary

| 관점 | 내용 |
|------|------|
| **Problem** | 양성 9/14 중 Enlarged_CM, Lung_Opacity는 독립 소견이 아닌 동반 증상. 감별진단 중복(CHF=폐부종). Rule 실행 순서 미보장 |
| **Solution** | engine.py 3단계 실행 + 6개 Rule 로직 개선 + 감별진단 중복 제거 + confidence 체계 통일 |
| **Function UX Effect** | 양성 9→5~7개, 감별진단 3→2개(중복 제거), 독립 소견 vs 동반 소견 구분 |
| **Core Value** | 임상적으로 정확한 소견 분류 — 과탐지 제거가 아니라 소견 간 관계를 반영한 정밀 판정 |

---

## Context Anchor

| 항목 | 내용 |
|------|------|
| **WHY** | Rule 내부 로직이 서로의 결과를 모르고 독립 실행 → 중복/오분류 |
| **WHO** | 박현우 (chest-svc 담당) |
| **RISK** | Rule 간 의존성 추가 시 순환 참조, 기존 테스트 깨질 수 있음 |
| **SUCCESS** | 양성 5~7개, confidence "low" 2~3개, 감별진단 중복 0 |
| **SCOPE** | layer3_clinical_logic/ 내부만 수정 + pipeline.py findings 필터링 |

---

## 수정 파일 (10개 개선 → 9개 파일)

| # | 파일 | 개선 | 작업 |
|---|------|------|------|
| 1 | `engine.py` | 개선 1 | Rule 실행 3단계화 (Phase 1→2→3) |
| 2 | `enlarged_cm.py` | 개선 2 | Cardiomegaly 동반 시 confidence "low" + 플래그 |
| 3 | `edema.py` | 개선 3 | 무기폐 동반 시 대칭성 보정 |
| 4 | `lung_opacity.py` | 개선 4 | 원인 귀속 시 independent=False + confidence "low" |
| 5 | `pleural_other.py` | 개선 5 | DenseNet 단독 양성 → confidence "low" |
| 6 | `consolidation.py` | 개선 6 | YOLO 없을 때 폐면적비로 위치 추정 |
| 7 | `support_devices.py` | 개선 7 | px→cm 동적 환산 (이미지 크기 기반) |
| 8 | `differential.py` | 개선 8 | 감별진단 중복 제거 (DIAGNOSIS_GROUPS) |
| 9 | `no_finding.py` | 개선 9 | 정상 폐면적비 범위 0.85~1.15로 수정 |
| - | 전체 Rules | 개선 10 | confidence 판정 기준 주석 통일 |
| - | `pipeline.py` | - | secondary_to_cardiomegaly, independent 플래그 활용 |
| - | `models.py` | - | ClinicalLogicInput에 original_image_size 추가 |

---

## 건드리지 않는 파일

- `cardiomegaly.py` — 이미 정상 동작
- `pneumothorax.py` — 이미 정상
- `pleural_effusion.py` — 이미 정상
- `pneumonia.py` — 이미 정상
- `lung_lesion.py` — 이미 정상
- `atelectasis.py` — 이미 정상
- `fracture.py` — 이미 정상
- `thresholds.py` — 이전 개선에서 완료
- `pertinent_negatives.py` — 이전 개선에서 완료

---

## 적용 순서

```
Step 1: engine.py 3단계 실행 (개선 1) — 나머지의 전제 조건
Step 2: enlarged_cm.py (개선 2) — Phase 2 의존
Step 3: edema.py (개선 3) — Phase 2 의존
Step 4: lung_opacity.py (개선 4) — Phase 3 의존
Step 5: pleural_other.py (개선 5) — 독립
Step 6: consolidation.py (개선 6) — 독립
Step 7: support_devices.py + models.py (개선 7) — 독립
Step 8: differential.py (개선 8) — engine.py 후처리
Step 9: no_finding.py (개선 9) — 1줄 수정
Step 10: 전체 confidence 주석 통일 (개선 10)
```

---

## 성공 기준

| 기준 | 목표 | 측정 |
|------|------|------|
| 양성 소견 수 | 5~7개 (현재 9개) | 096052b7.jpg 테스트 |
| confidence "low" | 2~3개 | Enlarged_CM, Lung_Opacity, Pleural_Other |
| 감별진단 중복 | 0 (현재 CHF=폐부종 중복) | 출력 확인 |
| Phase 실행 순서 | Phase 1→2→3 보장 | 코드 구조 |
| 기존 테스트 호환 | 깨지면 기대값 업데이트 | 테스트 실행 |
| 응답 시간 | 14초 이내 유지 | /predict 측정 |

---

## 예상 효과

| 항목 | 현재 (1차 개선 후) | 2차 개선 후 |
|------|-------------------|------------|
| 양성 소견 | 9/14 | 5~7/14 |
| Enlarged_CM | 독립 양성 | 동반 소견 (confidence "low") |
| Lung_Opacity | 독립 양성 | 원인 귀속 (confidence "low") |
| Pleural_Other | confidence "medium" | confidence "low" |
| Edema 위치 | "unilateral" (오분류) | "bilateral" (무기폐 보정) |
| 감별진단 | 3개 (중복) | 2개 (CHF 통합 + 무기폐→동반소견) |
| 정상 폐면적비 | 0.80~1.05 | 0.85~1.15 |
