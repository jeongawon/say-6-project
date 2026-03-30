---
name: K8s Local Validation 완료 상태
description: Docker Desktop K8s에서 6서비스 E2E 검증 완료, RAG 연결, 테스트 대시보드 구현
type: project
---

## K8s Local Validation (2026-03-27)

### 완료된 작업
- Docker Desktop Kubernetes에서 8개 Pod 전부 Running (6서비스 + PostgreSQL + Redis)
- 6개 서비스 Docker 이미지 빌드 완료 (v3/ context 통일)
- Kustomize local overlay로 배포 (base + overlays/local)
- 전체 E2E 파이프라인 성공: Bedrock → ECG → Blood → Chest(ONNX+RAG) → Report

### 수정한 파일들 (v3/)
- `services/*/Dockerfile` (5개) — build context를 v3/로 통일
- `k8s/overlays/local/pv-models.yaml` — hostPath를 Mac 절대경로로 변경
- `k8s/overlays/local/aws-secret.yaml` — 신규 (CHANGE_ME 플레이스홀더)
- `k8s/overlays/local/kustomization.yaml` — aws-secret 추가 + imagePullPolicy 패치
- `k8s/base/common-config.yaml` — RAG_URL/REPORT_URL 경로 수정
- `k8s/overlays/local/configmap.yaml` — CHEST/ECG/BLOOD_URL에 /predict 추가
- `k8s/base/*.yaml` (6개) — envFrom에 aws-credentials secretRef 추가
- `k8s/base/rag-svc.yaml` — MODEL_DIR=/models/rag 오버라이드 + 메모리 2Gi
- `services/central-orchestrator/main.py` — 테스트 UI 라우트 + static 마운트
- `services/central-orchestrator/static/index.html` — Jaeger 스타일 테스트 대시보드
- `services/central-orchestrator/static/testdata/` — 4개 테스트 X-ray 이미지

### 주의사항
- `kubectl apply -k`가 aws-secret.yaml의 CHANGE_ME로 덮어씀 → 매번 AWS Secret 재주입 필요
- rag-svc 메모리 2Gi 필요 (FAISS 123K 벡터 + SentenceTransformer)
- 전체 시스템 Docker Desktop 메모리 10~12GB 권장
- E2E 1건 소요시간: 60~200초 (Bedrock 호출 병목)
- chest-svc 이미지 821MB, rag-svc 이미지 8.84GB (FAISS+build-essential)

### DB 현황 (PostgreSQL)
- patients: 6명, exam_sessions: 18건, modal_results: 25건, comprehensive_reports: 11건
- 테이블: patients, exam_sessions, modal_results, comprehensive_reports

### RAG 서비스
- FAISS IVFFlat 인덱스: 123,974 벡터 (384차원, BAAI/bge-small-en-v1.5)
- 소스: MIMIC-IV Note v2.2 radiology.csv (acute + 2질환 필터)
- 파일: faiss_index.bin (183MB) + metadata.jsonl (176MB) + config.json
- chest-svc → rag-svc POST /search 정상 연결 확인

**Why:** EKS 배포 전 로컬 K8s 통합 검증
**How to apply:** 집에서 재현 시 Docker Desktop K8s 활성화 + 이미지 빌드 + AWS Secret 주입 필요
