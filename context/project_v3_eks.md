---
name: project-v3-eks
description: v3 EKS 마이크로서비스 구현 완료 상태. 6개 서비스 + K8s + chest-svc 개선. GitHub feature/MIMIC-CXR-v3 브랜치.
type: project
---

v3 EKS 마이크로서비스 전체 구현 완료 (2026-03-25).

**Why:** v2 Lambda 한계(콜드스타트, 단일 모달, 팀 독립개발 불가) 극복을 위한 K8s 전환.

**How to apply:**
- GitHub: `jeongawon/say-6-project` 브랜치 `feature/MIMIC-CXR-v3` (125파일, 15,582줄)
- 로컬 코드: `/Users/skku_aws2_04/Documents/forpreproject/v3/`
- 가상환경: `v3/venv/` (Python 3.12, fastapi, onnxruntime, httpx 등)
- ONNX 모델: `v3/models/` (unet.onnx, densenet.onnx, yolov8.onnx + .data 파일)
- RAG 인덱스: `v3/models/rag/` (faiss_index.bin 183MB + metadata.jsonl 176MB)
- S3 버킷: `pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an`
- Bedrock 모델: `global.anthropic.claude-sonnet-4-6` (서울 리전)

**서비스 구성:**
- chest-svc: 6-Layer CXR (ONNX 3개 + 14 규칙 + Bedrock 소견서 14초)
- ecg-svc: 12-lead ECG (규칙 기반)
- blood-svc: 혈액검사 30+ 항목
- central-orchestrator: Bedrock LLM 순차 루프 + PG/Redis
- rag-svc: FAISS + bge-small-en-v1.5
- report-svc: Bedrock 종합 소견서

**K8s:** base + overlays (local/eks) + ConfigMap 2-tier (common-config + dr-ai-config)
**chest-svc 개선 적용됨:** 질환별 임계값, pertinent negative, 간결 소견서(48초→14초)
**테스트:** 실제 MIMIC-CXR X-Ray 5장, chest-svc GET / 시각화 UI 내장

**남은 작업:** auth-svc/patient-svc (Phase 4), Terraform EKS, ArgoCD, 프론트엔드
