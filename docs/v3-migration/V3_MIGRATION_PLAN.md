# Dr. AI Radiologist — v3 EKS 마이그레이션 종합 계획서

> 작성일: 2026-03-25
> 브랜치: mimic-cxr-v3-eks
> 상태: 계획 수립

---

## 1. 프로젝트 개요

### 1-1. 목표

v2(Lambda 7개 개별 배포)에서 v3(EKS 마이크로서비스)로 전환하여, 5명의 팀원이 독립적으로 서비스를 개발하고 통합 오케스트레이터가 LLM 기반 순차 검사 루프를 실행하는 구조를 구축한다.

### 1-2. 팀 구성 (5명)

| 역할 | 담당자 | 서비스 | 설명 |
|------|--------|--------|------|
| 흉부 X-Ray 모달 | 박현우 | chest-svc | 6-Layer CXR 파이프라인 |
| ECG 모달 | 원정아 | ecg-svc | 12-lead 심전도 분석 |
| 혈액검사 모달 | 팀원 C | blood-svc | CBC/BMP/BNP 이상치 판정 |
| 중앙 오케스트레이터 | 팀원 D | central-orchestrator | LLM 순차 루프 + 상태 관리 |
| 중앙 오케스트레이터 | 팀원 E | central-orchestrator | 공유 서비스(rag/report) + 프론트엔드 |

### 1-3. v2 → v3 변경 요약

| 항목 | v2 (현재) | v3 (목표) |
|------|-----------|-----------|
| 컴퓨팅 | Lambda 7개 | EKS Pod (Docker Compose → minikube → EKS) |
| 통신 | Function URL (HTTP, IAM) | K8s Service DNS (IAM/CORS 불필요) |
| 모델 서빙 | Lambda 콜드스타트 | Pod 상시 로딩 (ONNX Runtime) |
| 오케스트레이션 | 단일 모달 파이프라인 | LLM 기반 멀티모달 순차 검사 루프 |
| DB | 없음 | PostgreSQL (환자 기록 + 세션 상태) |
| 캐시 | 없음 | Redis (오케스트레이터 세션) |
| RAG | Lambda 개별 | 공유 서비스 (3개 모달 공유) |
| 소견서 | 모달별 1개 | 모달별 소견서 + 종합 소견서 (2단계) |
| CI/CD | 수동 ECR push | GitHub Actions → ECR → ArgoCD |
| 모니터링 | CloudWatch | Prometheus + Grafana + Loki |

---

## 2. 아키텍처

### 2-1. 전체 인프라 구조

```
[ 사용자 ]
    │
    ├── 정적 파일 ──→ CloudFront + S3 (React 프론트엔드)
    │
    └── API ────────→ ALB + HTTPS
                        │
    ┌───────────────────┴─── EKS Cluster (namespace: dr-ai) ───────────────┐
    │                                                                       │
    │   [ central-orchestrator ]                                            │
    │     환자 상태 관리 + LLM(Bedrock) 검사 결정 + 순차 루프               │
    │         │                                                             │
    │         ├──→ chest-svc    (박현우)  6-Layer CXR                       │
    │         ├──→ ecg-svc      (원정아)  12-lead ECG                       │
    │         └──→ blood-svc    (팀원C)   CBC/BMP/BNP                       │
    │                                                                       │
    │   [ 공유 서비스 ]                                                     │
    │     rag-svc       FAISS + bge-small-en-v1.5 (3개 모달 공유)          │
    │     report-svc    Bedrock Claude 종합 소견서 (전체 모달 결과 합산)    │
    │     auth-svc      JWT 인증                                            │
    │     patient-svc   환자 정보 CRUD                                      │
    │                                                                       │
    │   [ 모니터링 + CI/CD ] (Helm 설치)                                    │
    │     Prometheus + Grafana + Loki + ArgoCD                              │
    │                                                                       │
    │   Pod 간 통신: K8s Service DNS — IAM/CORS 불필요                     │
    └───────────────────────────────────────────────────────────────────────┘
                        │
    ┌───────────────────┴─── AWS 관리형 서비스 ─────────────────────────────┐
    │  RDS (PG)    Redis    EFS         S3       Bedrock    ECR             │
    │  환자 기록   세션 캐시 ONNX 모델   파일     LLM 호출   Docker 이미지  │
    └───────────────────────────────────────────────────────────────────────┘

[ 배포 파이프라인 ]
  git push → GitHub Actions → docker build → ECR push → ArgoCD → Rolling Update
  팀원은 자기 모달 폴더만 push → 해당 서비스만 자동 재배포

[ 환경 분리 (Kustomize) ]
  base/       공통 Deployment YAML
  overlays/
    local/    Docker Compose (PG 컨테이너 + Redis 컨테이너)
    eks/      RDS 엔드포인트 + ElastiCache + EFS
```

### 2-2. 순차 검사 데이터 흐름 (예시: 67세 남성 호흡곤란)

```
환자 도착 (67세 M / 호흡곤란 / 고혈압 병력)
    │
    ▼
central-orchestrator
  Bedrock에 "이 환자 뭐부터 검사?" ←── Redis (세션 상태)
    │
    │  "CXR 먼저"
    ▼
chest-svc (박현우)
  seg → densenet → yolo → clinical → rag-svc 호출 → 흉부 소견서 생성
    │
    │  CTR 0.58 / 폐부종 / 흉수 + 흉부과 소견서
    ▼
orchestrator — 결과 누적 + 2차 판단
  "심비대 + 폐부종 → ECG로 심장 확인"
    │
    │  "ECG 지시" + CXR 결과 context
    ▼
ecg-svc (원정아)
  12-lead 분석 + 부정맥 판정
    │
    │  LVH + AF 소견 + 심전도 소견서
    ▼
orchestrator — CXR+ECG 누적 + 3차 판단
  "CXR 심비대 + ECG LVH → BNP 확인 필요"
    │
    │  "혈액검사 지시" + CXR+ECG context
    ▼
blood-svc (팀원 C)
  CBC + BMP + BNP + 이상치 판정
    │
    │  BNP 1200 / Cr 상승 + 혈액검사 소견서
    ▼
orchestrator — 추가 검사 필요성 판단
  "3개 모달 일치 → CHF 확진 충분 → 검사 종료"
    │
    │  전체 누적 결과 → LLM
    ▼
report-svc (Bedrock Claude) ←── rag-svc (근거 문헌)
  CXR 소견 + ECG 소견 + Blood 소견 → 종합 소견서
    │
    ▼
종합 소견서 응답
  "CHF NYHA III-IV — CXR/ECG/BNP 일관 소견"
```

### 2-3. 소견서 2단계 구조

| 단계 | 생성 위치 | 내용 | 예시 |
|------|----------|------|------|
| 1단계: 모달별 소견서 | 각 모달 서비스 내부 | 해당 과 전문의 소견 | "CXR: 심비대(CTR 0.58), 폐부종" |
| 2단계: 종합 소견서 | report-svc (공유) | 전체 결과 합산 진단 | "CHF NYHA III-IV — 다모달 일관 소견" |

chest-svc는 Layer 1~3 분석 후 rag-svc를 호출해 유사 케이스를 찾고, 내부에서 Bedrock를 호출해 흉부과 소견서를 생성한 뒤 오케스트레이터에 리턴한다. ecg-svc, blood-svc도 동일 패턴으로 자체 소견서를 생성한다.

---

## 3. 레포지토리 구조

### 3-1. v3 전체 폴더 구조

```
mimic-cxr-v3-eks/
│
├── services/                          ← 팀원별 서비스 코드
│   │
│   ├── chest-svc/                     ← [박현우] 흉부 X-Ray 모달
│   │   ├── main.py                        FastAPI (POST /predict)
│   │   ├── pipeline.py                    6단계 순차 실행 통합
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── layer1_segmentation/           Layer 1: 폐/심장 세그멘테이션
│   │   │   ├── preprocessing.py
│   │   │   └── segmentation_model.py
│   │   ├── layer2_detection/              Layer 2+2b: DenseNet + YOLOv8
│   │   │   ├── densenet_model.py
│   │   │   └── yolo_model.py
│   │   ├── layer3_clinical_logic/         Layer 3: 14 Rule + 교차검증
│   │   │   ├── engine.py
│   │   │   ├── cross_validation.py
│   │   │   ├── differential.py
│   │   │   └── rules/ (14개 질환)
│   │   └── report/                        Layer 6: 흉부과 소견서 생성
│   │       ├── chest_report_generator.py
│   │       └── prompt_templates.py
│   │
│   ├── ecg-svc/                       ← [원정아] ECG 모달
│   │   ├── main.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   ├── blood-svc/                     ← [팀원 C] 혈액검사 모달
│   │   ├── main.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   ├── central-orchestrator/          ← [팀원 D+E] 중앙 오케스트레이터
│   │   ├── main.py
│   │   ├── orchestrator.py                LLM 순차 루프 엔진
│   │   ├── session_manager.py             세션 상태 관리 (PG + Redis)
│   │   ├── modal_client.py                모달 서비스 HTTP 클라이언트
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   ├── rag-svc/                       ← [팀원 D+E] 공유 RAG 검색
│   │   ├── main.py
│   │   ├── rag_service.py
│   │   ├── query_builder.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   ├── report-svc/                    ← [팀원 D+E] 종합 소견서 생성
│   │   ├── main.py
│   │   ├── report_generator.py
│   │   ├── prompt_templates.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   ├── auth-svc/                      ← [팀원 D+E] JWT 인증
│   │   ├── main.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   └── patient-svc/                   ← [팀원 D+E] 환자 CRUD
│       ├── main.py
│       ├── Dockerfile
│       └── requirements.txt
│
├── k8s/                               ← K8s 매니페스트 (Kustomize)
│   ├── base/                              공통 Deployment + Service
│   │   ├── chest-svc.yaml
│   │   ├── ecg-svc.yaml
│   │   ├── blood-svc.yaml
│   │   ├── orchestrator.yaml
│   │   ├── rag-svc.yaml
│   │   ├── report-svc.yaml
│   │   ├── auth-svc.yaml
│   │   ├── patient-svc.yaml
│   │   └── kustomization.yaml
│   └── overlays/
│       ├── local/                         로컬 (Docker Compose / minikube)
│       │   ├── postgres.yaml
│       │   ├── redis.yaml
│       │   ├── configmap.yaml             localhost 엔드포인트
│       │   └── kustomization.yaml
│       └── eks/                           프로덕션
│           ├── configmap.yaml             RDS/ElastiCache 엔드포인트
│           ├── secret.yaml                AWS 크레덴셜
│           └── kustomization.yaml
│
├── docker-compose.yml                 ← 로컬 통합 테스트용
├── docker-compose.dev.yml             ← 개발 모드 (볼륨 마운트)
│
├── infra/                             ← Terraform (나중에)
│   ├── main.tf
│   ├── eks.tf
│   ├── rds.tf
│   └── ...
│
├── frontend/                          ← React 프론트엔드 (S3 배포)
│   └── ...
│
├── docs/                              ← 프로젝트 문서
│   ├── TEAM_GUIDE.md                      팀원 가이드
│   ├── API_REFERENCE.md                   API 레퍼런스
│   ├── ARCHITECTURE.md                    아키텍처 문서
│   └── images/
│       ├── v3_infra_architecture.png
│       └── v3_sequential_exam_flow.png
│
├── models/                            ← ONNX 모델 (로컬용, git LFS 또는 .gitignore)
│   ├── unet_seg.onnx
│   ├── densenet121.onnx
│   └── yolov8_vindr.onnx
│
├── data/                              ← 테스트 데이터 (로컬용)
│   └── test_images/
│       ├── sample_chf.jpg
│       ├── sample_pneumonia.jpg
│       └── sample_normal.jpg
│
└── .github/
    └── workflows/
        ├── chest-svc.yml                  chest-svc CI/CD
        ├── ecg-svc.yml                    ecg-svc CI/CD
        ├── blood-svc.yml                  blood-svc CI/CD
        └── orchestrator.yml               orchestrator CI/CD
```

### 3-2. v2 → v3 코드 마이그레이션 매핑

| v2 소스 (Lambda) | v3 대상 | 작업 |
|------------------|---------|------|
| deploy/layer1_segmentation/lambda_function.py | services/chest-svc/layer1_segmentation/ | Lambda 핸들러 제거 → Python 함수화 |
| deploy/layer2_detection/lambda_function.py | services/chest-svc/layer2_detection/densenet_model.py | 동일 |
| deploy/layer2b_yolov8/lambda_function.py | services/chest-svc/layer2_detection/yolo_model.py | 동일 |
| layer3_clinical_logic/ (전체) | services/chest-svc/layer3_clinical_logic/ | 거의 그대로 복사 |
| layer5_rag/ | services/rag-svc/ | S3 로딩 → EFS 로딩으로 변경 |
| layer6_bedrock_report/ | services/chest-svc/report/ (흉부 소견서) | 모달별 소견서 로직 |
| layer6_bedrock_report/ | services/report-svc/ (종합 소견서) | 새로 작성 |
| deploy/chest_modal_orchestrator/ | services/central-orchestrator/ | 완전 재작성 (LLM 순차 루프) |
| PyTorch 모델 (.pth, .pt) | models/ (.onnx) | ONNX 변환 필요 |

---

## 4. 서비스별 상세 스펙

### 4-1. chest-svc (박현우)

**내부 파이프라인:**

```
이미지 입력 (base64)
  → Layer 1: UNet 세그멘테이션 (마스크 + CTR + 해부학 계측)
  → Layer 2: DenseNet-121 (14질환 확률)
  → Layer 2b: YOLOv8 (병변 bbox 위치)
  → Layer 3: Clinical Logic (14 Rule + 교차검증 + 감별진단)
  → HTTP: rag-svc POST /search (유사 케이스 검색)
  → Layer 6: Bedrock 호출 (흉부과 소견서 생성)
  → 오케스트레이터에 리턴
```

**리소스:** CPU 1core / Memory 2Gi (ONNX 모델 3개 메모리 상주)
**모델:** unet_seg.onnx (~85MB) + densenet121.onnx (~27MB) + yolov8_vindr.onnx (~22MB)
**포트:** 8000

### 4-2. ecg-svc (원정아)

**역할:** 12-lead ECG 신호 분석, 부정맥 판정, 심전도 소견서 생성
**입력:** ECG 신호 데이터 (JSON)
**출력:** findings (LVH, AF, ST 변화 등) + 심전도 소견서
**리소스:** CPU 500m / Memory 1Gi
**포트:** 8000

### 4-3. blood-svc (팀원 C)

**역할:** CBC/BMP/BNP/Troponin 등 혈액검사 수치 분석, 이상치 판정, 혈액검사 소견서 생성
**입력:** 혈액검사 수치 (JSON)
**출력:** findings (BNP 상승, Cr 상승 등) + 혈액검사 소견서
**리소스:** CPU 250m / Memory 512Mi
**포트:** 8000

### 4-4. central-orchestrator (팀원 D+E)

**역할:** LLM 기반 순차 검사 루프
**흐름:**
1. 환자 도착 → 환자 정보 DB 저장
2. Bedrock에 "다음 검사?" 질의
3. 해당 모달 서비스 POST /predict 호출
4. 결과 누적 (PostgreSQL + Redis)
5. Bedrock에 "더 필요한 검사?" 재질의
6. 반복 또는 종료 판단
7. 종료 시 report-svc 호출 (종합 소견서)

**리소스:** CPU 250m / Memory 512Mi
**포트:** 8000

### 4-5. rag-svc (공유)

**역할:** FAISS 인덱스 + bge-small-en-v1.5 임베딩, 유사 케이스 검색
**엔드포인트:** POST /search
**사용자:** chest-svc, ecg-svc, blood-svc, report-svc
**리소스:** CPU 500m / Memory 1Gi (FAISS 인덱스 메모리 로딩)
**포트:** 8000

### 4-6. report-svc (공유)

**역할:** 종합 소견서 생성 (3개 모달 소견서 합산 → Bedrock Claude)
**엔드포인트:** POST /generate
**입력:** 각 모달의 소견서 + findings 전체
**리소스:** CPU 250m / Memory 512Mi
**포트:** 8000

### 4-7. auth-svc / patient-svc (공유)

**auth-svc:** JWT 발급/검증 (FastAPI 미들웨어 수준, 나중에 구현)
**patient-svc:** 환자 정보 CRUD (PostgreSQL 연동, 나중에 구현)
**우선순위 낮음** — 핵심 파이프라인 완성 후 추가

---

## 5. API 규격 (Contract)

### 5-1. 모달 서비스 공통 (chest/ecg/blood)

**요청:**

```json
POST /predict
{
  "patient_id": "P-20260324-001",
  "patient_info": {
    "age": 67, "sex": "M",
    "chief_complaint": "호흡곤란",
    "history": ["고혈압", "당뇨"]
  },
  "data": { /* 모달마다 다름 */ },
  "context": { /* 이전 모달 결과 요약 */ }
}
```

**응답:**

```json
{
  "status": "success",
  "modal": "chest",
  "findings": [
    {"name": "cardiomegaly", "detected": true, "confidence": 0.92, "detail": "CTR 0.58"}
  ],
  "summary": "심비대(CTR 0.58) 및 폐부종 소견.",
  "report": "흉부 X-Ray 소견서 전문...",
  "metadata": {"model_version": "v2.1", "inference_time_ms": 342}
}
```

### 5-2. rag-svc

```json
POST /search
{ "query": "cardiomegaly with pulmonary edema", "modal": "chest", "top_k": 5 }

→ { "results": [{"text": "...", "score": 0.92, "source": "..."}] }
```

### 5-3. report-svc

```json
POST /generate
{
  "patient_id": "P-20260324-001",
  "patient_info": {...},
  "modal_reports": [
    {"modal": "chest", "report": "...", "findings": [...]},
    {"modal": "ecg", "report": "...", "findings": [...]},
    {"modal": "blood", "report": "...", "findings": [...]}
  ]
}

→ { "status": "success", "report": "종합 소견서 전문...", "diagnosis": "CHF NYHA III-IV" }
```

---

## 6. 로컬 개발 및 테스트 계획

### 6-1. Phase 1 — 각자 단독 테스트 (즉시 시작)

각 팀원이 자기 서비스를 로컬에서 uvicorn으로 띄우고 /predict 테스트.
AWS 서비스 의존성 없음. mock 데이터 리턴도 OK.

```bash
cd services/너의-서비스명/
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
# http://localhost:8000/docs 에서 Swagger UI 테스트
```

**완료 기준:** /predict 호출 시 규격에 맞는 JSON 응답 리턴

### 6-2. Phase 2 — Docker Compose 통합 테스트

모든 서비스 + PostgreSQL + Redis를 docker-compose.yml로 한 번에 띄워서 오케스트레이터 → 모달 → rag → report 전체 흐름 테스트.

**AWS 서비스 로컬 대체:**

| AWS 서비스 | 로컬 대체 | Docker 이미지 |
|-----------|----------|---------------|
| RDS (PostgreSQL) | PostgreSQL 컨테이너 | postgres:16 |
| ElastiCache (Redis) | Redis 컨테이너 | redis:7 |
| EFS | 로컬 볼륨 마운트 | ./models:/models |
| Bedrock | 직접 API 호출 or mock | 환경변수로 분기 |
| S3 | 로컬 파일시스템 | ./data:/data |
| ECR | 로컬 Docker 이미지 | docker build 직접 |

**완료 기준:** 환자 도착 → 오케스트레이터 루프 → 모달 순차 호출 → 종합 소견서 생성 E2E 성공

### 6-3. Phase 3 — minikube 검증

Docker Compose에서 검증된 서비스를 K8s YAML로 배포하여 실제 K8s 환경에서 동작 확인.
Kustomize overlays/local 적용.

**완료 기준:** kubectl apply -k overlays/local 후 모든 Pod Running + E2E 성공

### 6-4. Phase 4 — EKS 배포

Terraform으로 AWS 인프라 생성 → Kustomize overlays/eks 적용 → ArgoCD 연동.

**완료 기준:** 외부에서 ALB 엔드포인트로 접근 가능 + 프론트엔드 CloudFront 연동

---

## 7. 구현 우선순위 및 마일스톤

### Sprint 1 (1주차): 기반 구축

- [박현우] 레포 구조 생성, chest-svc 스캐폴딩, v2 코드 마이그레이션 시작
- [원정아] ecg-svc main.py 작성, /predict mock 응답 구현
- [팀원 C] blood-svc main.py 작성, /predict mock 응답 구현
- [팀원 D] central-orchestrator 기본 구조 작성
- [팀원 E] rag-svc, report-svc 기본 구조 작성
- docker-compose.yml 작성 (PG + Redis + 서비스들)

### Sprint 2 (2주차): 핵심 로직 구현

- [박현우] chest-svc Layer 1~3 통합, ONNX 모델 로딩, pipeline.py 완성
- [원정아] ecg-svc 실제 분석 로직 구현
- [팀원 C] blood-svc 실제 분석 로직 구현
- [팀원 D] orchestrator LLM 순차 루프 구현, Bedrock 연동
- [팀원 E] rag-svc FAISS 로딩 + 검색 구현, report-svc 종합 소견서 구현

### Sprint 3 (3주차): 통합 테스트 + 배포 준비

- Docker Compose E2E 테스트
- K8s YAML 작성 + minikube 검증
- GitHub Actions CI/CD 파이프라인 구축
- 모니터링 스택 (Prometheus + Grafana) 설치
- 프론트엔드 연동

### Sprint 4 (4주차): EKS 배포 + 마무리

- Terraform 인프라 프로비저닝
- EKS 배포 + ArgoCD 연동
- 부하 테스트 + 성능 최적화
- auth-svc, patient-svc 추가 (선택)
- 문서화 + 발표 준비

---

## 8. Git 브랜치 전략

```
mimic-cxr-v3-eks (메인)
├── feat/chest-svc          ← 박현우
├── feat/ecg-svc            ← 원정아
├── feat/blood-svc          ← 팀원 C
├── feat/orchestrator       ← 팀원 D
├── feat/shared-services    ← 팀원 E
├── feat/docker-compose     ← 로컬 테스트 환경
├── feat/k8s-manifests      ← K8s YAML
└── feat/ci-cd              ← GitHub Actions
```

**규칙:**
- 메인 브랜치에 직접 push 금지, 반드시 PR
- services/자기-서비스명/ 폴더 밖 수정 금지
- 커밋 메시지: feat(chest-svc): 설명 / fix(ecg-svc): 설명
- API 규격 변경은 팀 전체 합의 필수

---

## 9. 기술 스택 요약

| 영역 | 기술 |
|------|------|
| 언어 | Python 3.11 |
| 웹 프레임워크 | FastAPI + Uvicorn |
| ML 추론 | ONNX Runtime (CPU) |
| 컨테이너 | Docker |
| 오케스트레이션 | Kubernetes (minikube → EKS) |
| DB | PostgreSQL 16 |
| 캐시 | Redis 7 |
| LLM | AWS Bedrock (Claude Sonnet 4.6) |
| RAG | FAISS + bge-small-en-v1.5 |
| 모델 저장 | EFS (EKS) / 로컬 볼륨 (dev) |
| CI/CD | GitHub Actions → ECR → ArgoCD |
| 모니터링 | Prometheus + Grafana + Loki |
| IaC | Terraform (Phase 4) |
| 프론트엔드 | React + S3 + CloudFront |
| 환경 관리 | Kustomize (base + overlays) |
