# Plan: v3-eks-migration

> v2 Lambda → v3 EKS 마이크로서비스 마이그레이션
> 작성일: 2026-03-25
> 피처: v3-eks-migration
> PDCA Phase: Plan

---

## Executive Summary

| 관점 | 내용 |
|------|------|
| **Problem** | v2 Lambda 7개 개별 배포 구조로 콜드스타트, 단일 모달 한계, 팀원 독립 개발 불가 |
| **Solution** | EKS 마이크로서비스 전환 — 로컬 minikube 우선 구축 후 AWS EKS 이전 |
| **Function UX Effect** | LLM 기반 멀티모달 순차 검사 루프로 CXR→ECG→Blood 자동 연계 진단 가능 |
| **Core Value** | 5명 독립 개발 + 모델 상시 로딩(ONNX) + 종합 소견서 2단계 생성 |

---

## Context Anchor

| 항목 | 내용 |
|------|------|
| **WHY** | Lambda 콜드스타트/단일 모달 한계 극복, 팀원별 독립 서비스 개발 체계 구축 |
| **WHO** | 6팀 5명 (박현우-chest, 원정아-ecg, 팀원C-blood, 팀원D-orchestrator, 팀원E-shared) |
| **RISK** | K8s 학습곡선, 서비스 간 통신 장애, ONNX 변환 정합성, Bedrock 비용 |
| **SUCCESS** | 로컬 minikube에서 환자→순차검사→종합소견서 E2E 성공, 이후 EKS 무중단 이전 |
| **SCOPE** | 8개 서비스 (chest/ecg/blood/orchestrator/rag/report/auth/patient) + K8s + CI/CD |

---

## 1. 배경 및 문제 정의

### 1-1. v2 현재 상태
- Lambda 7개 개별 배포 (layer1_seg, layer2_detection, layer2b_yolo, layer3_clinical, layer5_rag, layer6_report, orchestrator)
- Function URL (HTTP + IAM) 기반 통신
- PyTorch 모델 Lambda 콜드스타트 (~15초)
- 단일 모달(CXR) 파이프라인만 구현

### 1-2. v2 한계점
| 문제 | 영향 |
|------|------|
| Lambda 콜드스타트 | 모델 로딩 시간 15초+, 사용자 경험 저하 |
| 단일 모달 한정 | ECG/Blood 모달 추가 불가 구조 |
| 팀원 독립 개발 불가 | Lambda 간 의존성으로 병렬 개발 어려움 |
| IAM/CORS 복잡성 | 서비스 간 통신에 AWS 인증 필요 |
| 오케스트레이션 없음 | LLM 기반 순차 검사 판단 불가 |

### 1-3. v3 목표
- **컴퓨팅**: Lambda → K8s Pod (ONNX Runtime 상시 로딩)
- **통신**: Function URL → K8s Service DNS (IAM/CORS 불필요)
- **오케스트레이션**: 단일 모달 → LLM 기반 멀티모달 순차 검사 루프
- **개발 체계**: 팀원별 서비스 분리, 독립 빌드/배포

---

## 2. 요구사항

### 2-1. 기능 요구사항 (FR)

| ID | 요구사항 | 우선순위 | 담당 |
|----|----------|----------|------|
| FR-01 | chest-svc: 6-Layer CXR 파이프라인 (Seg→DenseNet→YOLO→Clinical→RAG→Report) | P0 | 박현우 |
| FR-02 | ecg-svc: 12-lead ECG 분석 + 부정맥 판정 + 소견서 | P0 | 원정아 |
| FR-03 | blood-svc: CBC/BMP/BNP 이상치 판정 + 소견서 | P0 | 팀원C |
| FR-04 | central-orchestrator: LLM(Bedrock) 순차 검사 루프 + 세션 관리 | P0 | 팀원D |
| FR-05 | rag-svc: FAISS + bge-small-en-v1.5 공유 검색 | P0 | 팀원E |
| FR-06 | report-svc: 3개 모달 소견서 합산 → 종합 소견서 (Bedrock Claude) | P0 | 팀원E |
| FR-07 | 소견서 2단계: 모달별 소견서(1단계) + 종합 소견서(2단계) | P0 | 전체 |
| FR-08 | auth-svc: JWT 인증 | P2 | 팀원E |
| FR-09 | patient-svc: 환자 정보 CRUD | P2 | 팀원E |

### 2-2. 비기능 요구사항 (NFR)

| ID | 요구사항 | 기준 |
|----|----------|------|
| NFR-01 | 모델 추론 응답시간 | < 5초 (콜드스타트 없음) |
| NFR-02 | 순차 검사 E2E 응답시간 | < 60초 (3모달 순차) |
| NFR-03 | Pod 간 통신 | K8s Service DNS, HTTP 직접 호출 |
| NFR-04 | 환경 분리 | Kustomize overlays (local/eks) |
| NFR-05 | 모델 저장 | 로컬 PV → EKS EFS |
| NFR-06 | DB/캐시 | 로컬 K8s Pod (PG/Redis) → EKS RDS/ElastiCache |

### 2-3. API Contract (서비스 간 규격)

**모달 서비스 공통 (chest/ecg/blood):**
```
POST /predict
Request:  { patient_id, patient_info: {age, sex, chief_complaint, history}, data: {...}, context: {...} }
Response: { status, modal, findings: [{name, detected, confidence, detail}], summary, report, metadata }
```

**rag-svc:**
```
POST /search
Request:  { query, modal, top_k }
Response: { results: [{text, score, source}] }
```

**report-svc:**
```
POST /generate
Request:  { patient_id, patient_info, modal_reports: [{modal, report, findings}] }
Response: { status, report, diagnosis }
```

---

## 3. 인프라 전략: Local-First → AWS

### 3-1. 2단계 인프라 전략

| 단계 | 환경 | 컴퓨팅 | DB | 캐시 | 모델 저장 | LLM |
|------|------|--------|-----|------|-----------|-----|
| **Phase A (현재)** | 로컬 minikube | K8s Pod | PG Pod (postgres:16) | Redis Pod (redis:7) | PV (로컬 볼륨) | Bedrock API 직접 호출 |
| **Phase B (후기)** | AWS EKS | EKS Pod | RDS PostgreSQL | ElastiCache Redis | EFS | Bedrock |

### 3-2. Kustomize 환경 분리

```
k8s/
├── base/                    ← 공통 Deployment + Service YAML
│   ├── chest-svc.yaml
│   ├── ecg-svc.yaml
│   ├── blood-svc.yaml
│   ├── orchestrator.yaml
│   ├── rag-svc.yaml
│   ├── report-svc.yaml
│   └── kustomization.yaml
└── overlays/
    ├── local/               ← minikube (PG Pod + Redis Pod + PV)
    │   ├── postgres.yaml        PG StatefulSet
    │   ├── redis.yaml           Redis Deployment
    │   ├── pv-models.yaml       모델 PersistentVolume
    │   ├── configmap.yaml       localhost 엔드포인트
    │   └── kustomization.yaml
    └── eks/                 ← AWS (RDS + ElastiCache + EFS)
        ├── configmap.yaml       RDS/ElastiCache 엔드포인트
        ├── secret.yaml          AWS 크레덴셜
        ├── storageclass.yaml    EFS StorageClass
        └── kustomization.yaml
```

### 3-3. 환경 변수 분기 패턴

```python
# 모든 서비스 공통 — ConfigMap에서 주입
DATABASE_URL = os.getenv("DATABASE_URL")        # local: postgres-svc:5432 / eks: rds-endpoint
REDIS_URL = os.getenv("REDIS_URL")              # local: redis-svc:6379 / eks: elasticache-endpoint
MODEL_PATH = os.getenv("MODEL_PATH", "/models") # local: PV / eks: EFS
```

---

## 4. 서비스 아키텍처

### 4-1. 전체 서비스 맵 (8개)

```
[ 사용자 ] → [ ALB / minikube ingress ]
                    │
    ┌───────────────┴─── K8s Cluster (ns: dr-ai) ───────────────┐
    │                                                             │
    │   [ central-orchestrator ]  ← Redis (세션) + PG (환자)     │
    │     LLM 순차 루프 (Bedrock)                                │
    │         │                                                   │
    │         ├──→ chest-svc    (ONNX x3, CPU 1c/2Gi)           │
    │         ├──→ ecg-svc     (CPU 500m/1Gi)                   │
    │         └──→ blood-svc   (CPU 250m/512Mi)                 │
    │                                                             │
    │   [ 공유 서비스 ]                                           │
    │     rag-svc      FAISS + bge-small (CPU 500m/1Gi)         │
    │     report-svc   종합 소견서 (CPU 250m/512Mi)             │
    │     auth-svc     JWT (P2)                                  │
    │     patient-svc  환자 CRUD (P2)                            │
    │                                                             │
    │   Pod 간 통신: K8s Service DNS (http://chest-svc:8000)     │
    └─────────────────────────────────────────────────────────────┘
```

### 4-2. 서비스별 리소스

| 서비스 | CPU | Memory | 모델 | 포트 | 우선순위 |
|--------|-----|--------|------|------|----------|
| chest-svc | 1 core | 2Gi | unet(85MB)+densenet(27MB)+yolo(22MB) | 8000 | P0 |
| ecg-svc | 500m | 1Gi | ECG 모델 | 8000 | P0 |
| blood-svc | 250m | 512Mi | 없음 (규칙 기반) | 8000 | P0 |
| central-orchestrator | 250m | 512Mi | 없음 | 8000 | P0 |
| rag-svc | 500m | 1Gi | FAISS 인덱스 + bge-small | 8000 | P0 |
| report-svc | 250m | 512Mi | 없음 | 8000 | P0 |
| auth-svc | 100m | 128Mi | 없음 | 8000 | P2 |
| patient-svc | 100m | 256Mi | 없음 | 8000 | P2 |
| **합계 (P0)** | **2.75 core** | **5.5Gi** | | | |

### 4-3. 순차 검사 데이터 흐름

```
환자 도착 (67세 M / 호흡곤란)
  → orchestrator: Bedrock "뭐부터 검사?" → "CXR 먼저"
  → chest-svc: Seg→DenseNet→YOLO→Clinical→RAG→흉부 소견서
  → orchestrator: 결과 누적 + "심비대+폐부종 → ECG 확인"
  → ecg-svc: 12-lead 분석 → LVH+AF + 심전도 소견서
  → orchestrator: CXR+ECG 누적 + "LVH → BNP 확인"
  → blood-svc: CBC+BMP+BNP → BNP 1200 + 혈액검사 소견서
  → orchestrator: "3모달 일치 → 검사 종료"
  → report-svc: 전체 소견서 합산 → 종합 소견서 (CHF NYHA III-IV)
```

---

## 5. v2 → v3 코드 마이그레이션

| v2 소스 (Lambda) | v3 대상 | 작업 |
|------------------|---------|------|
| deploy/layer1_segmentation/ | services/chest-svc/layer1_segmentation/ | Lambda 핸들러 제거 → Python 함수화 |
| deploy/layer2_detection/ | services/chest-svc/layer2_detection/densenet_model.py | 동일 |
| deploy/layer2b_yolov8/ | services/chest-svc/layer2_detection/yolo_model.py | 동일 |
| layer3_clinical_logic/ | services/chest-svc/layer3_clinical_logic/ | 거의 그대로 복사 |
| layer5_rag/ | services/rag-svc/ | S3→PV/EFS 로딩 변경 |
| layer6_bedrock_report/ | services/chest-svc/report/ (모달별) | 흉부 소견서 로직 분리 |
| layer6_bedrock_report/ | services/report-svc/ (종합) | 새로 작성 |
| deploy/chest_modal_orchestrator/ | services/central-orchestrator/ | 완전 재작성 (LLM 순차 루프) |
| PyTorch 모델 (.pth/.pt) | models/ (.onnx) | ONNX 변환 필수 |

---

## 6. 레포지토리 구조

```
mimic-cxr-v3-eks/
├── services/
│   ├── chest-svc/              [박현우] 6-Layer CXR
│   ├── ecg-svc/                [원정아] 12-lead ECG
│   ├── blood-svc/              [팀원C] 혈액검사
│   ├── central-orchestrator/   [팀원D] LLM 순차 루프
│   ├── rag-svc/                [팀원E] 공유 RAG
│   ├── report-svc/             [팀원E] 종합 소견서
│   ├── auth-svc/               [팀원E] JWT (P2)
│   └── patient-svc/            [팀원E] 환자 CRUD (P2)
├── k8s/
│   ├── base/                   공통 Deployment + Service
│   └── overlays/
│       ├── local/              minikube (PG/Redis Pod + PV)
│       └── eks/                AWS (RDS/ElastiCache/EFS)
├── docker-compose.yml          로컬 빠른 테스트용 (K8s 이전 단계)
├── infra/                      Terraform (Phase B)
├── frontend/                   React (S3+CloudFront)
├── models/                     ONNX 모델 (.gitignore)
├── data/                       테스트 데이터
└── .github/workflows/          서비스별 CI/CD
```

---

## 7. 마일스톤 및 일정

### Sprint 1 (1주차): 기반 구축 + 스캐폴딩

| 담당 | 작업 | 완료 기준 |
|------|------|-----------|
| 박현우 | 레포 구조 생성, chest-svc 스캐폴딩, v2 코드 마이그레이션 시작 | /predict mock 응답 |
| 원정아 | ecg-svc main.py + /predict mock | Swagger UI 테스트 통과 |
| 팀원C | blood-svc main.py + /predict mock | Swagger UI 테스트 통과 |
| 팀원D | central-orchestrator 기본 구조 | 모달 서비스 호출 mock 성공 |
| 팀원E | rag-svc + report-svc 기본 구조, docker-compose.yml | 서비스 간 통신 테스트 |

### Sprint 2 (2주차): 핵심 로직 구현

| 담당 | 작업 | 완료 기준 |
|------|------|-----------|
| 박현우 | Layer 1~3 통합, ONNX 로딩, pipeline.py | 실제 이미지 분석 성공 |
| 원정아 | ECG 실제 분석 로직 | 실제 ECG 데이터 분석 |
| 팀원C | Blood 실제 분석 로직 | 실제 수치 판정 |
| 팀원D | Bedrock 순차 루프 + 세션 관리 (PG+Redis) | 3모달 순차 호출 성공 |
| 팀원E | FAISS 로딩 + 종합 소견서 생성 | RAG 검색 + 종합 소견서 생성 |

### Sprint 3 (3주차): K8s 통합 + 테스트

| 작업 | 완료 기준 |
|------|-----------|
| K8s base YAML 작성 (8개 서비스) | kubectl apply 성공 |
| overlays/local (PG/Redis Pod + PV) | minikube 전체 서비스 Running |
| E2E 테스트: 환자→순차검사→종합소견서 | minikube에서 전체 흐름 성공 |
| GitHub Actions CI/CD 파이프라인 | 자동 빌드+이미지 push |
| 프론트엔드 연동 | UI에서 진단 요청 가능 |

### Sprint 4 (4주차): EKS 배포 + 마무리

| 작업 | 완료 기준 |
|------|-----------|
| Terraform 인프라 (EKS+RDS+ElastiCache+EFS) | AWS 리소스 생성 |
| overlays/eks 적용 + ArgoCD 연동 | EKS 전체 서비스 Running |
| ALB + CloudFront 연동 | 외부 접근 가능 |
| 모니터링 (Prometheus+Grafana+Loki) | 대시보드 확인 |
| auth-svc + patient-svc (선택) | JWT 인증 동작 |
| 문서화 + 발표 준비 | 최종 산출물 완성 |

---

## 8. Git 브랜치 전략

```
mimic-cxr-v3-eks (메인)
├── feat/chest-svc          ← 박현우
├── feat/ecg-svc            ← 원정아
├── feat/blood-svc          ← 팀원C
├── feat/orchestrator       ← 팀원D
├── feat/shared-services    ← 팀원E
├── feat/k8s-manifests      ← K8s YAML
└── feat/ci-cd              ← GitHub Actions
```

**규칙:**
- 메인 브랜치 직접 push 금지, PR 필수
- services/자기-서비스명/ 폴더 밖 수정 금지
- 커밋: `feat(chest-svc): 설명` / `fix(ecg-svc): 설명`
- API Contract 변경은 팀 전체 합의 필수

---

## 9. 기술 스택

| 영역 | 기술 |
|------|------|
| 언어 | Python 3.11 |
| 웹 프레임워크 | FastAPI + Uvicorn |
| ML 추론 | ONNX Runtime (CPU) |
| 컨테이너 | Docker |
| 오케스트레이션 | Kubernetes (minikube → EKS) |
| DB | PostgreSQL 16 (K8s Pod → RDS) |
| 캐시 | Redis 7 (K8s Pod → ElastiCache) |
| LLM | AWS Bedrock (Claude Sonnet 4.6) |
| RAG | FAISS + bge-small-en-v1.5 |
| 모델 저장 | PV (로컬) → EFS (EKS) |
| CI/CD | GitHub Actions → ECR → ArgoCD |
| 모니터링 | Prometheus + Grafana + Loki |
| IaC | Terraform (Phase B) |
| 프론트엔드 | React + S3 + CloudFront |
| 환경 관리 | Kustomize (base + overlays) |

---

## 10. 리스크 및 대응

| 리스크 | 영향 | 대응 |
|--------|------|------|
| K8s 학습곡선 | 팀원들 K8s 경험 부족 | Docker Compose 먼저, K8s는 Sprint 3에 집중 |
| ONNX 변환 실패 | 모델 정합성 깨짐 | v2 PyTorch와 ONNX 출력 교차 검증 |
| Bedrock 비용 | 순차 루프당 다회 LLM 호출 | max_iterations 제한 + 캐싱 |
| minikube 리소스 | 로컬 머신 리소스 부족 (5.5Gi+) | 개발 시 필요한 서비스만 선택 기동 |
| 서비스 간 API 불일치 | 통합 시 오류 | API Contract 선 합의 + Swagger 자동 생성 |
| FAISS 인덱스 크기 | 메모리 제한 | top_k 제한 + 인덱스 최적화 |

---

## 11. 성공 기준

| 기준 | 목표 | 측정 방법 |
|------|------|-----------|
| 로컬 E2E | minikube에서 환자→3모달 순차→종합소견서 성공 | curl 테스트 |
| 모달별 소견서 | 각 서비스가 독립 소견서 생성 | /predict 응답에 report 필드 |
| 종합 소견서 | 3개 모달 합산 진단 | report-svc /generate 응답 |
| 독립 배포 | 서비스별 Docker 이미지 빌드 성공 | GitHub Actions 그린 |
| 환경 분리 | local/eks overlays 교체만으로 배포 가능 | kustomize build 검증 |
| 추론 성능 | 모델 로딩 후 추론 < 5초 | 로그 타임스탬프 |
