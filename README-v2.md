# Dr. AI Radiologist — v2 아키텍처 고도화 (폐기)

> **상태: 폐기 (Deprecated)**
>
> v2 아키텍처는 설계 의도대로 구현되지 못했습니다.
> 교육 환경(SKKU AWS Academy)의 IAM 권한 제약으로 인해 핵심 AWS 서비스 연동이 불가하여,
> 임시 우회 방식(Lambda Function URL HTTP 직접 호출)으로 동작시켰으나
> 이는 원래 설계 의도와 다르므로 **v2를 폐기하고 v3로 재설계**합니다.

---

## 1. v2 원래 설계 의도

### 1.1 목표
v1의 **7개 Lambda + PyTorch 중복 배포** 문제를 해결하여:

| 항목 | v1 | v2 설계 |
|------|-----|---------|
| Lambda 수 | 7개 (각각 독립) | **2개** (Vision + Analysis) |
| 모델 형식 | PyTorch (~700MB × 3) | **ONNX Runtime** (~45MB × 3) |
| 오케스트레이션 | JS 순차 호출 (브라우저) | **Step Functions** (서버 사이드) |
| 중간 결과 저장 | 없음 (인메모리) | **S3 Claim-Check** 패턴 |
| API 진입점 | Lambda Function URL × 7 | **API Gateway REST** (단일) |
| 동시 요청 격리 | 없음 | **run_id 기반 S3 네임스페이스** |

### 1.2 v2 아키텍처 설계

```
[Browser] → POST /analyze → [API Gateway REST]
                                    │
                              [Step Functions EXPRESS]
                                    │
                    ┌───────────────┼───────────────┐
                    │               │               │
              [Lambda A: seg]  [Lambda A: densenet]  [Lambda A: yolo]
                    │               │               │
                    └───── S3 Claim-Check ──────────┘
                                    │
                              [Lambda B]
                         Clinical Logic → RAG → Bedrock
                                    │
                              S3 최종 리포트
                                    │
                    [API Gateway 응답 → Browser]
```

### 1.3 비동기 폴링 패턴 (Asynchronous Polling)

REST API의 29초 타임아웃 한계를 극복하기 위해 설계:

```
POST /analyze       → Step Functions StartExecution (비동기)
                    → 즉시 200 OK + executionArn 반환 (~0.1초)

GET /analyze/status → DescribeExecution (3초 간격 폴링)
                    → RUNNING / SUCCEEDED / FAILED 상태 반환
                    → SUCCEEDED 시 S3 Claim-Check 결과 수집하여 반환
```

### 1.4 동시 요청 격리 설계

```
사용자 A → Execution-AAA → s3://bucket/runs/Execution-AAA/seg.json
사용자 B → Execution-BBB → s3://bucket/runs/Execution-BBB/seg.json
사용자 C → Execution-CCC → s3://bucket/runs/Execution-CCC/seg.json

run_id = Execution ID → 절대 겹치지 않음
```

---

## 2. 실패 원인 — IAM 권한 제약

### 2.1 SKKU AWS Academy 환경의 제약

교육 환경에서 `aws-say2-11` 사용자에게 다음 권한이 **모두 차단**:

| 차단된 권한 | 영향 |
|------------|------|
| `iam:CreateRole` | 새 IAM 역할 생성 불가 |
| `iam:PutRolePolicy` | 기존 역할에 정책 추가 불가 |
| `iam:AttachRolePolicy` | 관리형 정책 연결 불가 |
| `states:StartExecution` | Step Functions 호출 불가 |
| `states:DescribeExecution` | Step Functions 상태 조회 불가 |
| `lambda:InvokeFunction` | Lambda → Lambda boto3 호출 불가 |
| `s3:PutObject` (Lambda 역할) | S3에 결과 저장 불가 |

### 2.2 사용 가능한 역할의 한계

기존 `say-2-lambda-bedrock-role` (v1에서 사용):
- **있음**: `s3:GetObject`, `bedrock:InvokeModel`, `logs:*`
- **없음**: `s3:PutObject`, `states:*`, `lambda:InvokeFunction`

### 2.3 태그 정책 (SKKU_TagEnforcementPolicy)

Lambda 생성 시 `project=pre-*team` 태그 필수:
- v1은 정책 생성(2025-07) 이전에 배포되어 태그 없이 가능했음
- v2는 `project=pre-6team` 태그 필요

---

## 3. 아키텍처 전환 이력 (3번 실패 → 1번 성공)

| 시도 | 설계 | 결과 | 차단된 권한 |
|:----:|------|:----:|------------|
| 1차 | API Gateway → Step Functions (동기) | **실패** | API GW 29초 타임아웃 |
| 2차 | API Gateway → Step Functions (비동기 폴링) | **실패** | `states:StartExecution` |
| 3차 | Gateway Lambda → Lambda A/B (boto3 invoke) | **실패** | `lambda:InvokeFunction` |
| 4차 | Gateway Lambda → Lambda A/B (**HTTP Function URL**) | **성공** | IAM 불필요 |

### 최종 동작한 구조 (임시 우회)

```
[Browser] → [Gateway Lambda Function URL]
                 │  urllib.request (HTTP POST)
                 ├→ [Lambda A Function URL] × 1 (preprocess)
                 ├→ [Lambda A Function URL] × 3 (seg/densenet/yolo, ThreadPool)
                 └→ [Lambda B Function URL] × 1 (clinical + RAG + bedrock)
              → [Browser 직접 응답]
```

---

## 4. v2에서 달성한 것 / 못한 것

### 달성

| 항목 | 상태 | 비고 |
|------|:----:|------|
| ONNX 변환 (3개 모델) | ✅ | UNet, DenseNet, YOLOv8 |
| 2개 Lambda 통합 | ✅ | Lambda A (Vision), Lambda B (Analysis) |
| E2E 파이프라인 동작 | ✅ | 27~52초 (warm/cold) |
| 테스트 페이지 | ✅ | 다크 테마, v1 기능 계승 |
| Playwright E2E 테스트 | ✅ | 15 테스트 (3 통과, 12 API 배포 후) |
| 5개 임상 테스트 케이스 | ✅ | CHF, Pneumonia, PTX, Normal, Multi |

### 미달성 (원래 설계 대비)

| 항목 | 설계 | 실제 | 이유 |
|------|------|------|------|
| Step Functions 오케스트레이션 | Express 상태 머신 | **Lambda HTTP 직접 호출** | `states:*` 권한 없음 |
| S3 Claim-Check 패턴 | `runs/{run_id}/` 저장 | **인메모리 전달** | `s3:PutObject` 권한 없음 |
| API Gateway REST 진입점 | POST /analyze + GET /status | **Function URL** | Step Functions 연동 불가 |
| 비동기 폴링 패턴 | executionArn + 3초 폴링 | **동기 직접 응답** | Step Functions 미사용 |
| 동시 요청 격리 (S3) | run_id 네임스페이스 | **미구현** | S3 저장 불가 |
| 프로덕션 수준 보안 | API Key, CORS 관리 | **Function URL public** | API GW 미사용 |

---

## 5. 추가 기술적 문제점

### 5.1 Docker 빌드
- Mac M4 (ARM) → `--provenance=false --platform linux/amd64` 필수
- `faiss-cpu==1.7.4` → `>=1.8.0` 버전 변경 필요

### 5.2 ONNX 변환
- UNet: transformers 호환성 문제 → 수동 모듈 로드 필요
- `.onnx.data` 외부 데이터 파일 관리 필요
- opset 17 실패 → opset 18 사용

### 5.3 CORS 헤더 중복
- Function URL 자동 CORS + Lambda 코드 CORS → 중복 → 브라우저 거부
- **해결**: Lambda 코드에서 CORS 헤더 제거, Function URL에 위임

### 5.4 Lambda B 콜드 스타트 (60초+)
- FastEmbed 모델 HuggingFace 다운로드 → Dockerfile 사전 다운로드로 해결
- FAISS 인덱스(183MB) + 메타데이터(176MB) S3 다운로드 → warm 유지 필요

### 5.5 Lambda 응답 크기 (6MB 제한)
- X-Ray 원본(1.9MB) → PNG base64 시 6MB 초과
- JPEG quality=85 + 1024px 리사이즈로 해결

---

## 6. 폐기 결정 및 v3 방향

### 6.1 폐기 이유

1. **원래 설계 의도(Step Functions + Claim-Check)가 구현되지 못함**
2. 임시 우회 방식(Function URL HTTP)은 프로덕션 수준이 아님
3. 동시 요청 격리, 실행 이력 관리, 에러 복구 등 Step Functions의 장점을 활용 못함
4. 코드에 사용하지 않는 모듈이 많이 남아있음 (result_store.py, state_machine.json 등)

### 6.2 v3 방향

v2의 교훈을 반영하여:

1. **IAM 권한 사전 확인** — 설계 전에 가용 권한 목록 작성
2. **Function URL 기반 설계** — Step Functions 대신 Gateway Lambda 오케스트레이션 정식 채택
3. **S3 의존성 최소화** — 모델 로드(GetObject)만 사용, 결과 저장 불필요
4. **Lambda B 분리 고려** — RAG를 별도 Lambda로 분리하여 콜드 스타트 최소화
5. **불필요 코드 제거** — result_store.py, state_machine.json, shared/ 정리

---

## 7. v2 코드 위치 (참고용)

```
forpreproject/
├── deploy/v2/                    # v2 배포 코드 (폐기 대상)
│   ├── lambda_a/                 # Lambda A — Vision Inference (ONNX)
│   ├── lambda_b/                 # Lambda B — Analysis & Report
│   ├── api-gateway/              # Gateway Lambda + API GW 스크립트
│   ├── step_functions/           # Step Functions ASL (미사용)
│   ├── shared/                   # 공용 모듈 (미사용)
│   ├── test-page/                # 테스트 페이지 HTML
│   └── scripts/                  # 배포/변환 스크립트
├── tests/e2e/                    # Playwright E2E 테스트
├── docs/                         # PDCA 문서
│   └── v2-issues-and-lessons.md  # 상세 문제점 기록
└── v1-reference/                 # v1 GitHub 클론
```

---

## 8. 참고 문서

- [v2 문제점 상세 기록](docs/v2-issues-and-lessons.md) — 54개 이슈 카탈로그
- [v2 아키텍처 Plan](docs/01-plan/features/architecture-v2.plan.md)
- [v2 아키텍처 Design](docs/02-design/features/architecture-v2.design.md)
- [v2 테스트 페이지 Plan](docs/01-plan/features/v2-test-page.plan.md)
- [v2 테스트 페이지 Design](docs/02-design/features/v2-test-page.design.md)
