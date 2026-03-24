# Plan: v2 테스트 페이지 및 테스트 케이스 검증 시스템

> 작성일: 2026-03-24
> 레벨: Dynamic
> 상태: Plan
> Feature: v2-test-page

---

## Executive Summary

| 항목 | 내용 |
|------|------|
| **Feature** | v2 테스트 페이지 및 테스트 케이스 검증 |
| **시작일** | 2026-03-24 |
| **예상 산출물** | 테스트 페이지 HTML + API Gateway + 테스트 케이스 검증 |

### Value Delivered

| 관점 | 내용 |
|------|------|
| **Problem** | v2 Step Functions 파이프라인에 외부 진입점이 없어 브라우저에서 E2E 테스트 불가. v1 테스트 페이지는 6개 Lambda Function URL 직접 호출이라 v2 아키텍처와 호환되지 않음 |
| **Solution** | API Gateway → Step Functions (Express) 동기 호출 진입점 구성 + v1 UI/UX를 계승한 단일 페이지 테스트 도구 |
| **Function UX Effect** | 테스트 케이스 선택 → 1-click 분석 실행 → 파이프라인 진행 실시간 표시 → 결과 시각화(마스크/YOLO/측정값/리포트) |
| **Core Value** | v2 아키텍처의 E2E 동작 검증, 5개 임상 시나리오별 정확도 확인, v1→v2 기능 패리티 증명 |

---

## Context Anchor

| 항목 | 내용 |
|------|------|
| **WHY** | v2 아키텍처(2 Lambda + Step Functions)가 실제로 동작하는지 E2E 검증이 필요하며, v1 대비 기능 손실이 없음을 증명해야 한다 |
| **WHO** | 프로젝트 6팀 (의료 AI 흉부 X-Ray 분석 시스템) |
| **RISK** | Step Functions Express 동기 호출 29초 타임아웃, CORS 설정 미비, 테스트 이미지 S3 접근 권한 |
| **SUCCESS** | 5개 테스트 케이스 모두 E2E 정상 완료, v1 대비 동일 결과 출력, 파이프라인 진행 시각화 동작 |
| **SCOPE** | `deploy/v2/test-page/` 하위에 신규 생성. API Gateway 인프라 코드 추가. 기존 v2 Lambda/Step Functions 코드는 수정하지 않음 |

---

## 1. 배경 및 문제 정의

### 1.1 현재 상태

**v1 테스트 페이지** (`v1-reference/deploy/chest_modal_orchestrator/index.html`):
- 6개 Lambda Function URL을 브라우저에서 직접 호출
- Layer 1/2/2b 병렬 → Layer 3/5/6 순차 실행
- 5개 임상 시나리오(CHF, Pneumonia, Tension PTX, Normal, Multi-finding)
- S3 presigned URL로 테스트 이미지 로드
- 결과 시각화: 세그멘테이션 마스크, YOLO 바운딩박스, CTR 측정값, 리포트

**v2 아키텍처** (`deploy/v2/`):
- Lambda A (Vision Inference): seg/densenet/yolo 추론
- Lambda B (Analysis & Report): Clinical Logic → RAG → Bedrock Report
- Step Functions: PreprocessInput → ParallelVisionInference(3 branch) → AnalysisAndReport
- Claim-Check 패턴으로 S3 중간 결과 저장
- **외부 진입점 없음** — API Gateway 미구성

### 1.2 문제점

1. v2 파이프라인을 브라우저에서 호출할 수 없음 (API 엔드포인트 없음)
2. v1 테스트 페이지는 개별 Lambda URL 직접 호출이라 v2에서 사용 불가
3. v1→v2 기능 패리티를 검증할 도구가 없음

---

## 2. 목표

### 2.1 핵심 목표

| # | 목표 | 측정 기준 |
|---|------|----------|
| G1 | v2 파이프라인 E2E 호출 가능한 API 엔드포인트 구성 | API Gateway → Step Functions 동기 호출 성공 |
| G2 | v1 기능을 계승한 v2 테스트 페이지 | 5개 테스트 케이스 실행 + 결과 시각화 |
| G3 | 테스트 케이스별 검증 | 각 시나리오의 예상 위험도(ROUTINE/URGENT/CRITICAL) 매칭 확인 |

### 2.2 비목표 (Out of Scope)

- 프로덕션 수준의 인증/인가 (Cognito, API Key 등)
- v1 테스트 페이지 수정
- v2 Lambda/Step Functions 코드 변경
- 모바일 반응형 최적화

---

## 3. 요구사항

### 3.1 기능 요구사항

#### FR-01: API Gateway 진입점
- REST API Gateway 생성 (POST `/analyze`)
- Step Functions Express 동기 호출 (StartSyncExecution)
- CORS 허용 (브라우저 직접 호출)
- 요청 본문: `{ "image_base64": "...", "patient_info": {...} }`
- 응답: Step Functions 실행 결과 (최종 리포트 포함)
- 타임아웃: API Gateway 29초, Step Functions Express 5분

#### FR-02: 테스트 페이지 UI
v1 기능 이식 (단일 HTML 파일):

| UI 컴포넌트 | v1 기능 | v2 구현 |
|-------------|---------|---------|
| 테스트 케이스 선택 | 5개 버튼 + Upload | 동일 유지 |
| 이미지 뷰어 | 원본 + 마스크 오버레이 + YOLO 박스 | 동일 유지 |
| 측정값 패널 | CTR, 해부학적 측정값 | 동일 유지 |
| 파이프라인 진행 | 6개 레이어 개별 표시 | v2 단계 표시 (Preprocess → Parallel Inference → Analysis & Report) |
| 임상 요약 | 질환 태그 + 위험도 배지 | 동일 유지 |
| Bedrock 리포트 | 전체 소견서 표시 | 동일 유지 |
| Layer 상세 | 각 레이어 아코디언 | v2 구조에 맞게 재구성 |
| Raw JSON | 전체 응답 JSON | Step Functions 최종 결과 JSON |

#### FR-03: 테스트 케이스 5개
v1과 동일한 5개 임상 시나리오:

| 케이스 | 환자 | 예상 위험도 |
|--------|------|------------|
| CHF (심부전) | 72M, 호흡곤란, 하지 부종 | URGENT |
| Pneumonia (폐렴) | 67M, 발열 38.5°C, 기침 | URGENT |
| Tension PTX (긴장성 기흉) | 25M, 교통사고, 좌측 흉통 | CRITICAL |
| Normal (정상) | 35F, 건강검진 | ROUTINE |
| Multi-finding (다중 소견) | 80F, 낙상, COPD | URGENT |

#### FR-04: 테스트 검증 기능
- 각 테스트 케이스의 예상 위험도와 실제 결과 비교
- Pass/Fail 표시
- 전체 테스트 결과 요약 (5/5 passed 등)
- 실행 시간 측정 및 표시

#### FR-05: 테스트 이미지 로드
- S3 presigned URL 방식 (v1과 동일)
- 또는 테스트 이미지를 프로젝트에 포함 (base64 인코딩)
- 커스텀 이미지 업로드도 지원

### 3.2 비기능 요구사항

| # | 요구사항 | 기준 |
|---|---------|------|
| NFR-01 | E2E 응답 시간 | < 60초 (Step Functions Express 최대 5분) |
| NFR-02 | 브라우저 호환 | Chrome, Safari 최신 버전 |
| NFR-03 | 배포 단순성 | 단일 HTML 파일 + deploy.sh 확장 |
| NFR-04 | CORS | 로컬 및 S3 정적 호스팅에서 호출 가능 |

---

## 4. 기술 설계 방향

### 4.1 API 아키텍처 — 비동기 폴링 패턴 (Asynchronous Polling)

REST API의 29초 타임아웃 한계를 극복하기 위해 **비동기 폴링 패턴**을 적용한다.
글로벌 서비스들이 가장 많이 쓰는 표준적인 정석 방식이다.

```
[Browser Test Page]
        |
        | 1. POST /analyze  (이미지 + 환자정보)
        v
[API Gateway (REST)]
        |
        | 2. StartExecution (비동기) → 즉시 200 OK + executionArn 반환 (~0.1초)
        v
[Step Functions]  ──→  [Lambda A x3 parallel] ──→ [Lambda B]
        |
        | 3. GET /analyze/status?id={executionArn}  (3초 간격 폴링)
        v
[Status Lambda]
        |
        | 4-a. RUNNING → { status: "RUNNING" }
        | 4-b. SUCCEEDED → S3 Claim-Check 결과 수집 → enriched 응답 반환
        v
[Browser] ← 전체 결과 수신 → 시각화
```

**엔드포인트 2개:**
- `POST /analyze` → Step Functions StartExecution (비동기) → executionArn 반환
- `GET /analyze/status?id={arn}` → Status Lambda → DescribeExecution + S3 결과 수집

**장점:**
- 서버 리소스 낭비 없음 (비동기 시작 → 폴링 확인)
- 새로고침해도 작업 ID만 있으면 결과 재확인 가능
- 29초 타임아웃 제약 완전 해소
- 포트폴리오 어필: "REST API의 타임아웃 한계를 이해하고, 비동기 폴링 패턴을 직접 구현하여 확장성 있는 아키텍처를 설계"

### 4.2 동시 요청 격리 — run_id 기반 요청 분리

핵심은 **run_id(= Execution ID)로 요청을 격리**하는 것이다.
동시 요청이 들어와도 각 요청은 독립된 Execution으로 생성되어 절대 섞이지 않는다.

**동시 요청 시나리오:**
```
10:00:00  사용자 A 요청 → Execution-AAA 생성 → Lambda A × 3 (seg, densenet, yolo)
10:00:02  사용자 B 요청 → Execution-BBB 생성 → Lambda A × 3
10:00:03  사용자 C 요청 → Execution-CCC 생성 → Lambda A × 3

→ 동시에 Lambda A 인스턴스 9개 실행 (각 3개씩)
```

**S3 결과 저장 — 완전 격리:**
```
사용자 A → s3://bucket/runs/Execution-AAA/seg.json
           s3://bucket/runs/Execution-AAA/densenet.json
           s3://bucket/runs/Execution-AAA/yolo.json
           s3://bucket/runs/Execution-AAA/final_report.json

사용자 B → s3://bucket/runs/Execution-BBB/seg.json
           s3://bucket/runs/Execution-BBB/densenet.json
           ...

사용자 C → s3://bucket/runs/Execution-CCC/seg.json
           ...
```

**격리 보장 원리:**
- `run_id = $$.Execution.Id` (Step Functions가 자동 생성하는 고유 ID)
- 각 Execution은 독립 컨텍스트에서 실행 → Lambda 간 상태 공유 없음
- S3 경로가 `runs/{run_id}/`로 네임스페이스 분리 → 결과 충돌 불가
- Claim-Check 패턴 자체가 요청별 격리를 내장 (run_id가 S3 키의 일부)
- 이 구조는 동기/비동기 관계없이 동일하게 적용됨

### 4.3 API Gateway 설정

```
API Name: dr-ai-radiologist-v2-api
Stage: test

Resources:
  POST /analyze
    Integration: Step Functions StartExecution (AWS Service, 비동기)
    Request Mapping: image_base64 + patient_info → Step Functions input
    Response: executionArn + status: "RUNNING"

  GET /analyze/status
    Integration: Status Lambda (Lambda Proxy)
    Query: id={executionArn}
    Response: status + results (완료 시)

  OPTIONS /analyze, OPTIONS /analyze/status
    Integration: Mock (CORS preflight)

CORS:
  Access-Control-Allow-Origin: *
  Access-Control-Allow-Methods: GET, POST, OPTIONS
  Access-Control-Allow-Headers: Content-Type
```

### 4.3 디렉토리 구조 (신규)

```
deploy/v2/
├─ test-page/
│   ├─ index.html              # v2 테스트 페이지 (단일 파일)
│   └─ test-cases.json         # 5개 테스트 케이스 데이터
│
├─ api-gateway/
│   └─ setup-api-gw.sh         # API Gateway 생성 스크립트
│
└─ scripts/
    └─ deploy.sh               # (기존) + API Gateway 배포 단계 추가
```

### 4.4 v1 → v2 호출 패턴 변환

**v1 (6개 API 순차 호출):**
```javascript
// 병렬: L1, L2, L2b
const [r1, r2, r2b] = await Promise.allSettled([
    callLayer(ENDPOINTS.layer1, imgPayload),
    callLayer(ENDPOINTS.layer2, imgPayload),
    callLayer(ENDPOINTS.layer2b, imgPayload),
]);
// 순차: L3 → L5 → L6
layer3 = await callLayer(ENDPOINTS.layer3, l3payload);
layer5 = await callLayer(ENDPOINTS.layer5, l5payload);
layer6 = await callLayer(ENDPOINTS.layer6, l6payload);
```

**v2 (단일 API 호출):**
```javascript
const result = await fetch(API_GATEWAY_URL + '/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        image_base64: imageBase64,
        patient_info: patientInfo,
    }),
});
// Step Functions가 내부적으로 전체 파이프라인 오케스트레이션
// 응답에 최종 리포트 + 중간 결과 모두 포함
```

---

## 5. 구현 범위

### 5.1 모듈 구성

| # | 모듈 | 산출물 | 의존성 |
|---|------|--------|--------|
| M1 | API Gateway 인프라 | `api-gateway/setup-api-gw.sh` | Step Functions ARN |
| M2 | 테스트 페이지 UI | `test-page/index.html` | API Gateway URL |
| M3 | 테스트 케이스 데이터 | `test-page/test-cases.json` | 테스트 이미지 S3 경로 |
| M4 | deploy.sh 확장 | `scripts/deploy.sh` 수정 | M1 |

### 5.2 구현 순서

```
M1 (API Gateway) → M2 (테스트 페이지) → M3 (테스트 케이스) → M4 (배포 스크립트)
```

---

## 6. 위험 및 대응

| # | 위험 | 영향 | 대응 |
|---|------|------|------|
| R1 | Step Functions Express 동기 호출 타임아웃 (29초 API GW 제한) | 파이프라인 완료 전 타임아웃 | API GW 타임아웃 29초 최대 설정 + 필요시 비동기 폴링 패턴 전환 |
| R2 | CORS 설정 오류 | 브라우저에서 API 호출 실패 | API Gateway CORS 명시 설정 + OPTIONS 메서드 |
| R3 | 테스트 이미지 S3 접근 | presigned URL 만료 | 테스트 이미지를 public-read로 설정하거나 base64 인라인 |
| R4 | v2 Lambda 미배포 상태 | 테스트 불가 | 테스트 페이지에 mock 모드 추가 (로컬 테스트용) |
| R5 | Step Functions 응답에 중간 결과 부재 | 세그멘테이션 마스크 등 시각화 불가 | Lambda B에서 Claim-Check URI를 최종 응답에 포함 → 테스트 페이지에서 S3 직접 로드 |

---

## 7. 성공 기준

| # | 기준 | 검증 방법 |
|---|------|----------|
| SC-01 | API Gateway → Step Functions 비동기 호출 성공 | curl 테스트 |
| SC-02 | 5개 테스트 케이스 전부 E2E 정상 완료 | 테스트 페이지에서 각각 실행 |
| SC-03 | 각 테스트 케이스 예상 위험도 매칭 | CHF→URGENT, Pneumonia→URGENT, PTX→CRITICAL, Normal→ROUTINE, Multi→URGENT |
| SC-04 | 세그멘테이션 마스크 오버레이 표시 | 이미지 뷰어에서 시각적 확인 |
| SC-05 | Bedrock 소견서 정상 출력 | 한국어 임상 소견서 생성 확인 |
| SC-06 | 전체 파이프라인 120초 이내 완료 | Playwright 타이머 + 테스트 페이지 타이머 |

---

## 8. 참조

### 8.1 v1 레퍼런스
- v1 테스트 페이지: `v1-reference/deploy/chest_modal_orchestrator/index.html` (1,125줄)
- v1 테스트 케이스: `v1-reference/deploy/chest_modal_orchestrator/test_cases.py` (5개 시나리오)
- v1 Lambda 엔드포인트: 6개 Function URL (layer1/2/2b/3/5/6)

### 8.2 v2 아키텍처
- Step Functions: `deploy/v2/step_functions/state_machine.json`
- Lambda A: `deploy/v2/lambda_a/lambda_function.py`
- Lambda B: `deploy/v2/lambda_b/lambda_function.py`
- 배포 스크립트: `deploy/v2/scripts/deploy.sh`
- v2 Design 문서: `docs/02-design/features/architecture-v2.design.md`
