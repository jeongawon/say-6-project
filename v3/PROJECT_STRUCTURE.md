# Dr. AI Radiologist v3 — 프로젝트 구조도

> v2 Lambda → v3 EKS 마이크로서비스
> 최종 업데이트: 2026-03-25

---

## 전체 디렉토리 구조

```
v3/
├── V3_MIGRATION_PLAN.md                          ← 마이그레이션 원본 계획서
├── PROJECT_STRUCTURE.md                          ← 이 문서
├── docker-compose.yml                            ← 로컬 통합 테스트 (8서비스 + PG + Redis)
│
├── shared/
│   └── schemas.py                                ← 공통 Pydantic 스키마 (전 서비스 공유)
│       PatientInfo, Finding, PredictRequest,
│       PredictResponse, RAGRequest, RAGResponse,
│       ReportRequest, ReportResponse
│
├── services/
│   │
│   ├── chest-svc/                   [박현우] 흉부 X-Ray 6-Layer 파이프라인
│   │   ├── main.py                      FastAPI + lifespan (ONNX 3개 로딩)
│   │   ├── config.py                    환경변수 (MODEL_DIR, RAG_URL, BEDROCK)
│   │   ├── pipeline.py                  Seg→DenseNet→YOLO→Clinical→RAG→Report 통합
│   │   ├── Dockerfile / requirements.txt
│   │   ├── layer1_segmentation/         UNet ONNX — 폐/심장 마스크 + CTR 계산
│   │   │   ├── preprocessing.py             이미지 리사이즈, 정규화
│   │   │   └── model.py                     ONNX Runtime 세그멘테이션
│   │   ├── layer2_detection/            DenseNet-121 + YOLOv8 ONNX
│   │   │   ├── densenet.py                  14질환 확률 분류
│   │   │   └── yolo.py                      병변 bbox 검출
│   │   ├── layer3_clinical_logic/       14 Rule + 교차검증 + 감별진단
│   │   │   ├── engine.py                    임상 분석 엔진 (메인)
│   │   │   ├── cross_validation.py          소견 간 교차검증
│   │   │   ├── differential.py              감별진단 로직
│   │   │   ├── models.py                    데이터 모델 (dataclass)
│   │   │   ├── thresholds.py                질환별 임계값
│   │   │   └── rules/                       14개 질환 규칙
│   │   │       ├── cardiomegaly.py              심비대
│   │   │       ├── pneumonia.py                 폐렴
│   │   │       ├── pleural_effusion.py          흉수
│   │   │       ├── edema.py                     폐부종
│   │   │       ├── atelectasis.py               무기폐
│   │   │       ├── consolidation.py             경화
│   │   │       ├── pneumothorax.py              기흉
│   │   │       ├── enlarged_cm.py               종격동 확장
│   │   │       ├── lung_opacity.py              폐 혼탁
│   │   │       ├── lung_lesion.py               폐 병변
│   │   │       ├── fracture.py                  골절
│   │   │       ├── support_devices.py           지지 장치
│   │   │       ├── pleural_other.py             기타 흉막
│   │   │       └── no_finding.py                정상 소견
│   │   └── report/                      Bedrock Claude → 흉부 소견서 생성
│   │       ├── chest_report_generator.py
│   │       └── prompt_templates.py
│   │
│   ├── ecg-svc/                     [원정아] 12-lead ECG 분석
│   │   ├── main.py                      FastAPI + lifespan + /healthz + /readyz
│   │   ├── config.py                    환경변수 (rag_url, bedrock)
│   │   ├── analyzer.py                  규칙 기반 ECG 분석 (8모듈)
│   │   │                                - 심박수, AF/VT/SVT 부정맥
│   │   │                                - LVH/RVH (Sokolow-Lyon, Cornell)
│   │   │                                - ST elevation/depression
│   │   │                                - QTc (Bazett), 축 편위, BBB
│   │   ├── report/
│   │   │   └── ecg_report_generator.py  Bedrock → 심전도 소견서
│   │   ├── Dockerfile / requirements.txt
│   │
│   ├── blood-svc/                   [팀원C] 혈액검사 분석
│   │   ├── main.py                      FastAPI + /healthz + /readyz
│   │   ├── config.py                    환경변수
│   │   ├── analyzer.py                  30+ 검사항목 분석 + 4 복합 평가
│   │   │                                - CBC, BMP, 심장마커, 간기능
│   │   │                                - 복합: 심부전, 신장, 빈혈, 감염
│   │   ├── reference_ranges.py          성별/연령별 정상 범위 + 위험값
│   │   ├── report/
│   │   │   └── blood_report_generator.py  Bedrock → 혈액검사 소견서
│   │   ├── Dockerfile / requirements.txt
│   │
│   ├── central-orchestrator/        [팀원D] LLM 순차 검사 루프 (핵심)
│   │   ├── main.py                      FastAPI + lifespan (DB+Redis 연결)
│   │   ├── config.py                    환경변수 (DB, Redis, 모달 URL, Bedrock)
│   │   ├── orchestrator.py              순차 루프 엔진 (핵심 로직)
│   │   │                                Bedrock "다음 검사?" → 모달 호출 → 누적 → 반복
│   │   ├── session_manager.py           PG + Redis 세션 상태 관리
│   │   ├── modal_client.py              chest/ecg/blood HTTP 클라이언트
│   │   ├── prompts.py                   Bedrock 프롬프트 (검사 결정)
│   │   ├── db.py                        asyncpg 풀 + 테이블 자동 생성
│   │   ├── Dockerfile / requirements.txt
│   │
│   ├── rag-svc/                     [팀원E] 공유 RAG 검색
│   │   ├── main.py                      FastAPI + lifespan (FAISS+임베더 로딩)
│   │   ├── config.py                    환경변수 (model_dir, index_path)
│   │   ├── rag_service.py               FAISS 검색 + bge-small-en-v1.5 임베딩
│   │   ├── query_builder.py             모달별 쿼리 구성 (chest/ecg/blood)
│   │   ├── Dockerfile / requirements.txt
│   │
│   ├── report-svc/                  [팀원E] 종합 소견서 생성
│   │   ├── main.py                      FastAPI + /healthz + /readyz
│   │   ├── config.py                    환경변수 (bedrock_region, model_id)
│   │   ├── report_generator.py          3개 모달 합산 → Bedrock Claude → 종합 진단
│   │   ├── prompt_templates.py          멀티모달 종합 소견서 프롬프트
│   │   ├── Dockerfile / requirements.txt
│   │
│   ├── auth-svc/                    (Phase 4 추가 예정) JWT 인증
│   │   └── 미구현 — Sprint 4에서 추가
│   │       POST /login (JWT 발급), GET /verify (토큰 검증)
│   │       FastAPI 미들웨어로 전 서비스 인증 적용
│   │
│   └── patient-svc/                 (Phase 4 추가 예정) 환자 CRUD
│       └── 미구현 — Sprint 4에서 추가
│           POST/GET/PUT /patients (PostgreSQL 연동)
│           환자 정보 등록/조회/수정
│
├── k8s/                                          ← Kubernetes 매니페스트
│   ├── base/                                        공통 Deployment + Service
│   │   ├── namespace.yaml                           dr-ai 네임스페이스
│   │   ├── chest-svc.yaml                           1cpu/2Gi, readiness 30s
│   │   ├── ecg-svc.yaml                             500m/1Gi, readiness 5s
│   │   ├── blood-svc.yaml                           250m/512Mi, readiness 3s
│   │   ├── central-orchestrator.yaml                250m/512Mi, readiness 5s
│   │   ├── rag-svc.yaml                             500m/1Gi, readiness 15s
│   │   ├── report-svc.yaml                          250m/512Mi, readiness 3s
│   │   └── kustomization.yaml
│   └── overlays/
│       ├── local/                                   minikube 환경
│       │   ├── configmap.yaml                       로컬 엔드포인트 (postgres-svc 등)
│       │   ├── postgres.yaml                        PG StatefulSet + Service
│       │   ├── redis.yaml                           Redis Deployment + Service
│       │   ├── pv-models.yaml                       모델 PV/PVC (hostPath)
│       │   └── kustomization.yaml
│       └── eks/                                     AWS EKS 환경
│           ├── configmap.yaml                       RDS/ElastiCache 엔드포인트
│           ├── secret.yaml                          AWS 크레덴셜
│           ├── storageclass.yaml                    EFS StorageClass
│           └── kustomization.yaml
│
└── .github/workflows/                            ← CI/CD (서비스별 독립)
    ├── chest-svc.yml                                services/chest-svc/** 변경 시 빌드
    ├── ecg-svc.yml                                  services/ecg-svc/** 변경 시 빌드
    ├── blood-svc.yml                                services/blood-svc/** 변경 시 빌드
    ├── orchestrator.yml                             services/central-orchestrator/**
    ├── rag-svc.yml                                  services/rag-svc/**
    └── report-svc.yml                               services/report-svc/**
```

---

## 개발 단계별 환경 가이드

> 상세 일정은 [V3_MIGRATION_PLAN.md](./V3_MIGRATION_PLAN.md) 참조

| Phase | 환경 | 사용 파일 | 완료 기준 |
|-------|------|-----------|-----------|
| **Phase 1** — 각자 단독 테스트 | `uvicorn main:app --reload` | 각 서비스 폴더만 | `/predict` mock 응답 리턴 |
| **Phase 2** — Docker Compose 통합 | `docker-compose up` | `docker-compose.yml` + 전체 서비스 | 오케스트레이터→모달→종합소견서 E2E |
| **Phase 3** — minikube K8s 검증 | `kubectl apply -k overlays/local` | `k8s/base/` + `k8s/overlays/local/` | 모든 Pod Running + E2E 성공 |
| **Phase 4** — EKS 배포 | `kubectl apply -k overlays/eks` | `k8s/base/` + `k8s/overlays/eks/` + `infra/` | 외부 ALB 접근 + auth-svc/patient-svc 추가 |

```
Phase 1 (Sprint 1~2)     Phase 2 (Sprint 2~3)     Phase 3 (Sprint 3)       Phase 4 (Sprint 4)
uvicorn 로컬 개발    →    docker-compose 통합  →    minikube K8s 검증   →    EKS 프로덕션 배포
각자 서비스 단독          PG+Redis 컨테이너          Kustomize local          Terraform + ArgoCD
                          8서비스 올림               overlays/local           overlays/eks
```

---

## 서비스 간 통신 흐름

```
[ 사용자 ] → [ ALB / minikube ingress ]
                    │
                    ▼
        ┌─ central-orchestrator (POST /examine) ─┐
        │   Bedrock "다음 검사?" 질의              │
        │       │                                  │
        │       ├──→ chest-svc (POST /predict)     │  CXR 6-Layer → 흉부 소견서
        │       │       └──→ rag-svc (POST /search)│  유사 케이스 검색
        │       │                                  │
        │       ├──→ ecg-svc (POST /predict)       │  12-lead ECG → 심전도 소견서
        │       │                                  │
        │       └──→ blood-svc (POST /predict)     │  CBC/BMP/BNP → 혈액 소견서
        │                                          │
        │   결과 누적 → "검사 종료" 판단            │
        │       │                                  │
        │       └──→ report-svc (POST /generate)   │  3개 소견서 합산 → 종합 소견서
        │                                          │
        │   ← Redis (세션 캐시) + PG (영구 저장) → │
        └──────────────────────────────────────────┘
```

---

## 순차 검사 데이터 흐름 (예시: 67세 남성 호흡곤란)

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
  Layer1 Seg → Layer2 DenseNet+YOLO → Layer3 Clinical → RAG → 흉부 소견서
  │
  │  CTR 0.58 / 폐부종 / 흉수 + 흉부 소견서
  ▼
orchestrator — 결과 누적 + 2차 판단
  "심비대 + 폐부종 → ECG로 심장 확인"
  │
  ▼
ecg-svc (원정아)
  12-lead 분석 → LVH(Sokolow-Lyon) + AF(불규칙 RR) + 심전도 소견서
  │
  │  LVH + AF 소견
  ▼
orchestrator — CXR+ECG 누적 + 3차 판단
  "CXR 심비대 + ECG LVH → BNP 확인 필요"
  │
  ▼
blood-svc (팀원C)
  CBC + BMP + BNP + Troponin 분석 + 혈액검사 소견서
  │
  │  BNP 1200 / Cr 상승
  ▼
orchestrator — 추가 검사 필요성 판단
  "3개 모달 일치 → CHF 확진 충분 → 검사 종료"
  │
  ▼
report-svc (팀원E)
  CXR 소견 + ECG 소견 + Blood 소견 → Bedrock Claude → 종합 소견서
  │
  ▼
종합 소견서 응답
  "CHF NYHA III-IV — CXR/ECG/BNP 일관 소견"
```

---

## 서비스별 상세

### 모달 서비스 (POST /predict)

| 서비스 | 담당 | 분석 방식 | 핵심 기술 | 리소스 |
|--------|------|-----------|-----------|--------|
| chest-svc | 박현우 | ML + Rule | ONNX(UNet+DenseNet+YOLO) + 14규칙 | 1cpu / 2Gi |
| ecg-svc | 원정아 | Rule-based | 임상 기준 (Sokolow-Lyon, Bazett 등) | 500m / 1Gi |
| blood-svc | 팀원C | Rule-based | 정상 범위 테이블 + 복합 평가 | 250m / 512Mi |

### 공유 서비스

| 서비스 | 담당 | 역할 | 핵심 기술 | 리소스 |
|--------|------|------|-----------|--------|
| central-orchestrator | 팀원D | LLM 순차 루프 + 세션 관리 | Bedrock + asyncpg + Redis | 250m / 512Mi |
| rag-svc | 팀원E | 유사 케이스 검색 | FAISS + bge-small-en-v1.5 | 500m / 1Gi |
| report-svc | 팀원E | 종합 소견서 생성 | Bedrock Claude | 250m / 512Mi |

### 소견서 2단계 구조

| 단계 | 생성 위치 | 내용 | 예시 |
|------|----------|------|------|
| 1단계: 모달별 소견서 | 각 모달 서비스 내부 | 해당 과 전문의 소견 | "CXR: 심비대(CTR 0.58), 폐부종" |
| 2단계: 종합 소견서 | report-svc | 전체 결과 합산 진단 | "CHF NYHA III-IV — 다모달 일관 소견" |

---

## API Contract

### 모달 서비스 공통 (chest / ecg / blood)

```
POST /predict
Request:
  { patient_id, patient_info: {age, sex, chief_complaint, history},
    data: {모달별 데이터}, context: {이전 모달 결과} }

Response:
  { status, modal, findings: [{name, detected, confidence, detail}],
    summary, report, metadata: {model_version, inference_time_ms} }
```

### rag-svc

```
POST /search
Request:  { query, modal, top_k }
Response: { results: [{text, score, source}] }
```

### report-svc

```
POST /generate
Request:  { patient_id, patient_info, modal_reports: [{modal, report, findings}] }
Response: { status, report, diagnosis }
```

### central-orchestrator

```
POST /examine
Request:  { patient_id, patient_info, data: {chest: {...}, ecg: {...}, blood: {...}} }
Response: { status, patient_id, exams_performed, modal_reports, final_report, diagnosis, metadata }
```

### 공통 헬스체크

```
GET /healthz  → { status: "ok" }        ← liveness probe
GET /readyz   → { status: "ready" }     ← readiness probe (모델 로딩 완료 후)
```

---

## K8s 12-Factor 운영 규약

모든 서비스가 동일하게 적용하는 3가지 규약:

| 규약 | 파일/엔드포인트 | 역할 |
|------|-----------------|------|
| 설정은 환경변수 | `config.py` (pydantic-settings) | ConfigMap으로 local/eks 환경 분기 |
| 헬스체크 2종 | `/healthz` + `/readyz` | 모델 로딩 중 트래픽 차단 |
| 라이프사이클 | FastAPI `lifespan` | Pod 생성 시 리소스 로딩, 종료 시 정리 |

---

## 인프라 환경 분리 (Kustomize)

| 항목 | local (minikube) | eks (AWS) |
|------|------------------|-----------|
| DB | PG Pod (postgres:16) | RDS PostgreSQL |
| 캐시 | Redis Pod (redis:7) | ElastiCache Redis |
| 모델 저장 | PV (hostPath) | EFS |
| LLM | Bedrock API 직접 호출 | Bedrock (IRSA) |
| 인증 | 없음 | Secret (AWS 크레덴셜) |
| 접근 | port-forward | ALB + HTTPS |

---

## 파일 통계

| 영역 | 파일 수 | 핵심 역할 |
|------|:-------:|-----------|
| shared | 1 | 공통 Pydantic 스키마 |
| chest-svc | 35 | ONNX 3모델 + 14 규칙 + 소견서 |
| ecg-svc | 7 | 규칙 기반 12-lead 분석 |
| blood-svc | 8 | 30+ 검사항목 + 4 복합 평가 |
| orchestrator | 9 | Bedrock 순차 루프 + DB/Redis |
| rag-svc | 6 | FAISS + bge-small 임베딩 |
| report-svc | 6 | Bedrock 종합 소견서 |
| K8s manifests | 15 | base + local + eks overlays |
| CI/CD | 6 | 서비스별 GitHub Actions |
| **합계** | **93** | |

---

## 기술 스택

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
| CI/CD | GitHub Actions → ECR → ArgoCD |
| 환경 관리 | Kustomize (base + overlays) |
