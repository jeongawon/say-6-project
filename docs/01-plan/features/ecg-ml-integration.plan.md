# ECG ML Integration Planning Document

> **Summary**: Lambda ECG 프로젝트의 ONNX ResNet ML 추론 로직을 v3 K8s ecg-svc에 통합
>
> **Project**: DR-AI v3 (Medical AI CXR/ECG/Blood Analysis)
> **Version**: v3
> **Author**: 프로젝트 6팀
> **Date**: 2026-03-30
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 현재 v3 ecg-svc는 규칙 기반(8모듈)으로 raw ECG 파형을 직접 분석하지 못함. 팀원이 Lambda로 구축한 ONNX ResNet 13-class ML 모델이 별도 프로젝트에 존재하지만, v3 K8s 아키텍처와 통합되지 않은 상태 |
| **Solution** | Lambda ECG의 ML 추론 엔진(inference.py, signal_processing.py)을 v3 ecg-svc에 이식. 모델 로딩은 K8s 볼륨 마운트로 단순화, 임계값은 thresholds.py로 SSOT 분리. 기존 규칙 기반은 폴백으로 유지 |
| **Function/UX Effect** | raw 12-lead ECG signal(.npy) → 13개 병리 자동 분류(STEMI, AFib 등) + 응급 라벨 바이패스 + HR/QTc 자동 계산. 기존 JSON 파라미터 입력도 하위 호환 |
| **Core Value** | ECG 모달을 규칙 기반에서 ML 기반으로 업그레이드하여 13개 병리의 자동 탐지 + 응급 질환 놓침 방지(Emergency Label Bypass) 구현 |

---

## Context Anchor

| Key | Value |
|-----|-------|
| **WHY** | 규칙 기반 ECG 분석은 raw signal 처리 불가, 팀원의 ML 모델은 Lambda에 갇혀 v3와 통합 안 됨 |
| **WHO** | 의료진 (ECG 판독 자동화), 개발팀 (v3 통합 파이프라인 완성) |
| **RISK** | ONNX 모델 파일 확보(S3 접근), Docker 이미지 사이즈 증가(~800MB), hyperkalemia FP 55% |
| **SUCCESS** | /predict에 signal_path 전달 시 ONNX 13-class 추론 성공, 기존 JSON 입력 하위 호환 유지, K8s Pod 정상 Running |
| **SCOPE** | Phase 1~12 (스키마→로직이식→인프라→검증), RAG 인덱스는 후속 작업 |

---

## 1. Overview

### 1.1 Purpose

팀원이 Lambda로 구축한 ECG ONNX ResNet ML 모델(13개 병리 분류)을 v3 K8s 마이크로서비스 아키텍처의 ecg-svc에 통합한다. Lambda 방식(S3 폴백, Mangum, /simulate)을 K8s 네이티브 방식(볼륨 마운트, lifespan 프리로드, readyz 연동)으로 전환한다.

### 1.2 Background

- **v3 ecg-svc 현재**: 규칙 기반 8개 모듈 — 사전 추출된 JSON 파라미터(HR, intervals, amplitudes) 입력 필요
- **Lambda ECG 프로젝트**: ONNX ResNet CNN으로 raw 12-lead signal(12×5000, 500Hz) → 13개 병리 분류
- **gap**: raw signal 처리 불가, ML 추론 엔진 부재, 활력징후 스키마 미확장
- **chest-svc 선례**: ONNX 모델 3개(UNet, DenseNet, YOLOv8) + thresholds.py 분리 + lifespan 프리로드 패턴 이미 적용됨

### 1.3 Related Documents

- 기능 분석: `docs/03-analysis/ecg-lambda-integration.analysis.md` (v2)
- 수정사항: `ECG_INTEGRATION_MODIFICATIONS.md` (7건 전량 반영)
- 소스 프로젝트: `say-6-project-feature-MIMIC-ECG/`
- v3-eks-migration Plan: `docs/01-plan/features/v3-eks-migration.plan.md`

---

## 2. Scope

### 2.1 In Scope

- [x] shared/schemas.py — PatientInfo 활력징후 4개 필드 추가 (Optional, 하위 호환)
- [ ] thresholds.py — 13개 질환 임계값 SSOT 파일 생성 (수정#4)
- [ ] inference.py — ONNX 13-class 추론 엔진 이식 (thresholds.py import)
- [ ] signal_processing.py — HR/QTc 신호 처리 이식 (변경 없이 복사)
- [ ] model_loader.py — K8s 전용 단순화 재작성 (S3 폴백 제거, 수정#2)
- [ ] main.py — lifespan 모델 프리로드 + /predict ML 분기 + readyz 연동 + 조건부 static
- [ ] main.py — /simulate 제거 + Mangum 제거 (수정#3, #7)
- [ ] config.py — model_path=/models/ecg_resnet.onnx (수정#1)
- [ ] requirements.txt — +numpy,scipy,onnxruntime / -mangum,pandas
- [ ] Dockerfile — 의존성 추가, 이미지 최적화
- [ ] K8s manifest — /models subPath 마운트 + 리소스 상향 (수정#1)
- [ ] 모델 파일 배치: v3/models/ecg-svc/ecg_resnet.onnx
- [ ] 테스트 UI: tests/v3/ecg-svc/static/index.html (수정#5)
- [ ] 로컬 K8s 검증 (Docker build → kubectl apply → /predict 테스트)

### 2.2 Out of Scope

- ECG RAG FAISS 인덱스 생성 (후속 작업, 수정#6)
- ONNX 모델 재훈련 (hyperkalemia FP 55% 문제)
- /simulate 엔드포인트 (v3 아키텍처 설계 위반, 수정#3)
- auth-svc / patient-svc (별도 feature)
- central-orchestrator 수정 (하위 호환이므로 불필요)
- EKS 배포 (로컬 K8s 검증까지만)

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | signal_path 포함 요청 시 ONNX 13-class ML 추론 수행 | High | Pending |
| FR-02 | signal_path 미포함 시 기존 규칙 기반 분석 폴백 (하위 호환) | High | Pending |
| FR-03 | lifespan에서 ONNX 모델 프리로드 + readyz 연동 | High | Pending |
| FR-04 | 13개 질환별 커스텀 임계값 + 응급 라벨 바이패스 적용 | High | Pending |
| FR-05 | Raw signal에서 HR/QTc 자동 계산 (scipy R-peak) | Medium | Pending |
| FR-06 | PatientInfo 활력징후 4개 필드 하위 호환 추가 | Medium | Pending |
| FR-07 | 임계값 thresholds.py SSOT 분리 | Medium | Pending |
| FR-08 | 테스트 대시보드 UI (tests/ 분리, 조건부 서빙) | Low | Pending |
| FR-09 | Pertinent negatives + suggested_next_actions 지원 | Medium | Pending |
| FR-10 | metadata에 hr, qtc, inference_time_ms 포함 | Low | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| Performance | ONNX 추론 < 500ms (CPU, 모델 로드 후) | metadata.inference_time_ms 확인 |
| Performance | 첫 요청 지연 없음 (lifespan 프리로드) | readyz 200 후 첫 요청 응답시간 |
| Compatibility | 기존 central-orchestrator 호출 변경 없음 | signal_path 없이 기존 JSON 요청 정상 처리 |
| Reliability | Pod readyz가 모델 로딩 전 503 리턴 | K8s readiness probe 테스트 |
| Size | Docker 이미지 < 1GB | docker images 확인 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] ONNX 13-class 추론이 /predict 엔드포인트에서 정상 동작
- [ ] 기존 규칙 기반 요청이 하위 호환으로 동작
- [ ] K8s Pod Running + readyz 200 (모델 로드 후)
- [ ] 전 서비스 (chest/ecg/blood/orchestrator/rag/report) 정상 동작 확인
- [ ] thresholds.py에 13개 임계값 분리
- [ ] /simulate, Mangum, pandas 완전 제거

### 4.2 Quality Criteria

- [ ] shared/schemas.py 변경이 타 서비스에 영향 없음 (Optional 필드)
- [ ] 모델 파일 부재 시 명확한 에러 메시지 (FileNotFoundError)
- [ ] ONNX 추론 결과가 Lambda 프로젝트와 동일 (동일 신호 → 동일 findings)
- [ ] Docker 이미지 빌드 성공 (scipy 의존성 포함)

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| ONNX 모델 파일 S3 접근 불가 | High | Low | S3 `say2-6team` 접근 확인, 로컬 복사 미리 준비 |
| 테스트 신호(.npy) 파일 부재 | Medium | Medium | Lambda 프로젝트 test-samples/ 에서 복사 |
| Docker 이미지 ~800MB | Medium | High | 멀티스테이지 빌드 + .dockerignore |
| scipy slim 이미지 빌드 실패 | Medium | Medium | python:3.11 (non-slim) 또는 빌드 의존성 추가 |
| hyperkalemia FP 55% | Low | High | 알려진 모델 한계 — 임계값 조정 또는 재훈련 (후속) |
| ECG RAG 인덱스 부재 | Low | High | Bedrock 소견서 RAG 부분만 빈 결과, 기능 자체 정상 |
| ONNX CPU 추론 느림 | Low | Low | metadata.inference_time_ms로 모니터링 |

---

## 6. Impact Analysis

### 6.1 Changed Resources

| Resource | Type | Change Description |
|----------|------|--------------------|
| `v3/shared/schemas.py` | Schema | PatientInfo에 Optional 활력징후 4필드 추가 |
| `v3/services/ecg-svc/main.py` | API | lifespan 프리로드 + ML/규칙 분기 + /simulate 제거 |
| `v3/services/ecg-svc/config.py` | Config | model_path, signal_bucket 추가 |
| `v3/services/ecg-svc/requirements.txt` | Deps | +3 패키지, -2 패키지 |
| `v3/services/ecg-svc/Dockerfile` | Build | 의존성 + 이미지 최적화 |
| `v3/k8s/base/ecg-svc.yaml` | K8s | 리소스 상향 + /models subPath |

### 6.2 Current Consumers

| Resource | Operation | Code Path | Impact |
|----------|-----------|-----------|--------|
| shared/schemas.py (PatientInfo) | CREATE | central-orchestrator → PredictRequest 생성 | ✅ None (Optional 필드) |
| shared/schemas.py (PatientInfo) | READ | chest-svc/ecg-svc/blood-svc → patient_info 참조 | ✅ None (Optional 필드) |
| ecg-svc /predict | POST | central-orchestrator → modal_client.predict("ecg") | ✅ None (signal_path 없으면 폴백) |
| ecg-svc /readyz | GET | K8s readiness probe | ✅ 동작 변경 — 모델 로드 전 503 (의도된 변경) |
| ecg-svc /healthz | GET | K8s liveness probe | ✅ None (변경 없음) |

### 6.3 Verification

- [ ] central-orchestrator → ecg-svc 기존 JSON 요청 정상 처리
- [ ] shared/schemas.py 변경 후 전 서비스 Docker 빌드 성공
- [ ] ecg-svc Pod readyz → 200 (모델 로드 후)
- [ ] chest-svc, blood-svc 기존 동작 영향 없음

---

## 7. Architecture Considerations

### 7.1 Project Level Selection

| Level | Characteristics | Recommended For | Selected |
|-------|-----------------|-----------------|:--------:|
| **Starter** | Simple structure | Static sites, portfolios | ☐ |
| **Dynamic** | Feature-based modules, BaaS integration | Web apps with backend, SaaS MVPs | ☐ |
| **Enterprise** | Strict layer separation, microservices | High-traffic, complex architectures | ☑ |

### 7.2 Key Architectural Decisions

| Decision | Options | Selected | Rationale |
|----------|---------|----------|-----------|
| ML Runtime | onnxruntime / pytorch / tflite | onnxruntime | Lambda 프로젝트와 동일, CPU 폴백 지원 |
| 모델 로딩 | S3 다운로드 / PV 마운트 / 이미지 내장 | PV 마운트 | K8s 네이티브, S3 권한 불필요 (수정#2) |
| 임계값 관리 | 하드코딩 / 별도 파일 / ConfigMap | thresholds.py | chest-svc 경험 반영, SSOT (수정#4) |
| /simulate | 이식 / 제거 | 제거 | 설계 위반 — orchestrator가 환자 데이터 관리 (수정#3) |
| 규칙 기반 분석 | 제거 / 폴백 유지 | 폴백 유지 | signal_path 없는 요청 하위 호환 |
| 모델 경로 | /mnt/efs / /app/models / /models | /models | 프로젝트 규칙 통일 (수정#1) |
| 테스트 UI | services/ 내부 / tests/ 분리 | tests/ 분리 | v3 cleanup 규칙 (수정#5) |

### 7.3 통합 아키텍처 다이어그램

```
central-orchestrator
    ↓ POST /predict (PredictRequest)
    ↓
ecg-svc (K8s Pod)
    ├─ [lifespan] ONNX 모델 프리로드 → readyz 200
    │
    ├─ signal_path 있음?
    │   ├─ YES → load_signal(.npy) → normalize → ONNX inference
    │   │         → thresholds 판정 → emergency bypass
    │   │         → HR/QTc 계산 (scipy) → findings + metadata
    │   └─ NO  → analyzer.analyze_ecg(JSON) → findings (폴백)
    │
    ├─ Bedrock 한국어 소견서 생성 (유지)
    │
    └─ PredictResponse { findings, summary, report, risk_level, metadata }
         ↓
central-orchestrator → 결과 누적 → 다음 모달
```

---

## 8. Convention Prerequisites

### 8.1 Existing Project Conventions

- [x] 서비스 구조: `v3/services/{svc}/main.py` + `config.py` + `Dockerfile`
- [x] 공유 스키마: `v3/shared/schemas.py`
- [x] K8s: `v3/k8s/base/` + `overlays/local/`
- [x] 모델 경로: `/models` (PV 마운트)
- [x] 테스트 UI: `tests/v3/{svc}/static/` (조건부 서빙)
- [x] 임계값: 별도 파일 분리 (chest-svc thresholds.py 선례)

### 8.2 Environment Variables Needed

| Variable | Purpose | Scope | To Be Created |
|----------|---------|-------|:-------------:|
| `MODEL_PATH` | ONNX 모델 파일 경로 | ecg-svc | ☑ |
| `SIGNAL_BUCKET` | ECG 신호 S3 버킷 | ecg-svc | ☑ |
| `BEDROCK_REGION` | Bedrock 리전 | 공통 (기존) | ☐ 기존 |
| `BEDROCK_MODEL_ID` | Bedrock 모델 ID | 공통 (기존) | ☐ 기존 |

---

## 9. Implementation Phases

| Phase | 작업 | 수정사항 | 예상 시간 |
|-------|------|----------|----------|
| 1 | shared/schemas.py 활력징후 추가 | — | 5분 |
| 2 | thresholds.py 생성 (임계값 SSOT) | #4 | 10분 |
| 3 | inference.py 이식 + thresholds import | #4 | 25분 |
| 4 | signal_processing.py 이식 | — | 5분 |
| 5 | model_loader.py 단순화 재작성 | #2 | 10분 |
| 6 | main.py 통합 (lifespan+ML분기+static+제거) | #1,3,5,7 | 20분 |
| 7 | config.py + requirements + Dockerfile | #1 | 15분 |
| 8 | 모델 파일 배치 (v3/models/ecg-svc/) | #1 | 10분 |
| 9 | K8s manifest 수정 | #1 | 10분 |
| 10 | Mangum 잔여 코드 확인 | #7 | 5분 |
| 11 | 테스트 UI 배치 | #5 | 5분 |
| 12 | 로컬 K8s 검증 | — | 20분 |
| (후속) | ECG RAG 인덱스 생성 | #6 | 별도 |
| **합계** | | | **~140분** |

---

## 10. Next Steps

1. [ ] Design 문서 작성 (`ecg-ml-integration.design.md`)
2. [ ] Implementation 진행 (Phase 1~12)
3. [ ] Gap Analysis (Design vs 구현 비교)
4. [ ] ECG RAG 인덱스 후속 작업 계획

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-30 | 초안 — 분석서(v2) 기반 Plan 수립, 수정사항 7건+lifespan 반영 | 프로젝트 6팀 |
