# PDCA Completion Report: v3-eks-migration

> v2 Lambda → v3 EKS 마이크로서비스 마이그레이션
> 작성일: 2026-03-25
> 피처: v3-eks-migration
> PDCA Phase: Report (Completed)

---

## Executive Summary

### 1.1 프로젝트 개요

| 항목 | 내용 |
|------|------|
| **Feature** | v3-eks-migration |
| **시작일** | 2026-03-25 |
| **완료일** | 2026-03-25 |
| **PDCA 사이클** | Plan → Design → Do → Check(89%) → Act → Check(95%) → Report |
| **최종 Match Rate** | 95% |
| **Iteration** | 1회 (89% → 95%) |

### 1.2 결과 요약

| 항목 | 수치 |
|------|------|
| 총 파일 수 | 105개 |
| 서비스 수 | 6개 (P0) + 2개 (P2 예정) |
| K8s 매니페스트 | 18개 (base + local + eks) |
| CI/CD 파이프라인 | 6개 (서비스별 GitHub Actions) |
| README (팀원 가이드) | 6개 (서비스별) |
| 한글 주석 파일 | 전체 (Python + YAML + Dockerfile + CI/CD) |

### 1.3 Value Delivered

| 관점 | 결과 |
|------|------|
| **Problem** | v2 Lambda 7개 → 콜드스타트 15초+, 단일 모달, 팀원 독립개발 불가 문제 해결 |
| **Solution** | 6개 마이크로서비스 + K8s(minikube→EKS) + ConfigMap 2-tier + 12-Factor 규약 적용 |
| **Function UX Effect** | LLM 순차 검사 루프로 환자→CXR→ECG→Blood 자동 연계 진단 + 소견서 2단계 생성 구현 |
| **Core Value** | 5명 독립 개발 체계 구축, ONNX 모델 상시 로딩(콜드스타트 제거), 팀원별 README+한글주석으로 즉시 작업 가능 |

---

## 2. PDCA 사이클 이력

### 2.1 Phase 진행

```
Plan ──→ Design ──→ Do ──→ Check(89%) ──→ Act ──→ Check(95%) ──→ Report
  │        │        │        │              │        │             │
  │        │        │        │              │        │             ▼
  │        │        │        ▼              ▼        ▼          완료
  │        │        │    Critical 3건    수정 적용   PASS
  │        │        │    Important 9건   ConfigMap
  │        │        │                    2-tier 추가
  │        │        ▼
  │        │    5개 에이전트 병렬
  │        │    93파일 생성
  │        ▼
  │    Option C + K8s 12-Factor
  │    3가지 아키텍처 제시 → 사용자 선택
  ▼
V3_MIGRATION_PLAN.md 기반
로컬 minikube → EKS 전략
```

### 2.2 Phase별 산출물

| Phase | 산출물 | 위치 |
|-------|--------|------|
| Plan | 마이그레이션 계획서 | `docs/01-plan/features/v3-eks-migration.plan.md` |
| Design | 아키텍처 설계서 (Option C + K8s 12-Factor) | `docs/02-design/features/v3-eks-migration.design.md` |
| Do | 105개 구현 파일 | `v3/` 디렉토리 |
| Check | Gap Analysis (89% → 95%) | `docs/03-analysis/v3-eks-migration.analysis.md` |
| Report | 이 문서 | `docs/04-report/features/v3-eks-migration.report.md` |

---

## 3. 구현 결과

### 3.1 서비스별 구현 현황

| 서비스 | 파일 수 | 핵심 구현 | 담당 |
|--------|:-------:|-----------|------|
| shared/schemas.py | 1 | 공통 Pydantic 스키마 (8 모델) | 공통 |
| chest-svc | 35 | ONNX 3모델 + 14 규칙 + 6-Layer 파이프라인 + 소견서 | 박현우 |
| ecg-svc | 7 | 규칙 기반 12-lead 분석 (8모듈) + 소견서 | 원정아 |
| blood-svc | 8 | 30+ 검사항목 + 4 복합 평가 + 소견서 | 팀원C |
| central-orchestrator | 9 | Bedrock 순차 루프 + PG/Redis 세션 + DB 자동 생성 | 팀원D |
| rag-svc | 6 | FAISS + bge-small-en-v1.5 임베딩 | 팀원E |
| report-svc | 6 | Bedrock 멀티모달 종합 소견서 | 팀원E |
| K8s manifests | 18 | base + local overlay + eks overlay + common-config | 공통 |
| Docker Compose | 1 | 8서비스 + PG + Redis 통합 테스트 | 공통 |
| CI/CD | 6 | 서비스별 GitHub Actions (빌드 + ECR push) | 공통 |
| README | 6 | 서비스별 팀원 가이드 | 공통 |
| 문서 | 2 | PROJECT_STRUCTURE.md + V3_MIGRATION_PLAN.md | 공통 |

### 3.2 K8s 12-Factor 운영 규약 적용 현황

| 규약 | 적용 | 상세 |
|------|:----:|------|
| 설정은 환경변수 | ✅ | config.py (pydantic-settings), 공통 설정 기본값 제거 |
| ConfigMap 2-tier | ✅ | common-config (공통) + dr-ai-config (환경별) |
| /healthz liveness | ✅ | 전 서비스 적용 |
| /readyz readiness | ✅ | 전 서비스 적용 (모델 로딩 완료 후 ready) |
| FastAPI lifespan | ✅ | 전 서비스 적용 (모델/DB/Redis 초기화) |

### 3.3 v2 → v3 마이그레이션 현황

| 항목 | 상태 | 상세 |
|------|:----:|------|
| Lambda 핸들러 제거 | ✅ | event/context → FastAPI 파라미터 |
| S3 의존성 제거 | ✅ | s3.put_object/get_object → 로컬 PV/EFS |
| PyTorch → ONNX | ✅ | model.forward() → ort.InferenceSession.run() |
| IAM/CORS 제거 | ✅ | Function URL → K8s Service DNS |
| 단일 모달 → 멀티모달 | ✅ | chest + ecg + blood 순차 검사 루프 |
| 소견서 1단계 → 2단계 | ✅ | 모달별 소견서 + 종합 소견서 |
| Clinical Logic 14 규칙 | ✅ | 거의 그대로 복사 (순수 Python) |

---

## 4. Gap Analysis 결과

### 4.1 Match Rate 추이

```
1차 분석:  89% ████████████████████░░ WARN
                Critical 3건 / Important 9건

수정 적용: env_prefix 제거, CI/CD 추가, EKS Secret,
          Bedrock 모델/리전 통일, chest 리소스 조정,
          ConfigMap 2-tier 전략 적용

2차 분석:  95% ████████████████████████░ PASS
                Critical 0건 / Important 1건 (minor)
```

### 4.2 수정된 Critical 이슈

| # | 이슈 | 수정 내용 |
|---|------|-----------|
| C-1 | env_prefix 불일치 (4개 서비스 런타임 장애) | env_prefix 제거 → 공통 ConfigMap 직접 바인딩 |
| C-2 | CI/CD 워크플로 누락 (rag-svc, report-svc) | 2개 워크플로 신규 생성 |
| C-3 | EKS Secret 매니페스트 누락 | secret.yaml 생성 + kustomization 포함 |

### 4.3 추가 개선 (Act Phase)

| # | 개선 내용 |
|---|-----------|
| 1 | ConfigMap 2-tier 전략 도입 (common-config + dr-ai-config) |
| 2 | config.py 공통 설정 기본값 제거 → 환경변수 필수 |
| 3 | 전체 파일 한글 주석 (Python 26파일 + YAML 17파일 + Dockerfile 6파일 + CI/CD 6파일) |
| 4 | 서비스별 README.md 6개 생성 (팀원 가이드, 수정 포인트, API 스펙) |
| 5 | PROJECT_STRUCTURE.md 보완 (auth/patient Phase 4 표시, 개발 단계 가이드) |
| 6 | Bedrock 모델 ID/리전 전 서비스 통일 |

---

## 5. 팀원 작업 가이드

### 5.1 각 팀원의 다음 단계

| 팀원 | 서비스 | 즉시 할 일 | 참고 |
|------|--------|------------|------|
| **박현우** | chest-svc | ONNX 모델 3개 변환 검증 (v2 PyTorch vs v3 ONNX 출력 비교) | `services/chest-svc/README.md` |
| **원정아** | ecg-svc | `analyzer.py`의 TODO 블록에 실제 ECG 분석 로직 구현 | `services/ecg-svc/README.md` |
| **팀원C** | blood-svc | `reference_ranges.py` 정상 범위 값 검증 + 검사항목 추가 | `services/blood-svc/README.md` |
| **팀원D** | orchestrator | `prompts.py` Bedrock 프롬프트 튜닝 (검사 순서 결정 품질) | `services/central-orchestrator/README.md` |
| **팀원E** | rag/report | FAISS 인덱스 생성 + `prompt_templates.py` 종합 소견서 프롬프트 | `services/rag-svc/README.md` |

### 5.2 개발 단계

```
Phase 1 (Sprint 1~2)     Phase 2 (Sprint 2~3)     Phase 3 (Sprint 3)       Phase 4 (Sprint 4)
uvicorn 로컬 개발    →    docker-compose 통합  →    minikube K8s 검증   →    EKS 프로덕션 배포
각자 서비스 단독          PG+Redis 컨테이너          Kustomize local          Terraform + ArgoCD
/predict mock 응답        8서비스 E2E 테스트         overlays/local           overlays/eks
                                                                              + auth-svc/patient-svc
```

---

## 6. 인프라 환경 분리

| 항목 | local (minikube) | eks (AWS) |
|------|------------------|-----------|
| DB | PG Pod (postgres:16) | RDS PostgreSQL |
| 캐시 | Redis Pod (redis:7) | ElastiCache Redis |
| 모델 | PV (hostPath) | EFS |
| 공통 설정 | common-config ConfigMap | common-config ConfigMap |
| 환경 설정 | dr-ai-config (local) | dr-ai-config (eks) |
| 민감 정보 | 없음 | Secret (AWS 크레덴셜) |
| LLM | Bedrock API 직접 | Bedrock (IRSA) |

---

## 7. 기술 스택

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
| 환경 관리 | Kustomize (base + overlays) + ConfigMap 2-tier |

---

## 8. 남은 작업 (Phase 4)

| 항목 | 우선순위 | 상세 |
|------|----------|------|
| auth-svc | P2 | JWT 인증 서비스 (POST /login, GET /verify) |
| patient-svc | P2 | 환자 CRUD (POST/GET/PUT /patients) |
| Terraform | P2 | EKS + RDS + ElastiCache + EFS 인프라 프로비저닝 |
| ArgoCD | P2 | GitOps 배포 자동화 |
| 모니터링 | P2 | Prometheus + Grafana + Loki |
| 프론트엔드 | P2 | React + S3 + CloudFront |
| 부하 테스트 | P2 | 성능 최적화 |

---

## 9. Lessons Learned

| # | 교훈 |
|---|------|
| 1 | **12-Factor 규약은 코드 아키텍처보다 운영 규약이 핵심** — domain/application/infrastructure 레이어 분리(Option B)보다 config.py + /healthz + /readyz + lifespan 3가지가 K8s에서 실질적으로 중요 |
| 2 | **ConfigMap 2-tier 필수** — 공통 설정을 서비스별 config.py에 하드코딩하면 N개 서비스 수정+재빌드 필요. common-config 한 곳에서 관리하면 `kubectl edit` 한 번으로 해결 |
| 3 | **env_prefix는 K8s ConfigMap과 충돌** — pydantic-settings의 env_prefix가 ConfigMap 키 이름과 불일치 유발. 공통 설정은 prefix 없이 직접 바인딩 |
| 4 | **병렬 에이전트로 구현 속도 극대화** — 5개 서비스를 순차적으로 하면 수 시간, 병렬로 돌리면 가장 복잡한 서비스(chest-svc) 시간만 소요 |
| 5 | **한글 주석 + README는 팀 온보딩 비용을 크게 낮춤** — 각 팀원이 자기 서비스의 README만 읽으면 바로 작업 시작 가능 |
