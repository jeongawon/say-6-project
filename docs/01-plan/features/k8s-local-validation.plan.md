# k8s-local-validation Planning Document

> **Summary**: Docker Desktop Kubernetes에서 6개 마이크로서비스 전체를 로컬 배포하고, 서비스 간 통신 + healthcheck + API 호출까지 E2E 검증
>
> **Project**: dr-ai (say-6-project)
> **Version**: v3
> **Author**: 박현우 (6팀)
> **Date**: 2026-03-27
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | v3 EKS 마이크로서비스 코드가 완성되었지만, 실제 K8s 환경에서 6개 서비스가 정상 동작하는지 검증되지 않았다. Docker 단독 실행과 K8s 오케스트레이션은 네트워킹/볼륨/환경변수 주입 방식이 다르므로, EKS 배포 전에 로컬에서 먼저 확인해야 한다. |
| **Solution** | Docker Desktop 내장 Kubernetes를 활성화하고, Kustomize local overlay로 6개 서비스 + PostgreSQL + Redis를 배포. 단계별로 이미지 빌드 → 매니페스트 적용 → healthcheck 확인 → 서비스 간 호출 → 전체 파이프라인 E2E 테스트를 진행한다. |
| **Function/UX Effect** | 로컬에서 `kubectl apply -k` 한 번으로 전체 시스템이 K8s 위에서 돌아가고, port-forward로 central-orchestrator에 접근하여 실제 의료 영상 분석 파이프라인을 테스트할 수 있다. |
| **Core Value** | EKS 배포 전 K8s 레벨 통합 검증 완료 — 배포 후 발생할 수 있는 서비스 디스커버리, 볼륨 마운트, 리소스 부족 등의 문제를 사전에 잡는다. |

---

## Context Anchor

| Key | Value |
|-----|-------|
| **WHY** | v3 코드 완성 후 EKS 배포 전, K8s 환경에서의 통합 동작을 로컬에서 사전 검증 |
| **WHO** | 6팀 개발자 (박현우) — 로컬 Mac 환경 |
| **RISK** | 모델 파일 볼륨 마운트 실패, AWS Bedrock 자격증명 누락, 메모리 부족(6서비스+DB+Redis) |
| **SUCCESS** | 6개 Pod 전부 Running + 전체 E2E 파이프라인 200 OK 응답 |
| **SCOPE** | Phase 1: 환경 준비 → Phase 2: 이미지 빌드 → Phase 3: K8s 배포 → Phase 4: 검증 |

---

## 1. Overview

### 1.1 Purpose

v3에서 구현된 6개 마이크로서비스(chest-svc, ecg-svc, blood-svc, central-orchestrator, rag-svc, report-svc)와 인프라(PostgreSQL, Redis)가 Kubernetes 환경에서 정상 동작하는지 EKS 배포 전에 로컬에서 검증한다.

### 1.2 Background

- 현재까지 v3 코드는 개별 서비스 단위로 `python main.py` 또는 Docker 단독 실행으로만 테스트됨
- K8s 환경에서는 네트워킹(ClusterIP DNS), 볼륨 마운트(PV/PVC), ConfigMap/Secret 주입, Probe 기반 헬스체크 등이 추가됨
- 이 차이 때문에 "로컬에서 되는데 K8s에서 안 되는" 문제가 빈번하게 발생
- Docker Desktop Kubernetes가 macOS에서 가장 간단한 로컬 K8s 환경

### 1.3 Related Documents

- v3 EKS 마이그레이션 계획: `docs/01-plan/features/v3-eks-migration.plan.md`
- K8s 매니페스트: `v3/k8s/base/`, `v3/k8s/overlays/local/`

---

## 2. Scope

### 2.1 In Scope

- [x] Docker Desktop Kubernetes 활성화 및 클러스터 확인
- [ ] 6개 서비스 Docker 이미지 로컬 빌드
- [ ] Dockerfile build context 문제 수정 (central-orchestrator 등)
- [ ] 모델 볼륨 hostPath를 실제 Mac 경로로 수정
- [ ] AWS Bedrock 자격증명 Secret 생성
- [ ] `kubectl apply -k k8s/overlays/local/` 로 전체 배포
- [ ] 6개 Pod 전부 Running 상태 확인
- [ ] healthcheck (/healthz, /readyz) 응답 확인
- [ ] 서비스 간 통신 확인 (orchestrator → chest/ecg/blood → rag → report)
- [ ] central-orchestrator port-forward 후 E2E API 호출 테스트
- [ ] 발견된 문제점 수정 및 재배포

### 2.2 Out of Scope

- EKS 실제 배포 (이번은 로컬 검증만)
- Ingress / LoadBalancer 설정
- HPA(Horizontal Pod Autoscaler) 테스트
- CI/CD 파이프라인 구축
- 성능/부하 테스트

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | Docker Desktop K8s 클러스터에 dr-ai 네임스페이스 생성 | High | Pending |
| FR-02 | 6개 서비스 Docker 이미지를 로컬에서 빌드 | High | Pending |
| FR-03 | PostgreSQL + Redis Pod 정상 기동 및 연결 확인 | High | Pending |
| FR-04 | ONNX 모델 파일 볼륨 마운트 (hostPath → Mac 로컬 경로) | High | Pending |
| FR-05 | AWS Bedrock 자격증명 Secret 생성 및 Pod 주입 | High | Pending |
| FR-06 | 6개 서비스 Pod 전부 Running + Ready 상태 | High | Pending |
| FR-07 | central-orchestrator port-forward 후 E2E 분석 요청 성공 | High | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| 리소스 | Mac에서 전체 클러스터 구동 가능 (CPU 4core+, RAM 10~12Gi 권장) | Docker Desktop Settings → Resources 확인 |
| 기동 시간 | 전체 서비스 Ready까지 3분 이내 | Pod 시작 ~ Ready 시간 측정 |
| 안정성 | 5분 이상 OOMKilled/CrashLoop 없이 유지 | `kubectl get pods --watch` |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] Docker Desktop K8s 활성화 및 `kubectl get nodes` 정상
- [ ] 6개 서비스 이미지 빌드 성공 (`docker images | grep -E "chest|ecg|blood|central|rag|report"`)
- [ ] `kubectl apply -k v3/k8s/overlays/local/` 에러 없이 적용
- [ ] `kubectl get pods -n dr-ai` — 전부 Running (1/1 Ready)
- [ ] `kubectl logs <pod> -n dr-ai` — 각 서비스 시작 로그 정상
- [ ] `curl localhost:<port>/healthz` — 모든 서비스 200 OK
- [ ] E2E 테스트: central-orchestrator에 흉부 X-Ray 분석 요청 → 200 + 유효한 JSON 응답

### 4.2 Quality Criteria

- [ ] CrashLoopBackOff 없음
- [ ] OOMKilled 없음
- [ ] 서비스 간 DNS 해석 정상 (chest-svc:8000, ecg-svc:8000 등)

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| **메모리 부족** — 6서비스+DB+Redis가 Mac에서 메모리 초과 (chest-svc ONNX 3모델이 특히 큼) | High | Medium | Docker Desktop 메모리 할당 10~12Gi 권장. chest-svc 리소스 limits를 로컬용으로 하향 가능 (2Gi→1.5Gi) |
| **모델 볼륨 마운트 실패** — Docker Desktop K8s의 hostPath가 macOS 경로와 다를 수 있음 | High | Medium | Docker Desktop은 `/Users/` 경로를 자동 공유. pv-models.yaml의 hostPath를 절대경로로 수정 |
| **Dockerfile build context 불일치** — central-orchestrator의 `COPY ../shared`가 context 밖 참조 | High | High | v3/ 루트를 build context로 사용하도록 Dockerfile 수정. `-f` 옵션 활용 |
| **AWS 자격증명 누락** — Bedrock 호출 서비스(rag-svc, report-svc)가 인증 실패 | Medium | Medium | aws-credentials Secret 생성 후 envFrom으로 주입 |
| **이미지 pull 정책** — `imagePullPolicy: Always`면 로컬 이미지를 무시하고 레지스트리에서 pull 시도 | Medium | Low | local overlay에서 `imagePullPolicy: Never` 또는 `IfNotPresent` 패치 |

---

## 6. Impact Analysis

### 6.1 Changed Resources

| Resource | Type | Change Description |
|----------|------|--------------------|
| `k8s/overlays/local/pv-models.yaml` | K8s PV | hostPath를 Mac 절대경로로 변경 |
| `k8s/overlays/local/kustomization.yaml` | Kustomize | aws-secret.yaml 리소스 추가 + imagePullPolicy 패치 |
| `k8s/overlays/local/aws-secret.yaml` | K8s Secret | **신규** — AWS Bedrock 자격증명 |
| 각 서비스 Dockerfile | Docker | build context 통일 (v3/ 루트 기준) |
| 각 서비스 Deployment YAML | K8s | envFrom에 aws-credentials secretRef 추가 |

### 6.2 Current Consumers

| Resource | Operation | Code Path | Impact |
|----------|-----------|-----------|--------|
| pv-models.yaml | READ | chest-svc Pod → /models 마운트 | hostPath 경로 변경 필요 |
| common-config | READ | 모든 서비스 Pod envFrom | 변경 없음 |
| Dockerfile | BUILD | `docker build` 시 | context 경로 주의 |

### 6.3 Verification

- [ ] hostPath 변경 후 chest-svc에서 모델 파일 접근 가능 확인
- [ ] AWS Secret 주입 후 rag-svc에서 Bedrock 호출 성공 확인
- [ ] 모든 서비스 이미지 빌드 성공 확인

---

## 7. Architecture Considerations

### 7.1 Project Level Selection

| Level | Characteristics | Recommended For | Selected |
|-------|-----------------|-----------------|:--------:|
| **Starter** | Simple structure | Static sites | |
| **Dynamic** | Feature-based modules, BaaS | Web apps with backend | |
| **Enterprise** | Microservices, K8s, Terraform | High-traffic systems | **v** |

### 7.2 Key Architectural Decisions

| Decision | Options | Selected | Rationale |
|----------|---------|----------|-----------|
| 로컬 K8s 환경 | Docker Desktop K8s / Minikube / Kind | Docker Desktop K8s | Mac에서 가장 간단, 별도 설치 불필요 |
| 매니페스트 관리 | Kustomize / Helm / 직접 YAML | Kustomize | 이미 base/overlay 구조 구현 완료 |
| 이미지 빌드 | docker build / docker compose | docker build | 서비스별 개별 빌드, context = v3/ |
| 볼륨 마운트 | hostPath / emptyDir+initContainer | hostPath | Mac 파일시스템 직접 마운트 |

### 7.3 배포 아키텍처 (로컬)

```
Docker Desktop Kubernetes (단일 노드)
┌─────────────────────────────────────────────────────┐
│  Namespace: dr-ai                                   │
│                                                     │
│  ┌─────────────────────┐  ┌──────────┐ ┌─────────┐ │
│  │ central-orchestrator │  │ postgres │ │  redis  │ │
│  │     :8000            │  │  :5432   │ │  :6379  │ │
│  └─────┬───┬───┬───────┘  └──────────┘ └─────────┘ │
│        │   │   │                                    │
│   ┌────┘   │   └────┐                              │
│   ▼        ▼        ▼                              │
│ ┌─────┐ ┌─────┐ ┌───────┐                          │
│ │chest│ │ ecg │ │ blood │                           │
│ │:8000│ │:8000│ │ :8000 │                           │
│ └─────┘ └─────┘ └───────┘                          │
│   │                                                 │
│   ▼                                                 │
│ ┌─────────┐  ┌────────────┐                        │
│ │ rag-svc │→│ report-svc │                          │
│ │  :8000  │  │   :8000    │                          │
│ └─────────┘  └────────────┘                        │
│                                                     │
│  Volume: models-pvc ← hostPath (Mac 로컬 경로)     │
│  Secret: aws-credentials (Bedrock 인증)             │
└─────────────────────────────────────────────────────┘
     ↑ port-forward :8000
     │
   개발자 (curl / 브라우저)
```

---

## 8. Implementation Steps (4 Phases)

### Phase 1: 환경 준비 (Prerequisites)

```bash
# Step 1-1: Docker Desktop → Settings → Kubernetes → Enable Kubernetes → Apply
# UI에서 체크 후 Apply & Restart (약 2~3분 소요)

# Step 1-2: 클러스터 확인
kubectl config use-context docker-desktop
kubectl get nodes
# NAME             STATUS   ROLES           AGE   VERSION
# docker-desktop   Ready    control-plane   ...   v1.xx

# Step 1-3: Docker Desktop 리소스 확인 (Settings → Resources)
# CPU: 4+ cores, Memory: 10~12 GB 권장 (최소 8GB)
# chest-svc ONNX 3모델 로딩이 메모리를 가장 많이 사용
# 모델은 이미지에 포함하지 않고 hostPath 볼륨으로 마운트 (빌드 속도 최적화)
```

### Phase 2: Docker 이미지 빌드

모든 이미지는 `v3/` 디렉토리를 build context로 사용:

```bash
cd v3/

# 6개 서비스 이미지 빌드 (각각 -f로 Dockerfile 지정)
docker build -f services/chest-svc/Dockerfile -t chest-svc:latest .
docker build -f services/ecg-svc/Dockerfile -t ecg-svc:latest .
docker build -f services/blood-svc/Dockerfile -t blood-svc:latest .
docker build -f services/central-orchestrator/Dockerfile -t central-orchestrator:latest .
docker build -f services/rag-svc/Dockerfile -t rag-svc:latest .
docker build -f services/report-svc/Dockerfile -t report-svc:latest .

# 빌드 확인
docker images | grep -E "chest|ecg|blood|central|rag|report"
```

> **주의**: Dockerfile의 COPY 경로가 v3/ context 기준으로 작성되어야 함.
> 예: `COPY services/chest-svc/requirements.txt .` (chest-svc는 이미 이 패턴)
> central-orchestrator의 `COPY ../shared`는 `COPY shared/ /app/shared/`로 수정 필요.

### Phase 3: K8s 매니페스트 수정 및 배포

#### 3-1: hostPath 수정 (pv-models.yaml)

```yaml
# 변경 전
hostPath:
  path: /data/models

# 변경 후 — Mac 로컬 절대경로
hostPath:
  path: /Users/skku_aws2_04/Documents/forpreproject/v3/models
  type: Directory
```

#### 3-2: AWS Secret 생성 (aws-secret.yaml — 신규)

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: aws-credentials
  namespace: dr-ai
type: Opaque
stringData:
  AWS_ACCESS_KEY_ID: "<your-key>"
  AWS_SECRET_ACCESS_KEY: "<your-secret>"
  AWS_DEFAULT_REGION: "ap-northeast-2"
```

#### 3-3: Kustomization에 리소스 추가 + imagePullPolicy 패치

```yaml
# k8s/overlays/local/kustomization.yaml
resources:
  - ../../base
  - configmap.yaml
  - postgres.yaml
  - redis.yaml
  - pv-models.yaml
  - aws-secret.yaml        # 추가

# imagePullPolicy 패치 (로컬 이미지 사용)
patches:
  - target:
      kind: Deployment
    patch: |-
      - op: add
        path: /spec/template/spec/containers/0/imagePullPolicy
        value: Never
```

#### 3-4: 각 서비스 Deployment에 AWS Secret 주입

base YAML의 envFrom에 추가:
```yaml
envFrom:
  - configMapRef:
      name: common-config
  - configMapRef:
      name: dr-ai-config
  - secretRef:                # 추가
      name: aws-credentials   # 추가
```

#### 3-5: 배포 실행

```bash
# Kustomize 빌드 미리보기 (문법 검증)
kubectl kustomize v3/k8s/overlays/local/

# 배포
kubectl apply -k v3/k8s/overlays/local/

# Pod 상태 감시
kubectl get pods -n dr-ai -w
```

### Phase 4: 검증

```bash
# 4-1: Pod 상태 확인
kubectl get pods -n dr-ai
# 모든 Pod이 Running (1/1 Ready) 상태여야 함

# 4-2: 서비스 로그 확인
kubectl logs -n dr-ai deploy/chest-svc --tail=20
kubectl logs -n dr-ai deploy/central-orchestrator --tail=20

# 4-3: healthcheck 확인 (Pod 내부에서)
kubectl exec -n dr-ai deploy/central-orchestrator -- \
  python -c "import urllib.request; print(urllib.request.urlopen('http://chest-svc:8000/healthz').read())"

# 4-4: port-forward로 외부 접근
kubectl port-forward -n dr-ai svc/central-orchestrator 8000:8000 &

# 4-5: E2E 테스트 — 흉부 X-Ray 분석 요청
curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "patient_id": "TEST-001",
    "patient_info": {
      "age": 65,
      "sex": "M",
      "chief_complaint": "chest pain",
      "history": ["hypertension"]
    },
    "modals": ["chest"],
    "data": {
      "chest": {
        "image_base64": "<base64-encoded-xray>"
      }
    }
  }'
# 기대: 200 OK + 분석 결과 JSON

# 4-6: 리소스 사용량 확인
kubectl top pods -n dr-ai
```

---

## 9. Dockerfile 수정 사항 (사전 파악)

| 서비스 | 현재 상태 | 수정 필요 | 내용 |
|--------|-----------|:---------:|------|
| chest-svc | `COPY services/chest-svc/` (v3/ context) | 없음 | 이미 올바름 |
| ecg-svc | 확인 필요 | 가능 | context = v3/ 기준 COPY 확인 |
| blood-svc | 확인 필요 | 가능 | context = v3/ 기준 COPY 확인 |
| central-orchestrator | `COPY ../shared` (상위 참조) | **필요** | `COPY shared/ /app/shared/`로 변경 |
| rag-svc | 확인 필요 | 가능 | context = v3/ 기준 COPY 확인 |
| report-svc | 확인 필요 | 가능 | context = v3/ 기준 COPY 확인 |

---

## 10. Troubleshooting Guide

| 증상 | 원인 | 해결 |
|------|------|------|
| Pod `Pending` | PVC 바인딩 실패 | `kubectl describe pvc models-pvc -n dr-ai` → hostPath 경로 확인 |
| Pod `CrashLoopBackOff` | 모델 파일 없음 or import 에러 | `kubectl logs <pod> -n dr-ai` → 에러 메시지 확인 |
| Pod `OOMKilled` | 메모리 부족 | Docker Desktop 메모리 → 10Gi+ 또는 리소스 limits 하향 |
| `ImagePullBackOff` | imagePullPolicy 문제 | `imagePullPolicy: Never` 패치 확인 |
| 서비스 간 통신 실패 | DNS 미해석 | `kubectl exec <pod> -- nslookup chest-svc.dr-ai.svc.cluster.local` |
| Bedrock 401 | AWS 자격증명 누락 | `kubectl get secret aws-credentials -n dr-ai -o yaml` 확인 |

---

## 11. Next Steps

1. [ ] Plan 확정 후 Design 문서 작성 (`/pdca design k8s-local-validation`)
2. [ ] Phase 1~4 순차 실행
3. [ ] 발견된 이슈 수정 후 재검증
4. [ ] 검증 완료 시 EKS 배포 진행

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-27 | Initial draft | 박현우 |
