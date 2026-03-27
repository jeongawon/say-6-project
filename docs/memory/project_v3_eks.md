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
**chest-svc 개선 적용됨 (2026-03-26):**
- QA 전수 분석: 83건 (3 기본PA + 80 S3 PA), 10개 병렬 에이전트 이미지 분석
- Lateral View 게이트: 9건 자동 거부 (pipeline.py view=="Lateral" 조기 리턴)
- YOLO 후처리: CTR 기반 Cardiomegaly 보완(FN 17→0), 경계 FP 필터, PTX threshold 0.15
- 마스크 후처리: connected component 파편 제거 + Heart 횡격막 클리핑 (scipy.ndimage)
- Clinical Rules 개선: 7개 규칙 파일 수정 (PTX 세그 기반 검출, 감별진단 3패턴 추가, severity/recommendation, SpO2 연동)
- Finding 스키마 확장: severity/location/recommendation 필드 추가
- 프론트엔드: 드롭다운 80건 PA Only, 측정 SVG 한글 라벨, CTR 측정선 추가
- Youden's J 임계값 최적화: 61건 GT ROC 분석, 7/13 질환 배율 ≤2.0
- 최종: 평균 양성 11개→3.9개 (-65%), Cardiomegaly FN 0건

**테스트:** 83건 MIMIC-CXR (3 기본 PA + 80 S3 PA), chest-svc GET / 시각화 UI (드롭다운)
**결과 위치:** `tests/chest-svc/results/full_80/` (오버레이 83장 + FULL_QA_REPORT.md + analysis_group_0~9.md)
**PDCA 문서:** `docs/01-plan/features/chest-svc-qa-fix.plan.md`, `threshold-optimization.plan.md`

**다음 세션 TODO (우선순위 순):**
1. 🔴 **전체 MIMIC-CXR GT로 Youden's J 재계산** — 83건은 통계 부족, 전체 p10_pa로 ROC 분석 필요
   - `mimic-cxr-csv/mimic-cxr-2.0.0-chexpert.csv` + metadata 조인
   - 특히 Consolidation(AUC 0.682), Fracture(AUC 0.441) 개선 기대
   - CTR 보완 기준 0.50→0.53 (AP뷰 borderline 제외)
2. 🟡 git commit + push (현재 미커밋 상태)
3. 🟡 Bedrock 소견서 + RAG 연동 재테스트 (skip 해제 후)
4. 🟢 남은 서비스: auth-svc/patient-svc (Phase 4), Terraform EKS, ArgoCD, 프론트엔드
