# 통합 오케스트레이터 — Gap 분석 보고서 v3

> **Feature**: integrated-orchestrator
> **Design Reference**: `docs/02-design/features/integrated-orchestrator.design.md`
> **Analysis Date**: 2026-03-23
> **Match Rate**: 98%
> **Iteration**: v3 (v1: 92% → v2: 96% → v3: 98%)

---

## 1. Executive Summary

| 항목 | 값 |
|------|-----|
| 총 검증 항목 | 48개 |
| 일치 | 47개 (98%) |
| 미일치 (코스메틱) | 1개 (2%) |
| Critical Gap | 0개 |

이전 v2 분석 대비 주요 개선:
- **Layer 2b (YOLOv8) 통합 완료**: 백엔드 + 프론트엔드 12개 터치포인트 모두 구현
- **Layer 1 마스크 L/R 보정 완료**: 중심선 기반 교차 픽셀 재분류 적용

---

## 2. 이전 GAP 해결 현황

| GAP ID | 설명 | 상태 |
|--------|------|------|
| GAP-01 | Layer 2b가 orchestrator.py 병렬 실행에 미포함 | **RESOLVED** |
| GAP-02 | S3 테스트 케이스 시 원본 CXR 이미지 미표시 | **RESOLVED** (v2) |
| GAP-03 | Anatomy measurements UI 미표시 | **RESOLVED** (v2) |

---

## 3. Layer 2b 통합 검증 (신규)

### 3.1 백엔드 (orchestrator.py)

| 검증 항목 | 파일:라인 | 상태 |
|-----------|----------|------|
| ThreadPoolExecutor max_workers=3 | orchestrator.py:45 | ✅ |
| call_layer2b 병렬 submit | orchestrator.py:52 | ✅ |
| layer2b 결과 수집 및 저장 | orchestrator.py:54-73 | ✅ |
| layer2b 실패 시 layers_failed 추가 | orchestrator.py:73 | ✅ |
| _build_layer6_payload에 yolo_detections 전달 | orchestrator.py:236 | ✅ |

### 3.2 백엔드 인프라 (config.py, layer_client.py)

| 검증 항목 | 파일 | 상태 |
|-----------|------|------|
| LAYER2B_URL 환경변수 지원 | config.py:9-10 | ✅ |
| LAYER_TIMEOUTS["layer2b"] = 180 | config.py:14 | ✅ |
| call_layer2b() 메서드 | layer_client.py:31-34 | ✅ |

### 3.3 프론트엔드 (index.html)

| 검증 항목 | 라인 | 상태 |
|-----------|------|------|
| ENDPOINTS에 layer2b URL | ~461 | ✅ |
| Pipeline Progress HTML step-layer2b | ~392 | ✅ |
| 변수 선언 layer2b 포함 | ~601 | ✅ |
| Promise.allSettled 3-way 병렬 (L1+L2+L2b) | ~607-610 | ✅ |
| Layer 2b 실패 시 optional 처리 (throw 안함) | ~636-640 | ✅ |
| buildLayer6Payload에 l2b 파라미터 추가 | ~743 | ✅ |
| yolo_detections: l2b.detections 전달 | ~743 | ✅ |
| resetProgress에 layer2b 포함 | ~766 | ✅ |
| renderLayerDetails에 layer2b 포함 | ~1060 | ✅ |
| renderRawJson에 layer2b 포함 | ~676 | ✅ |

---

## 4. Layer 1 마스크 보정 검증

| 검증 항목 | 파일:라인 | 상태 |
|-----------|----------|------|
| 중심선(midline) 계산 로직 | lambda_function.py:363-368 | ✅ |
| class 2 좌측 → class 1 재분류 | lambda_function.py:371 | ✅ |
| class 1 우측 → class 2 재분류 | lambda_function.py:373 | ✅ |
| R Lung(class 1) 파랑 색상 유지 | lambda_function.py:410 | ✅ |
| L Lung(class 2) 초록 색상 유지 | lambda_function.py:411 | ✅ |
| Heart(class 3) 빨강 색상 유지 | lambda_function.py:412 | ✅ |
| CTR 계산 영향 없음 | lambda_function.py:375-381 | ✅ |

### 4.1 픽셀 분포 테스트 결과

| 테스트 케이스 | Blue(R) LEFT | Blue(R) RIGHT | Green(L) LEFT | Green(L) RIGHT |
|--------------|:----:|:----:|:----:|:----:|
| Multi-finding | 100% | 0% | 1% | 98% |
| CHF | 100% | 0% | 0% | 100% |
| Normal | 100% | 0% | 0% | 100% |

---

## 5. 기존 파이프라인 검증 (유지)

| 검증 항목 | 상태 |
|-----------|------|
| Layer 1 → Layer 2 → Layer 2b 병렬 실행 | ✅ |
| Layer 3: Layer 1+2 의존성 (layer1_ok && layer2_ok) | ✅ |
| Layer 5: Layer 3 의존성 + include_rag 옵션 | ✅ |
| Layer 6: Layer 3 의존성 + Layer 5 선택적 | ✅ |
| _flatten_layer1_for_layer3 키 변환 | ✅ |
| _normalize_layer2_for_layer3 공백→언더스코어 | ✅ |
| _build_summary: detected diseases + risk_level | ✅ |
| _extract_report, _extract_next_actions | ✅ |
| skip_layers 옵션 지원 | ✅ |
| partial 상태 (layers_failed 존재 시) | ✅ |
| 프론트엔드 presigned_url 이미지 표시 | ✅ |
| 프론트엔드 SVG 측정값 오버레이 | ✅ |
| 프론트엔드 마스크 ON/OFF 토글 | ✅ |
| 프론트엔드 측정값 패널 | ✅ |
| Lambda handler GET→HTML, POST→pipeline | ✅ |

---

## 6. 미일치 항목 (코스메틱, 1건)

| ID | 항목 | 설계 | 구현 | 심각도 |
|----|------|------|------|--------|
| CSS-01 | CSS 변수/폰트 미세 차이 | `--bg: #0a0e17`, `--accent: #4A9EFF`, JetBrains Mono | `--bg: #0f1117`, `--accent: #3b82f6`, Segoe UI | Low (코스메틱) |

---

## 7. 권고사항

1. **설계 문서 업데이트 권장**: Section 2.8 의사코드가 아직 2-way 병렬(L1+L2)과 `yolo_detections: []` 하드코딩을 보여줌 → 3-way 병렬(L1+L2+L2b) + 실제 detections 전달로 업데이트
2. **CSS-01은 무시 가능**: 기능에 영향 없는 시각적 미세 차이
3. **Layer 1 마스크 보정 문서화**: 중심선 보정 로직을 API Reference에 반영 권장

---

## 8. 결론

**Match Rate 98%** — Critical gap 0건, Layer 2b 12개 터치포인트 완전 통합, Layer 1 마스크 L/R 보정 완료.
설계 대비 구현 일치율이 90% 이상이므로 **Report 단계 진행 가능**.
