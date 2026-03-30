# Plan: chest-svc-improvement

> chest-svc 파이프라인 개선 — 임계값 최적화 + pertinent negative + 소견서 간결화 + 응답 구조
> 작성일: 2026-03-25
> 근거: CHEST_SVC_IMPROVEMENT_PROMPT.md (논문 리서치 + 파이프라인 디버그 분석)
> PDCA Phase: Plan

---

## Executive Summary

| 관점 | 내용 |
|------|------|
| **Problem** | 14개 질환 중 11개가 양성(0.5 일괄 임계값), Bedrock 소견서 48.7초(출력 3393 토큰), 음성 소견 미정리 |
| **Solution** | 질환별 최적 임계값(문헌 기반) + pertinent negative + 모달별 간결 소견서(max 1024 토큰) |
| **Function UX Effect** | 과탐지 감소(11→5~7개), 응답 48초→12초, 오케스트레이터에 필요한 핵심 정보만 전달 |
| **Core Value** | 임상적으로 의미있는 소견만 보고, 실시간에 가까운 응답, 멀티모달 루프에 최적화된 응답 |

---

## Context Anchor

| 항목 | 내용 |
|------|------|
| **WHY** | 과탐지(11/14 양성) + 느린 응답(48초) + 프롬프트 비효율 해결 |
| **WHO** | 박현우 (chest-svc 담당) |
| **RISK** | 임계값 변경으로 진짜 양성을 놓칠 수 있음 → 응급 질환은 낮은 임계값 유지 |
| **SUCCESS** | 양성 5~7개, 응답 15초 이내, pertinent negative 포함 |
| **SCOPE** | chest-svc 내부만 수정 (API Contract 변경 없음) |

---

## 1. 개선 항목

### 개선 1: 질환별 최적 임계값 (thresholds.py)

| 항목 | 현재 | 개선 |
|------|------|------|
| 방식 | 14개 질환 0.5 일괄 (일부 0.25) | 질환별 개별 임계값 (Youden's J 기반) |
| 양성 수 | 11/14 | 예상 5~7/14 |
| 근거 | 없음 | CheXpert/MIMIC-CXR DenseNet-121 논문 |

수정 파일: `layer3_clinical_logic/thresholds.py`

```
임계값 원칙:
- 응급 질환(기흉, 흉수): 낮은 임계값 (놓치면 치명적)
- CTR 교차검증 가능(심비대): 높은 임계값 OK
- 비특이적 소견(Pleural_Other): 0.25→0.60 상향
- CXR 한계 질환(골절): 높은 임계값 (CT 확인 필요)
```

### 개선 2: Pertinent Negative 처리

| 항목 | 현재 | 개선 |
|------|------|------|
| 음성 소견 | 14개 전부 프롬프트에 포함 | 주소증 관련 음성만 포함 |
| 프롬프트 | 모든 소견 나열 | 양성 상세 + pertinent negative 간결 |
| 입력 토큰 | 2,662 | 예상 ~1,500 (40% 감소) |

신규 파일: `layer3_clinical_logic/pertinent_negatives.py`
수정 파일: `report/prompt_templates.py`, `pipeline.py`

### 개선 3: Bedrock 소견서 간결화

| 항목 | 현재 | 개선 |
|------|------|------|
| 출력 형식 | 7섹션 구조화 + narrative + summary + actions | impression + summary + risk + actions |
| max_tokens | 4096 | 1024 |
| 출력 토큰 | 3,393 | 예상 ~800 |
| 소요 시간 | 48.7초 | 예상 ~12초 |

수정 파일: `report/prompt_templates.py`, `report/chest_report_generator.py`, `config.py`

### 개선 4: /predict 응답 구조 정리

| 항목 | 현재 | 개선 |
|------|------|------|
| findings | 14개 전체 (음성 포함) | 양성만 + pertinent_negatives 별도 필드 |
| risk_level | metadata 내부 | 최상위로 이동 |
| suggested_next_actions | 없음 | 최상위에 추가 |
| report | 장문 narrative | 간결 impression |

수정 파일: `pipeline.py`, `main.py`

---

## 2. 수정 파일 목록

| # | 파일 | 작업 | 우선순위 |
|---|------|------|----------|
| 1 | `layer3_clinical_logic/thresholds.py` | OPTIMAL_THRESHOLDS 교체 | P0 |
| 2 | `layer3_clinical_logic/pertinent_negatives.py` | 신규 생성 | P0 |
| 3 | `layer3_clinical_logic/engine.py` | 새 임계값 + pertinent negative 적용 | P0 |
| 4 | `report/prompt_templates.py` | 간결 소견서 프롬프트로 교체 | P0 |
| 5 | `report/chest_report_generator.py` | 간결 응답 파싱 | P0 |
| 6 | `config.py` | bedrock_max_tokens 4096→1024 | P0 |
| 7 | `pipeline.py` | 응답 구조 변경 + pertinent negative 포함 | P0 |
| 8 | `static/index.html` | 새 응답 구조에 맞춰 렌더링 수정 | P1 |

---

## 3. 성공 기준

| 기준 | 목표 | 측정 |
|------|------|------|
| 양성 소견 수 | 5~7개 (현재 11개) | 테스트 이미지 5장 평균 |
| Bedrock 응답 시간 | 15초 이내 (현재 48초) | /predict 호출 측정 |
| 입력 토큰 | 1,500 이내 (현재 2,662) | Bedrock 로그 |
| 출력 토큰 | 1,000 이내 (현재 3,393) | Bedrock 로그 |
| pertinent negative | 주소증별 2~4개 포함 | 응답 확인 |
| API Contract | 기존 findings 호환 유지 | 오케스트레이터 테스트 |

---

## 4. 적용 순서

```
Step 1: thresholds.py 수정 (즉시 효과 — 과탐지 감소)
Step 2: pertinent_negatives.py 신규 생성
Step 3: engine.py에 새 임계값 + pertinent negative 연결
Step 4: prompt_templates.py 간결 소견서 프롬프트 교체
Step 5: chest_report_generator.py 간결 응답 파싱
Step 6: config.py max_tokens 1024
Step 7: pipeline.py 응답 구조 변경
Step 8: index.html UI 수정
```

---

## 5. 주의사항

- 임계값은 **문헌 기반 참고값** — 반드시 자체 validation set에서 Youden's J 기반 재검증 필요
- 응급 질환(Pneumothorax)은 임계값 0.35로 낮게 유지 — 놓치면 치명적
- 모달별 소견서만 간결화, **report-svc 종합 소견서는 풀 7섹션 유지**
- `compute_optimal_thresholds.py`는 validation prediction 데이터 준비 시 실행
