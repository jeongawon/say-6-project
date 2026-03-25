# PDCA Report: chest-svc-improvement

> chest-svc 파이프라인 개선 — 임계값 + pertinent negative + 소견서 간결화 + 응답 구조
> 완료일: 2026-03-25
> 근거: CHEST_SVC_IMPROVEMENT_PROMPT.md (논문 리서치 + 파이프라인 디버그 분석)

---

## Executive Summary

### 1.1 프로젝트 개요

| 항목 | 내용 |
|------|------|
| **Feature** | chest-svc-improvement |
| **PDCA 사이클** | Plan → Do → Check(78%) → Act(버그 3건 수정) → Check(~90%) → Report |
| **Iteration** | 1회 (78% → ~90%) |

### 1.2 결과 요약

| 항목 | Before | After | 개선 |
|------|--------|-------|------|
| Bedrock 응답 시간 | 48.7초 | **13.8초** | **-72%** |
| 출력 토큰 | 3,393 | **781** | **-77%** |
| 입력 토큰 | 2,662 | 2,363 | -11% |
| 양성 소견 수 | 11/14 | 9/14 | -18% |
| risk_level | metadata 내부 | **top-level** | API 개선 |
| pertinent_negatives | 없음 | **["기흉 없음"]** | 신규 기능 |
| suggested_next_actions | 없음 | **5개 조치** | 신규 기능 |
| v1 데드 코드 | 있음 | **삭제** | 정리 |

### 1.3 Value Delivered

| 관점 | 결과 |
|------|------|
| **Problem** | Bedrock 48.7초 → 13.8초로 72% 단축. 과탐지 11→9개 감소 |
| **Solution** | 질환별 최적 임계값 + pertinent negative + 간결 소견서(1024 토큰) + 응답 구조 개선 |
| **Function UX Effect** | 14초 이내 응답으로 실시간 진단 가능. 오케스트레이터에 risk_level+next_actions 직접 전달 |
| **Core Value** | 임상적으로 의미있는 소견만 보고 + 빠른 응답 + 멀티모달 순차 루프에 최적화된 응답 |

---

## 2. 개선 항목별 결과

### 개선 1: 질환별 최적 임계값

| 항목 | 상태 | 상세 |
|------|:----:|------|
| OPTIMAL_THRESHOLDS 14개 질환 | ✅ | 문헌 기반 개별 임계값 적용 |
| Pneumothorax 0.35 (낮은 임계값) | ✅ | 놓치면 치명적 — sensitivity 우선 |
| Pleural_Other 0.25→0.60 | ✅ | 과탐지 방지 |
| Fracture 0.65 | ✅ | CXR 한계 반영 |
| Youden's J TODO 주석 | ✅ | validation set 준비 시 실행 |

**효과**: 양성 11→9개 (목표 5~7보다 높지만 개선됨. validation set 기반 튜닝으로 추가 감소 가능)

### 개선 2: Pertinent Negative

| 항목 | 상태 | 상세 |
|------|:----:|------|
| pertinent_negatives.py 신규 | ✅ | 6개 키워드 (호흡곤란/흉통/발열/기침/외상/default) |
| engine.py 연동 | ✅ | Phase 5로 추가, 결과에 포함 |
| pipeline.py → report_event 전달 | ✅ | Bug 1 수정 완료 |
| Bedrock 프롬프트 포함 | ✅ | "관련 음성 소견" 섹션 추가 |
| API 응답 top-level | ✅ | PredictResponse에 필드 추가 |

**효과**: "호흡곤란" 환자에서 "기흉 없음" 보고 (5개 체크 중 음성 1개)

### 개선 3: Bedrock 소견서 간결화

| 항목 | Before | After |
|------|--------|-------|
| max_tokens | 4,096 | **1,024** |
| 출력 형식 | 7섹션 구조화 + narrative + summary | **impression + summary + risk + actions** |
| 출력 토큰 | 3,393 | **781** |
| 소요 시간 | 48.7초 | **13.8초** |
| 생성 속도 | ~70 tok/s | ~57 tok/s (서울 리전 정상) |

**효과**: 응답 시간 72% 단축. 모달별 소견서는 간결하게, 풀 7섹션은 report-svc 종합 소견서에서 생성

### 개선 4: /predict 응답 구조

| 필드 | Before | After |
|------|--------|-------|
| findings | 14개 전부 | **양성만 (9개)** |
| pertinent_negatives | 없음 | **["기흉 없음"]** |
| risk_level | metadata 내부 | **top-level "critical"** |
| suggested_next_actions | 없음 | **5개 조치 (Bedrock 생성)** |
| report | 장문 narrative | **간결 impression** |

### 개선 5+6: UI + 데드코드 (이전 세션에서 완료)

| 항목 | 상태 |
|------|:----:|
| 마스크 오버레이 연결 | ✅ |
| YOLO bbox 연결 | ✅ |
| 측정값 연결 | ✅ |
| v1 데드코드 삭제 (buildLayer3/6Payload) | ✅ |
| next_actions [object Object] 버그 수정 | ✅ |

---

## 3. 수정 파일 목록

| # | 파일 | 작업 |
|---|------|------|
| 1 | `layer3_clinical_logic/thresholds.py` | OPTIMAL_THRESHOLDS 14개 질환별 임계값 |
| 2 | `layer3_clinical_logic/pertinent_negatives.py` | **신규** — 6개 키워드 pertinent negative |
| 3 | `layer3_clinical_logic/engine.py` | Phase 5 pertinent negative 추가 |
| 4 | `report/prompt_templates.py` | 간결 소견서 프롬프트 (4필드) |
| 5 | `report/chest_report_generator.py` | 간결 응답 파싱 + pertinent neg 전달 |
| 6 | `config.py` | bedrock_max_tokens 4096→1024 |
| 7 | `pipeline.py` | 응답 구조 변경 + pertinent_negatives report_event 전달 |
| 8 | `shared/schemas.py` | PredictResponse에 3개 필드 추가 |
| 9 | `main.py` | 새 필드 전달 |
| 10 | `static/index.html` | next_actions 렌더링 수정 + 데드코드 삭제 |

---

## 4. 실측 데이터 (테스트 이미지: 096052b7.jpg)

```
환자: 67세 남성, 호흡곤란, 고혈압/당뇨

파이프라인 타이밍:
  segmentation:    0.162s
  densenet:        0.046s
  yolo:            0.419s
  clinical_logic:  0.000s
  report (Bedrock): 13.8s
  ─────────────────
  합계:           14.5s

Bedrock 토큰:
  입력: 2,363 tokens
  출력:   781 tokens
  지연:  13.8s

결과:
  risk_level: critical
  양성 소견 9개: Cardiomegaly, Pleural_Effusion, Atelectasis,
    Consolidation, Edema, Enlarged_CM, Fracture, Pleural_Other, Lung_Opacity
  pertinent_negatives: ["기흉 없음"]
  next_actions: 5개 (산소 투여, 심초음파, 혈액검사, 흉부CT, 심장내과 협진)
  impression: CHF 의증, CTR 0.52, 비대칭 폐부종, 우측 무기폐
```

---

## 5. 남은 작업

| 항목 | 우선순위 | 상세 |
|------|----------|------|
| Youden's J 기반 임계값 재계산 | P1 | validation set prediction 준비 시 compute_optimal_thresholds.py 실행 |
| DenseNet 필터를 OPTIMAL_THRESHOLDS와 정렬 | P2 | chest_report_generator.py에서 0.5 하드코딩 → 임계값 참조 |
| 추가 테스트 이미지 검증 | P1 | 5장 전체로 양성 수 평균 확인 |
| 입력 토큰 1,500 목표 | P2 | 음성 소견 프롬프트 완전 제거 시 달성 가능 |

---

## 6. Lessons Learned

| # | 교훈 |
|---|------|
| 1 | **출력 토큰이 병목** — 프롬프트 입력(2,662)이 아니라 출력(3,393)이 시간의 99%를 차지. max_tokens 제한이 가장 효과적 |
| 2 | **PredictResponse 스키마 동기화 필수** — pipeline.py에서 새 필드를 리턴해도 schemas.py에 없으면 직렬화 시 누락 |
| 3 | **pertinent negative는 전달 경로가 길다** — engine → clinical_result → pipeline → report_event → Bedrock. 중간에 한 곳이라도 빠지면 빈 배열 |
| 4 | **문헌 기반 임계값은 시작점** — 실제 모델+데이터셋에서 Youden's J로 최적화해야 정확. 현재는 과탐지 존재 |
