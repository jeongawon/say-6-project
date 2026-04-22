# Emergency Multimodal Orchestrator - Architecture

## 시스템 개요

응급 상황에서 환자의 골든타임 확보를 위한 능동형 멀티모달 진단 보조 시스템입니다.

## 핵심 설계 원칙

### 1. 능동형 오케스트레이션 (Active Orchestration)
- 중앙 오케스트레이터가 환자 상태와 초기 결과를 기반으로 다음 검사를 능동적으로 결정
- 고정된 워크플로우가 아닌 동적 의사결정 기반 흐름

### 2. 반복적 평가 (Iterative Evaluation)
- 각 모달 결과를 받을 때마다 Fusion Decision 수행
- 추가 검사 필요 여부를 실시간으로 판단
- 최대 3회 반복으로 과도한 검사 방지

### 3. 위험도 기반 의사결정 (Risk-based Decision Making)
- 고위험 패턴 감지 시 즉시 LLM 추론 요청
- 신뢰도가 낮은 결과에 대해 추가 모달 호출
- 충분한 정보 확보 시 즉시 리포트 생성

## 아키텍처 다이어그램

```
┌─────────────────────────────────────────────────────────────────┐
│                         API Gateway                              │
│                    POST /case, GET /case/{id}                    │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Case Init Lambda                              │
│  - Generate case_id                                              │
│  - Store input in S3                                             │
│  - Start Step Functions                                          │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Step Functions (Orchestrator)                  │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  1. Initialize Workflow                                  │   │
│  │     - Set iteration = 1                                  │   │
│  │     - Initialize empty results                           │   │
│  └─────────────────────────────────────────────────────────┘   │
│                             │                                     │
│                             ▼                                     │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  2. Fusion Decision Lambda                               │   │
│  │     - Analyze current results                            │   │
│  │     - Decide: CALL_NEXT_MODALITY |                       │   │
│  │               NEED_REASONING |                           │   │
│  │               GENERATE_REPORT                            │   │
│  └─────────────────────────────────────────────────────────┘   │
│                             │                                     │
│              ┌──────────────┼──────────────┐                    │
│              ▼              ▼              ▼                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │ CALL_NEXT    │  │ NEED         │  │ GENERATE     │         │
│  │ _MODALITY    │  │ _REASONING   │  │ _REPORT      │         │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘         │
│         │                  │                  │                  │
│         ▼                  ▼                  ▼                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │ Call         │  │ Bedrock      │  │ Report       │         │
│  │ Modalities   │  │ Reasoning    │  │ Generator    │         │
│  │ (Parallel)   │  │ Lambda       │  │ Lambda       │         │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘         │
│         │                  │                  │                  │
│         ▼                  │                  │                  │
│  ┌──────────────┐         │                  │                  │
│  │ Merge        │         │                  │                  │
│  │ Results      │         │                  │                  │
│  └──────┬───────┘         │                  │                  │
│         │                  │                  │                  │
│         └──────────────────┴──────────────────┘                 │
│                             │                                     │
│                             ▼                                     │
│                      (Loop or End)                               │
└─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Modal Connectors                              │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │ CXR          │  │ ECG          │  │ LAB          │         │
│  │ Connector    │  │ Connector    │  │ Connector    │         │
│  │              │  │              │  │              │         │
│  │ → External   │  │ → Mock       │  │ → Mock       │         │
│  │   CXR API    │  │   (준비중)    │  │   (준비중)    │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
└─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Report Generator                              │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  RAG Service (FAISS)                                      │  │
│  │  - MIMIC-NOTE clinical notes                             │  │
│  │  - MIMIC-CXR radiology reports                           │  │
│  │  - Semantic search for similar cases                     │  │
│  └──────────────────────────────────────────────────────────┘  │
│                             │                                     │
│                             ▼                                     │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Bedrock Claude (Sonnet 4.5)                             │  │
│  │  - Generate comprehensive clinical report                │  │
│  │  - Integrate multimodal findings                         │  │
│  │  - Provide actionable recommendations                    │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                         S3 Storage                               │
│  - cases/{case_id}/input.json                                   │
│  - cases/{case_id}/output.json                                  │
└─────────────────────────────────────────────────────────────────┘
```

## 주요 컴포넌트

### 1. Case Init Lambda
**역할**: API 진입점 및 워크플로우 시작
- Case ID 생성
- 입력 데이터 검증 및 S3 저장
- Step Functions 실행 시작
- GET 요청 시 결과 조회

### 2. Fusion Decision Lambda
**역할**: 중앙 의사결정 엔진
- 현재까지의 모달 결과 분석
- 다음 단계 결정:
  - `CALL_NEXT_MODALITY`: 추가 모달 호출 필요
  - `NEED_REASONING`: LLM 추론 필요
  - `GENERATE_REPORT`: 리포트 생성 준비 완료

**결정 로직** (하드코딩):
1. Chief complaint 기반 초기 모달 선택
2. 고위험 패턴 감지 (예: CXR pneumonia + LAB elevated WBC)
3. 신뢰도 임계값 체크 (< 0.60)
4. 현재 결과 기반 추가 검사 제안
5. 복잡도 평가

### 3. Modal Connectors
**역할**: 외부 모달 시스템과의 인터페이스

#### CXR Connector
- 외부 CXR 추론 API 호출
- API 미설정 시 mock 응답 생성
- 표준화된 응답 형식으로 변환

#### ECG Connector (준비 중)
- 현재 mock 응답 제공
- 실제 ECG 시스템 연동 준비

#### LAB Connector (준비 중)
- 현재 mock 응답 제공
- 실제 Lab 시스템 연동 준비

### 4. Bedrock Reasoning Lambda
**역할**: LLM 기반 임상 추론
- 고위험 패턴 감지 시 호출
- 복잡한 케이스에 대한 종합 분석
- 멀티모달 결과의 임상적 의미 해석

### 5. Report Generator Lambda
**역할**: 최종 소견서 생성

**구성 요소**:
- **RAG Service**: FAISS 기반 유사 케이스 검색
- **Bedrock Report**: Claude를 이용한 리포트 생성
- **S3 Storage**: 최종 결과 저장

## 데이터 흐름

### 1. 입력 데이터
```json
{
  "patient": {
    "age": 65,
    "sex": "Male",
    "chief_complaint": "chest pain",
    "vitals": {...},
    "cxr_image_url": "...",
    "ecg_data": {...},
    "lab_data": {...}
  }
}
```

### 2. 모달 응답 형식 (표준화)
```json
{
  "modality": "CXR|ECG|LAB",
  "finding": "진단 결과",
  "confidence": 0.0-1.0,
  "details": {...},
  "rationale": "진단 근거",
  "timestamp": "ISO 8601"
}
```

### 3. Fusion Decision 응답
```json
{
  "decision": "CALL_NEXT_MODALITY|NEED_REASONING|GENERATE_REPORT",
  "next_modalities": ["ECG", "LAB"],
  "rationale": "결정 근거",
  "risk_level": "low|medium|high",
  "confidence_summary": {...}
}
```

### 4. 최종 출력
```json
{
  "case_id": "...",
  "status": "completed",
  "report": "임상 소견서 전문",
  "modalities_used": ["CXR", "ECG", "LAB"],
  "risk_level": "high",
  "timestamp": "..."
}
```

## 확장성 고려사항

### 1. 모달 추가
- 새로운 connector Lambda 추가
- Step Functions에 라우팅 로직 추가
- Fusion Decision에 결정 규칙 추가

### 2. 결정 로직 개선
- 하드코딩 → ML 모델 기반 결정
- 강화학습을 통한 최적 워크플로우 학습

### 3. RAG 확장
- 추가 의료 데이터베이스 통합
- 실시간 문헌 검색 추가

### 4. 성능 최적화
- Lambda 동시성 조정
- Step Functions Express Workflow 고려
- RAG 인덱스 캐싱

## 보안 고려사항

- PHI (Protected Health Information) 암호화
- S3 버킷 암호화 활성화
- IAM 최소 권한 원칙
- VPC 내 Lambda 배포 고려
- CloudWatch Logs 암호화

## 모니터링

- CloudWatch Metrics: Lambda 실행 시간, 에러율
- Step Functions 실행 추적
- X-Ray 분산 추적
- Custom metrics: 모달별 호출 빈도, 평균 처리 시간
