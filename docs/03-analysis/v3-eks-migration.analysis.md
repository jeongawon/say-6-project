# Gap Analysis: v3-eks-migration

> Design vs Implementation 비교 분석
> 분석일: 2026-03-25
> Match Rate: **89%**
> 상태: WARN (90% 미만 — 수정 필요)

---

## Context Anchor

| 항목 | 내용 |
|------|------|
| **WHY** | Lambda 콜드스타트/단일 모달 한계 극복, 팀원별 독립 서비스 개발 체계 구축 |
| **WHO** | 6팀 5명 (박현우-chest, 원정아-ecg, 팀원C-blood, 팀원D-orchestrator, 팀원E-shared) |
| **RISK** | K8s 학습곡선, 서비스 간 통신 장애, ONNX 변환 정합성, Bedrock 비용 |
| **SUCCESS** | 로컬 minikube에서 환자→순차검사→종합소견서 E2E 성공 |
| **SCOPE** | 8개 서비스 + K8s + CI/CD |

---

## 카테고리별 점수

| 카테고리 | 점수 | 상태 |
|----------|:----:|:----:|
| K8s 12-Factor 규약 | 95% | PASS |
| 서비스 파일 구조 | 88% | WARN |
| 공통 스키마 | 97% | PASS |
| K8s 매니페스트 | 82% | WARN |
| Docker Compose | 90% | PASS |
| CI/CD 파이프라인 | 67% | WARN |
| API Contract | 95% | PASS |
| v2 마이그레이션 | 98% | PASS |
| DB 스키마 | 90% | PASS |
| Plan 성공 기준 | 85% | WARN |
| **전체** | **89%** | **WARN** |

---

## Critical Issues (3건)

### C-1. config.py env_prefix 불일치 — 런타임 장애 유발

4개 서비스(ecg, blood, rag, report)가 `env_prefix`를 사용하여 ConfigMap 변수가 바인딩되지 않음.

| 서비스 | Design | 구현 | 영향 |
|--------|--------|------|------|
| ecg-svc | prefix 없음 | `ECG_` | `RAG_URL` → `ECG_RAG_URL` 필요 |
| blood-svc | prefix 없음 | `BLOOD_` | 동일 |
| rag-svc | prefix 없음 | `RAG_` | 동일 |
| report-svc | prefix 없음 | `REPORT_` | 동일 |

**수정**: 4개 서비스 config.py에서 `env_prefix` 제거

### C-2. CI/CD 워크플로 누락 (2개)

- `rag-svc.yml` 없음
- `report-svc.yml` 없음

**수정**: chest-svc.yml 복사 후 서비스명/경로 변경

### C-3. K8s EKS Secret 누락

- `k8s/overlays/eks/secret.yaml` 없음 (AWS 크레덴셜)

**수정**: Secret 매니페스트 생성

---

## Important Issues (9건)

| # | 항목 | Design | 구현 | 영향 |
|---|------|--------|------|------|
| I-1 | Bedrock 모델 ID (ecg/blood) | claude-sonnet-4-6 | claude-3-5-sonnet | 모델 버전 불일치 |
| I-2 | Bedrock region (ecg) | ap-northeast-2 | us-east-1 | 리전 불일치 |
| I-3 | chest-svc CPU request | 1 core | 500m | 모델 로딩 시 throttling |
| I-4 | chest-svc memory request | 2Gi | 1Gi | ONNX 3개 OOM 위험 |
| I-5 | K8s resource 전략 | requests=limits | requests=50% limits | 설계 차이 |
| I-6 | ConfigMap URL 경로 | /search, /generate 포함 | base URL만 | 경로 누락 가능 |
| I-7 | ecg-svc models/ 디렉토리 | 있음 | 없음 | 구조 누락 |
| I-8 | docker-compose version | 3.9 | 3.8 | 마이너 |
| I-9 | DB patients PK | id VARCHAR(20) | patient_id TEXT | 컬럼명 차이 |

---

## 요약

- **총 93개 파일** 구현, Design 대비 89% 일치
- **Critical 3건**: env_prefix 런타임 장애, CI/CD 2개 누락, EKS Secret 누락
- **Important 9건**: 대부분 설정값 차이
- **v2 마이그레이션 98%**: Lambda/S3 의존성 완전 제거, ONNX 전환 완료
