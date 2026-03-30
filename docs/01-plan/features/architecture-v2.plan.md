# Plan: Dr. AI Radiologist 아키텍처 v2 고도화

> 작성일: 2026-03-24
> 레벨: Dynamic
> 상태: Plan

---

## Executive Summary

| 항목 | 내용 |
|------|------|
| **Feature** | Dr. AI Radiologist 아키텍처 v2 고도화 |
| **시작일** | 2026-03-24 |
| **프로젝트 유형** | AWS 인프라 아키텍처 마이그레이션 |

| 관점 | 설명 |
|------|------|
| **Problem** | 기존 7개 Lambda + PyTorch 구조는 모델 700MB × 3벌 중복, HTTP 호출 6회, Function URL 공개 노출 등 비용/성능/보안 문제 존재 |
| **Solution** | 2개 Lambda + ONNX Runtime + Step Functions으로 통합하여 모델 크기 93% 절감, 호출 1회, 오케스트레이션 자동화 |
| **Function UX Effect** | Cold start 시간 대폭 단축, 병렬 추론으로 전체 파이프라인 응답 속도 향상, 안정적인 에러 핸들링 |
| **Core Value** | 비용 절감(ECR/Lambda 수 감소), 유지보수 용이(코드 2곳 집중), 롤백 안전성(v1 공존) |

---

## Context Anchor

| 항목 | 내용 |
|------|------|
| **WHY** | 7개 Lambda의 PyTorch 중복 배포로 인한 비용·성능 비효율을 해소하고, Function URL 공개 노출 보안 문제를 제거한다 |
| **WHO** | 프로젝트 6팀 (의료 AI 흉부 X-Ray 분석 시스템 개발) |
| **RISK** | ONNX 변환 시 추론 정확도 손실 (atol>1e-5), 기존 버킷 오염, Layer 코드 이식 누락 |
| **SUCCESS** | ONNX vs PyTorch 결과 atol≤1e-5, E2E 소견서 정상 생성, v1 엔드포인트 정상 유지 |
| **SCOPE** | deploy/v2/ 하위에 새 구조 생성. 기존 deploy/ 및 7개 Lambda는 절대 수정하지 않음 |

---

## 1. 배경 및 문제 정의

### 1.1 현재 상태 (v1)
- **7개 Lambda**: layer1_segmentation, layer2_detection, layer2b_yolov8, layer3_clinical_logic, layer4_dashboard, layer5_rag, layer6_bedrock_report + integrated_orchestrator
- **모델 배포**: PyTorch .pth/.pt 파일을 각 Lambda Docker 이미지에 포함 (700MB × 3벌)
- **호출 방식**: 통합 오케스트레이터가 HTTP로 각 Lambda Function URL을 순차 호출 (6회)
- **보안**: Function URL이 공개 노출 상태

### 1.2 문제점
1. **비용**: PyTorch 모델 중복으로 ECR 스토리지·Lambda 메모리 낭비
2. **성능**: HTTP 순차 호출 6회로 지연 누적, Cold start 시 PyTorch 로딩 느림
3. **보안**: Function URL 공개로 인증 없이 외부 접근 가능
4. **유지보수**: 7개 Lambda 개별 관리, 코드 분산

### 1.3 목표 상태 (v2)
- **2개 Lambda**: Lambda A (Vision 통합), Lambda B (분석+소견서 통합)
- **모델 배포**: ONNX Runtime (50MB × 1벌), S3에서 Lazy Load + /tmp 캐시
- **호출 방식**: Step Functions가 Lambda A를 병렬 3회 호출 → Lambda B 순차 호출 (1회)
- **보안**: API Gateway + Step Functions (인증 가능)

---

## 2. 요구사항

### 2.1 기능 요구사항

| ID | 요구사항 | 우선순위 | 비고 |
|----|----------|----------|------|
| FR-01 | PyTorch 모델 3개를 ONNX로 변환 (UNet, DenseNet-121, YOLOv8) | **필수** | atol≤1e-5 검증 |
| FR-02 | Lambda A: task 파라미터로 seg/densenet/yolo 분기 추론 | **필수** | ONNX Runtime + S3 Lazy Load |
| FR-03 | Lambda B: L3 임상로직 → L5 RAG → L6 Bedrock 소견서 순차 실행 | **필수** | 기존 코드 100% 이식 |
| FR-04 | Step Functions State Machine으로 전체 파이프라인 오케스트레이션 | **필수** | Parallel + Claim-Check 패턴 |
| FR-05 | Claim-Check 패턴: S3 JSON으로 중간 결과 저장, URI만 전달 | **필수** | 256KB 페이로드 제한 우회 |
| FR-06 | Graceful Degradation: YOLOv8 실패 시 bbox 없이 진행 | **필수** | L1/L2 실패는 파이프라인 중단 |
| FR-07 | S3 Lifecycle Rule: runs/ 경로 7일 후 자동 삭제 | 선택 | 비용 절감 |
| FR-08 | ONNX vs PyTorch 결과 비교 스크립트 | **필수** | 품질 검증 |

### 2.2 비기능 요구사항

| ID | 요구사항 | 기준 |
|----|----------|------|
| NFR-01 | 기존 추론 로직 100% 보존 | torch 호출만 ONNX로 교체, 후처리 동일 |
| NFR-02 | 기존 7개 Lambda 무수정 | deploy/v2/에 새로 생성 |
| NFR-03 | 기존 엔드포인트 유지 | v1 롤백 가능 상태 유지 |
| NFR-04 | 기존 S3 버킷 읽기 전용 | say1-pre-project-1~7 쓰기 절대 금지 |
| NFR-05 | ResultStore 인터페이스 추상화 | save()/load() — 향후 DynamoDB 전환 가능 |

### 2.3 제약 조건
- **AWS 리전**: ap-northeast-2
- **AWS 계정**: 666803869796
- **S3 버킷**: pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an
- **IAM Role**: say-2-lambda-bedrock-role (기존 역할 활용)
- **Git 전략**: 현재 브랜치에서 v2 브랜치 생성 (feature/architecture-v2 등)

---

## 3. 구현 범위 (7단계)

### 3.1 0단계: Git 브랜치 전략
- 현재 작업 브랜치에서 v2 브랜치 생성
- `deploy/v2/` 디렉토리에 새 구조 생성
- 기존 `deploy/` 폴더는 그대로 유지

### 3.2 1단계: ONNX 모델 변환
- `deploy/v2/scripts/convert_to_onnx.py` 작성
- 3개 모델 변환: UNet (세그멘테이션), DenseNet-121 (14질환 분류), YOLOv8 (객체 탐지)
- 변환 후 PyTorch vs ONNX 동일성 검증 (atol≤1e-5)
- 변환된 ONNX 모델을 S3 `models/onnx/` 경로에 업로드
- **예상 모델 크기**: UNet ~85MB, DenseNet ~27MB, YOLOv8 ~22MB (총 ~134MB, 기존 대비 93% 절감)

### 3.3 2단계: Lambda A (Vision 통합) 구축
- **구조**: `deploy/v2/lambda_a/`
- **핵심 모듈**:
  - `lambda_function.py` — task 분기 핸들러 (seg/densenet/yolo)
  - `model_loader.py` — S3 Lazy Load + /tmp 캐시
  - `inference_seg.py` — Layer 1 세그멘테이션 로직 이식 (CTR, CP angle, 면적비, 중심선 보정)
  - `inference_densenet.py` — Layer 2 DenseNet 로직 이식 (14질환 분류)
  - `inference_yolo.py` — Layer 2b YOLOv8 로직 이식 (객체 탐지 + NMS)
  - `result_store.py` — Claim-Check 패턴 (S3ResultStore)
  - `config.py` — 설정
- **Docker 베이스**: public.ecr.aws/lambda/python:3.12
- **의존성**: onnxruntime, pillow, numpy, boto3

### 3.4 3단계: Lambda B (분석+소견서 통합) 구축
- **구조**: `deploy/v2/lambda_b/`
- **핵심 모듈**:
  - `lambda_function.py` — L3→L5→L6 순차 실행 핸들러
  - `clinical_logic/` — 기존 layer3_clinical_logic 코드 복사 (14개 질환 룰 포함)
  - `rag/` — 기존 layer5_rag 코드 복사 (FAISS + bge)
  - `bedrock_report/` — 기존 layer6_bedrock_report 코드 복사
  - `result_store.py` — Lambda A와 동일한 Claim-Check 모듈
- **처리 흐름**:
  1. Lambda A의 3개 결과 URI 수신 (Claim-Check)
  2. S3에서 Vision 결과 로드
  3. L3 임상 로직 엔진 실행
  4. L5 RAG 검색
  5. L6 Bedrock 소견서 생성
  6. 최종 결과 S3 저장 + 반환
- **에러 핸들링**: L1/L2 실패 → 중단, L2b(YOLO) 실패 → bbox 빈 배열로 계속

### 3.5 4단계: Step Functions State Machine
- **ASL 정의**: `deploy/v2/step_functions/state_machine.json`
- **상태 흐름**:
  1. `PreprocessInput` — base64 이미지를 S3에 저장, URI 변환
  2. `ParallelVisionInference` — Lambda A × 3 병렬 호출 (seg, densenet, yolo)
  3. `AnalysisAndReport` — Lambda B 호출 (L3→L5→L6)
- **에러 처리**: 각 Branch에 Retry (3회) + Catch → Fallback 상태
- **타입**: EXPRESS (동기 실행)
- **run_id**: Step Functions Execution ID 활용

### 3.6 5단계: ECR 빌드 + 배포
- Lambda A ECR 이미지 빌드 및 Push
- Lambda B ECR 이미지 빌드 및 Push
- Lambda 함수 생성 (dr-ai-v2-lambda-a, dr-ai-v2-lambda-b)
- Step Functions State Machine 배포

### 3.7 6단계: 테스트
- **단위 테스트**: Lambda A task별 개별 호출 (seg, densenet, yolo)
- **Lambda B 테스트**: 모의 결과 URI로 단독 호출
- **E2E 테스트**: Step Functions 전체 파이프라인 (CHF 시나리오 등)
- **ONNX vs PyTorch 비교**: 동일 이미지로 기존 Lambda와 새 Lambda 결과 비교

### 3.8 7단계: S3 Lifecycle + IAM
- S3 Lifecycle Rule: `runs/` 경로 7일 후 자동 삭제
- IAM 권한 추가: states, lambda:Invoke, s3, bedrock

---

## 4. 기술 아키텍처 요약

### 4.1 v1 → v2 비교

| 항목 | v1 (기존) | v2 (목표) |
|------|-----------|-----------|
| Lambda 수 | 7개 + 오케스트레이터 | 2개 (A + B) |
| ECR 리포지토리 | 7개 | 2개 |
| 모델 포맷 | PyTorch (.pth, .pt) 700MB×3 | ONNX (.onnx) ~134MB 총합 |
| 호출 방식 | HTTP Function URL 6회 순차 | Step Functions 1회 (병렬 포함) |
| 엔드포인트 | Function URL (공개) | API Gateway + Step Functions |
| 에러 핸들링 | 수동 | Step Functions Retry/Catch |
| 중간 결과 전달 | HTTP 응답 본문 | Claim-Check (S3 JSON + URI) |

### 4.2 데이터 흐름

```
Client → API Gateway → Step Functions
  ├─ PreprocessInput (base64 → S3 URI)
  ├─ ParallelVisionInference
  │   ├─ Lambda A (task=seg)     → S3 결과 저장 → URI
  │   ├─ Lambda A (task=densenet) → S3 결과 저장 → URI
  │   └─ Lambda A (task=yolo)    → S3 결과 저장 → URI
  └─ AnalysisAndReport
      └─ Lambda B (L3→L5→L6)    → 최종 소견서
```

### 4.3 주요 패턴
- **Claim-Check**: S3 JSON으로 중간 결과 저장, URI만 Step Functions에 전달 (256KB 제한 우회)
- **Lazy Load + Cache**: ONNX 모델을 S3에서 /tmp로 다운로드, Warm start 시 0초 로드
- **Graceful Degradation**: YOLOv8 실패 시 bbox 없이 진행 (L1/L2는 필수)
- **ResultStore 추상화**: save()/load() 인터페이스로 향후 DynamoDB 전환 가능

---

## 5. 구현 순서 및 의존성

```
0단계: Git 브랜치
  ↓
1단계: ONNX 변환 + S3 업로드
  ↓
2단계: Lambda A 구축  ←──── 기존 L1/L2/L2b 코드 참조
  ↓
3단계: Lambda B 구축  ←──── 기존 L3/L5/L6 코드 복사
  ↓
4단계: Step Functions ASL 작성
  ↓
5단계: ECR 빌드 + 배포 (Lambda A → Lambda B → Step Functions)
  ↓
6단계: 테스트 (단위 → E2E → ONNX 비교)
  ↓
7단계: S3 Lifecycle + IAM 정리
```

---

## 6. 리스크 및 대응

| 리스크 | 영향 | 대응 |
|--------|------|------|
| ONNX 변환 시 정확도 손실 | 진단 결과 불일치 | atol≤1e-5 검증 필수, 실패 시 해당 모델만 PyTorch 유지 |
| Layer 1 후처리 이식 누락 (CTR, CP angle 등) | 세그멘테이션 결과 불완전 | 기존 코드 라인별 대조 이식, E2E 결과 비교 |
| Lambda /tmp 용량 초과 (512MB) | 모델 로드 실패 | 3개 모델 총합 ~134MB로 충분 (여유 378MB) |
| Step Functions 256KB 페이로드 초과 | 실행 실패 | Claim-Check 패턴으로 S3에 저장, URI만 전달 |
| 기존 S3 버킷 오염 | 데이터 손실 | say1-pre-project-1~7 쓰기 절대 금지 룰 적용 |
| Cold start 지연 | 응답 시간 증가 | ONNX 경량화로 PyTorch 대비 크게 개선됨 |

---

## 7. 성공 기준

| 기준 | 측정 방법 |
|------|-----------|
| ONNX 변환 정확도 | 3개 모델 모두 PyTorch 대비 atol≤1e-5 |
| E2E 파이프라인 정상 | CHF 시나리오로 소견서 정상 생성 확인 |
| 기존 시스템 무영향 | v1 엔드포인트 정상 동작 확인 |
| 모델 크기 절감 | 700MB×3 → ~134MB 총합 (93% 절감) |
| Lambda 수 감소 | 7개 → 2개 |
| Claim-Check 정상 | S3 중간 결과 저장/로드 정상 |
| Graceful Degradation | YOLO 실패 시에도 소견서 정상 생성 |

---

## 8. 절대 주의사항

1. **say1-pre-project-1 ~ say1-pre-project-7 버킷**: 읽기 전용, 쓰기 절대 금지
2. **기존 7개 Lambda**: 코드 수정 절대 금지 (참조만 가능)
3. **기존 엔드포인트**: 삭제 금지 (v2 검증 완료 전까지 유지)
4. **추론 로직**: torch 호출만 ONNX로 교체, 나머지 전처리/후처리는 100% 동일하게 이식
5. **모델 변환 후**: 반드시 동일 이미지로 PyTorch vs ONNX 결과 비교 검증
