# Emergency Multimodal Diagnostic Orchestrator

> 응급 상황에서 환자의 골든타임 확보와 응급의학 의료진 간의 경력 편차를 줄이기 위한 **능동형 멀티모달 진단 보조 및 자동 소견 생성 서비스**

[![AWS](https://img.shields.io/badge/AWS-Serverless-orange)](https://aws.amazon.com/)
[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

## 🎯 시스템 개요

### 핵심 목적
- 🚑 **응급 환자의 골든타임 확보**: 능동적 검사 선택으로 진단 시간 단축
- 👨‍⚕️ **의료진 간 경력 편차 최소화**: AI 기반 의사결정 지원
- 🔬 **멀티모달 진단 보조**: CXR, ECG, Blood Lab 통합 분석
- 📋 **자동 소견서 생성**: RAG 기반 임상 리포트 자동 생성

### 기술 스택
- **인프라**: AWS Serverless (Lambda, Step Functions, S3, API Gateway)
- **오케스트레이션**: AWS Step Functions (동적 워크플로우)
- **AI/ML**: Amazon Bedrock (Claude Sonnet 4.5), FAISS RAG
- **데이터**: MIMIC-NOTE, MIMIC-CXR radiology notes

## 🏗️ 아키텍처

### 시스템 흐름도

```
┌─────────────────────────────────────────────────────────────────┐
│                         Client Request                           │
│                    POST /case (Patient Info)                     │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  API Gateway    │
                    │  Case Init      │
                    └────────┬────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────┐
│              Step Functions (Central Orchestrator)              │
│                                                                 │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  Iteration Loop (Max 3회)                            │    │
│  │                                                        │    │
│  │  1. Fusion Decision                                   │    │
│  │     ├─ Chief complaint 분석                           │    │
│  │     ├─ 현재 결과 평가                                  │    │
│  │     └─ 다음 단계 결정                                  │    │
│  │                                                        │    │
│  │  2. Modal Execution (Parallel)                        │    │
│  │     ├─ CXR Connector → CXR Service                    │    │
│  │     ├─ ECG Connector → ECG Service                    │    │
│  │     └─ LAB Connector → LAB Service                    │    │
│  │                                                        │    │
│  │  3. Decision Branch                                   │    │
│  │     ├─ CALL_NEXT_MODALITY → Loop                      │    │
│  │     ├─ NEED_REASONING → Bedrock Reasoning             │    │
│  │     └─ GENERATE_REPORT → Report Generator             │    │
│  └──────────────────────────────────────────────────────┘    │
└────────────────────────────┬───────────────────────────────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ Report Generator│
                    │ (RAG + Bedrock) │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │   S3 Storage    │
                    │   + Response    │
                    └─────────────────┘
```

### 핵심 특징

#### 🔄 능동형 오케스트레이션
- Chief complaint 기반 초기 모달 선택
- 결과에 따라 동적으로 추가 검사 결정
- 고정된 워크플로우가 아닌 **적응형 의사결정**

#### 🎯 반복적 평가 (Iterative Evaluation)
- 각 모달 결과마다 Fusion Decision 수행
- 추가 검사 필요 여부 실시간 판단
- 최대 3회 반복으로 과도한 검사 방지

#### ⚠️ 위험도 기반 의사결정
- 고위험 패턴 감지 시 즉시 LLM 추론 요청
- 신뢰도 낮은 결과에 대해 추가 모달 호출
- 충분한 정보 확보 시 즉시 리포트 생성

## 📁 디렉토리 구조

```
emergency-multimodal-orchestrator/
├── 📄 README.md                         # 이 파일
├── 📄 template.yaml                     # AWS SAM 템플릿
├── 📄 test_request.json                 # 테스트 요청 샘플
├── 📄 example_response.json             # 예상 응답 샘플
│
├── 📂 deploy/                           # 배포 코드
│   ├── 📂 orchestrator/                 # 중앙 오케스트레이션
│   │   ├── case_init/                   # API 진입점
│   │   ├── fusion_decision/             # 의사결정 엔진 ⭐
│   │   └── bedrock_reasoning/           # LLM 추론
│   │
│   ├── 📂 report_generator/             # 소견서 생성
│   │   ├── rag/                         # FAISS RAG
│   │   └── bedrock_report/              # Bedrock 리포트
│   │
│   ├── 📂 modal_connectors/             # 모달 연동 어댑터
│   │   ├── cxr_connector/               # CXR 연동
│   │   ├── ecg_connector/               # ECG 연동
│   │   └── lab_connector/               # LAB 연동
│   │
│   ├── 📂 step_functions/               # Step Functions ASL
│   └── 📂 scripts/                      # 배포 스크립트
│
├── 📂 tests/                            # 테스트
│   ├── local_test.py                    # 로컬 단위 테스트
│   └── full_workflow_simulation.py      # 전체 워크플로우 시뮬레이션
│
└── 📂 docs/                             # 문서
    ├── ARCHITECTURE.md                  # 아키텍처 상세
    ├── MODAL_INTEGRATION.md             # 모달 연동 가이드
    ├── MODAL_INTEGRATION_CXR_ECG.md     # CXR/ECG 통합 가이드
    ├── DECISION_LOGIC.md                # 의사결정 로직
    ├── RAG_SETUP.md                     # RAG 구성
    └── UPGRADE_GUIDE.md                 # ML 모델 업그레이드
```

## 🧩 주요 컴포넌트

### 1️⃣ Central Orchestrator (Step Functions)
**역할**: 전체 워크플로우 제어
- 환자 정보 기반 초기 모달 선택
- 병렬 모달 호출 관리
- 동적 워크플로우 제어 (최대 3회 반복)

### 2️⃣ Fusion Decision Engine ⭐
**역할**: 중앙 의사결정 엔진 (현재 규칙 기반, ML 모델로 교체 가능)

**결정 타입**:
- `CALL_NEXT_MODALITY`: 추가 모달 호출 필요
- `NEED_REASONING`: Bedrock 임상 추론 필요
- `GENERATE_REPORT`: 소견서 생성 준비 완료

**결정 로직**:
```python
# Chief complaint 기반 초기 선택
'chest pain' → ['CXR', 'ECG']
'shortness of breath' → ['CXR', 'ECG']
'fever' → ['LAB', 'CXR']

# 고위험 패턴 감지
CXR(pneumonia) + LAB(elevated WBC) → NEED_REASONING
CXR(cardiomegaly) + ECG(ST elevation) → NEED_REASONING

# 신뢰도 기반
confidence < 0.60 → CALL_NEXT_MODALITY
```

### 3️⃣ Modal Connectors
**역할**: 외부 모달 시스템과의 인터페이스

| Modal | 상태 | 설명 |
|-------|------|------|
| **CXR** | ✅ 연동 가능 | Lambda 기반 Vision Inference + Clinical Logic |
| **ECG** | ✅ 연동 가능 | FastAPI 기반 Mamba S6 + Clinical Logic |
| **LAB** | 🔄 준비 중 | Mock 응답 (실제 시스템 연동 대기) |

### 4️⃣ RAG-based Report Generator
**역할**: 최종 임상 소견서 생성
- MIMIC-NOTE 기반 임상 노트 검색 (FAISS)
- MIMIC-CXR radiology notes 검색
- Bedrock Claude Sonnet 4.5 기반 소견서 생성
- 유사 케이스 참조로 품질 향상

## 📖 문서 가이드

| 문서 | 설명 | 대상 |
|------|------|------|
| **[QUICKSTART.md](QUICKSTART.md)** | 5분 안에 시작하기 | 처음 사용자 |
| **[DEPLOYMENT.md](DEPLOYMENT.md)** | 상세 배포 가이드 | DevOps |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | 시스템 아키텍처 | 개발자 |
| [DECISION_LOGIC.md](docs/DECISION_LOGIC.md) | Fusion Decision 로직 | 개발자 |
| [MODAL_INTEGRATION_CXR_ECG.md](docs/MODAL_INTEGRATION_CXR_ECG.md) | CXR/ECG 통합 | 통합 담당자 |
| [UPGRADE_GUIDE.md](docs/UPGRADE_GUIDE.md) | ML 모델 업그레이드 | ML 엔지니어 |
| [RAG_SETUP.md](docs/RAG_SETUP.md) | RAG 시스템 구성 | 데이터 엔지니어 |

## 🚀 빠른 시작

### Prerequisites

```bash
# 필수 도구
- AWS CLI (configured)
- AWS SAM CLI
- Python 3.12+
- Amazon Bedrock 접근 권한

# 설치 확인
aws --version
sam --version
python --version
```

### 1. 로컬 테스트 (배포 전)

```bash
# 레포 클론
git clone <repository-url>
cd emergency-multimodal-orchestrator

# 로컬 테스트 실행
python tests/local_test.py

# 전체 워크플로우 시뮬레이션
python tests/full_workflow_simulation.py
```

**예상 출력**:
```
============================================================
EMERGENCY MULTIMODAL ORCHESTRATOR - LOCAL TESTS
============================================================

✓ PASS: Chest Pain Patient
✓ PASS: Pneumonia Detection
✓ PASS: Low Confidence Handling
✓ PASS: Normal Findings
✓ PASS: Modal Connectors

Total: 5/5 tests passed
```

### 2. AWS 배포

```bash
# 배포 스크립트 실행
chmod +x deploy/scripts/deploy.sh
./deploy/scripts/deploy.sh
```

**배포 완료 시 출력**:
```
==========================================
Deployment Complete!
==========================================

API Endpoint: https://xxxxx.execute-api.us-east-1.amazonaws.com/v1
Case Bucket: emergency-orchestrator-cases-123456789
State Machine: arn:aws:states:us-east-1:123456789:stateMachine:emergency-orchestration

Test with:
curl -X POST https://xxxxx.execute-api.us-east-1.amazonaws.com/v1/case \
  -H 'Content-Type: application/json' \
  -d @test_request.json
```

### 3. API 테스트

```bash
# 케이스 생성
curl -X POST $API_ENDPOINT/case \
  -H "Content-Type: application/json" \
  -d @test_request.json

# 응답 예시
{
  "case_id": "a1b2c3d4",
  "status": "processing",
  "execution_arn": "arn:aws:states:...",
  "message": "Case initiated. Use GET /case/{case_id} to check status."
}

# 결과 조회
curl -X GET $API_ENDPOINT/case/a1b2c3d4

# 완료 시 응답
{
  "case_id": "a1b2c3d4",
  "status": "completed",
  "result": {
    "report": "...",
    "modalities_used": ["CXR", "ECG", "LAB"],
    "risk_level": "high"
  }
}
```

## 📊 테스트 결과

### 로컬 시뮬레이션 결과

```
Case 1: Acute Inferior STEMI
  Modalities: CXR, ECG
  Iterations: 2
  Final decision: NEED_REASONING
  Risk level: high
  ✓ 고위험 패턴 정확히 감지

Case 2: Community-Acquired Pneumonia
  Modalities: CXR, ECG, LAB
  Iterations: 3
  Final decision: NEED_REASONING
  Risk level: high
  ✓ 능동적 추가 검사 (LAB) 요청

Case 3: Headache - Normal Workup
  Modalities: LAB
  Iterations: 2
  Final decision: GENERATE_REPORT
  Risk level: low
  ✓ 불필요한 검사 없이 효율적 처리
```

## 🔗 모달 연동

### CXR Modal 연동
```bash
# CXR 서비스 엔드포인트 등록
aws ssm put-parameter \
  --name /emergency-orchestrator/cxr-endpoint \
  --value "https://your-cxr-api.com" \
  --type String
```

### ECG Modal 연동
```bash
# ECG 서비스 엔드포인트 등록
aws ssm put-parameter \
  --name /emergency-orchestrator/ecg-endpoint \
  --value "http://your-ecg-service:8000" \
  --type String
```

자세한 내용은 [`docs/MODAL_INTEGRATION_CXR_ECG.md`](docs/MODAL_INTEGRATION_CXR_ECG.md) 참조

## 📚 문서

| 문서 | 설명 |
|------|------|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | 시스템 아키텍처 상세 설명 |
| [DECISION_LOGIC.md](docs/DECISION_LOGIC.md) | Fusion Decision 로직 상세 |
| [MODAL_INTEGRATION.md](docs/MODAL_INTEGRATION.md) | 모달 연동 가이드 |
| [MODAL_INTEGRATION_CXR_ECG.md](docs/MODAL_INTEGRATION_CXR_ECG.md) | CXR/ECG 통합 가이드 |
| [RAG_SETUP.md](docs/RAG_SETUP.md) | RAG 시스템 구성 |
| [UPGRADE_GUIDE.md](docs/UPGRADE_GUIDE.md) | ML 모델 업그레이드 가이드 |
