# Dr. AI Radiologist v2 — 아키텍처 고도화

> **Branch**: `feature/MIMIC-CXR-v2`
> **상태**: 폐기 (Deprecated) → v3 재설계 예정
> **기반**: `feature/MIMIC-CXR` (v1)

---

## 프로젝트 개요

흉부 X-Ray AI 분석 시스템의 아키텍처 고도화 시도.
v1의 7개 Lambda + PyTorch 중복 배포를 2개 Lambda + ONNX로 통합하려 했으나,
**교육 환경(SKKU AWS Academy)의 IAM 권한 제약으로 원래 설계대로 구현 실패.**

---

## v1 → v2 변경 목표

| 항목 | v1 | v2 설계 | v2 실제 |
|------|-----|---------|---------|
| Lambda 수 | 7개 | 2개 | 2개 + Gateway 1개 |
| 모델 | PyTorch (~700MB × 3) | ONNX (~45MB × 3) | ONNX 변환 완료 |
| 오케스트레이션 | 브라우저 JS 순차호출 | Step Functions | **Lambda HTTP 직접 호출** |
| 중간 결과 | 인메모리 | S3 Claim-Check | **인메모리 (S3 쓰기 불가)** |
| API 진입점 | Function URL × 7 | API Gateway REST | **Function URL × 3** |

---

## 폐기 사유

### IAM 권한 차단 (교육 환경)

| 차단된 권한 | 영향 |
|------------|------|
| `iam:CreateRole` | 새 역할 생성 불가 |
| `iam:PutRolePolicy` | 기존 역할에 정책 추가 불가 |
| `states:StartExecution` | Step Functions 호출 불가 |
| `lambda:InvokeFunction` | Lambda→Lambda boto3 호출 불가 |
| `s3:PutObject` (Lambda 역할) | Claim-Check 패턴 사용 불가 |

### 아키텍처 전환 (3번 실패 → 1번 성공)

```
1차: API GW → Step Functions (동기)     → 실패 (29초 타임아웃)
2차: API GW → Step Functions (비동기 폴링) → 실패 (states:StartExecution 차단)
3차: Gateway Lambda → Lambda (boto3)     → 실패 (lambda:InvokeFunction 차단)
4차: Gateway Lambda → Lambda (HTTP URL)  → 성공 (IAM 불필요)
```

### 최종 동작한 구조 (임시, 설계 의도와 다름)

```
[Browser] → [Gateway Lambda Function URL]
                 │ urllib HTTP POST
                 ├→ [Lambda A Function URL] preprocess
                 ├→ [Lambda A Function URL] seg/densenet/yolo (ThreadPool 병렬)
                 └→ [Lambda B Function URL] clinical + RAG + bedrock
             → [Browser 직접 응답, 27~52초]
```

---

## 프로젝트 구조

```
.
├── README.md                           # 이 파일
├── deploy/
│   ├── lambda_a/                       # Lambda A — Vision Inference (ONNX)
│   │   ├── Dockerfile
│   │   ├── lambda_function.py          # preprocess/seg/densenet/yolo 핸들러
│   │   ├── model_loader.py             # S3 → /tmp ONNX 모델 로드
│   │   ├── inference_seg.py            # UNet (1ch, 320×320)
│   │   ├── inference_densenet.py       # DenseNet-121 (14질환, 224×224)
│   │   ├── inference_yolo.py           # YOLOv8 (병변 탐지, 1024×1024)
│   │   └── requirements.txt
│   │
│   ├── lambda_b/                       # Lambda B — Analysis & Report
│   │   ├── Dockerfile
│   │   ├── lambda_function.py          # L3→L5→L6 순차 실행
│   │   ├── clinical_logic/             # L3: 14질환 룰 기반 임상 로직
│   │   │   ├── clinical_engine.py
│   │   │   ├── cross_validation.py
│   │   │   └── rules/                  # 14개 질환별 룰
│   │   ├── rag/                        # L5: FAISS + bge-small-en (12.3만건)
│   │   │   ├── rag_service.py
│   │   │   └── query_builder.py
│   │   └── bedrock_report/             # L6: Claude Sonnet 소견서 생성
│   │       ├── report_generator.py
│   │       └── prompt_templates.py
│   │
│   ├── api-gateway/                    # Gateway Lambda
│   │   ├── setup-api-gw.sh            # API GW 스크립트 (미사용)
│   │   └── status-lambda/
│   │       └── status_handler.py       # HTTP 오케스트레이터
│   │
│   ├── shared/                         # 공용 모듈 (미사용)
│   │   ├── config.py
│   │   └── result_store.py             # Claim-Check (S3 쓰기 불가로 미사용)
│   │
│   ├── step_functions/                 # Step Functions (미사용)
│   │   └── state_machine.json          # ASL 정의
│   │
│   ├── test-page/
│   │   ├── index.html                  # v2 테스트 페이지 (1700줄, 다크 테마)
│   │   └── test-cases.json             # 5개 임상 시나리오
│   │
│   └── scripts/
│       ├── deploy_v2.py                # boto3 배포 스크립트
│       ├── deploy.sh                   # bash 배포 (참고용)
│       ├── convert_to_onnx.py          # PyTorch → ONNX 변환
│       └── compare_results.py          # ONNX vs PyTorch 비교
│
├── tests/e2e/                          # Playwright E2E 테스트
│   ├── playwright.config.js
│   ├── v2-pipeline.spec.js             # 6개 테스트 그룹 (15 테스트)
│   └── helpers/api-client.js
│
└── docs/
    ├── 01-plan/features/               # Plan 문서
    ├── 02-design/features/             # Design 문서
    ├── 03-analysis/                    # Gap Analysis
    ├── 04-report/                      # Completion Report
    └── v2-issues-and-lessons.md        # ★ 54개 문제점 상세 기록
```

---

## v2에서 달성한 것

- ONNX 변환 완료 (UNet, DenseNet, YOLOv8)
- 7개 Lambda → 2개 Lambda 통합
- E2E 파이프라인 동작 확인 (27~52초)
- 테스트 페이지 (v1 UI 계승, 다크 테마)
- Playwright 테스트 15개 (UI 3개 통과)
- 5개 임상 테스트 케이스 (CHF, Pneumonia, PTX, Normal, Multi-finding)

---

## v3 방향

1. **IAM 권한 사전 확인** — 설계 전 가용 권한 파악
2. **Function URL 기반** — Step Functions 대신 Gateway Lambda 정식 채택
3. **S3 의존성 최소화** — GetObject만 사용, PutObject 불필요 설계
4. **Lambda B 분리** — RAG 별도 Lambda로 콜드 스타트 최소화
5. **불필요 코드 제거** — result_store.py, state_machine.json 등

---

## 참고

- **v1 코드**: `feature/MIMIC-CXR` 브랜치
- **문제점 상세**: [docs/v2-issues-and-lessons.md](docs/v2-issues-and-lessons.md)
- **v1 DEPLOY_GUIDE**: v1 브랜치의 `deploy/DEPLOY_GUIDE.md` 참조
