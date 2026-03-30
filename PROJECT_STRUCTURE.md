# DR-AI v3 프로젝트 구조

> v2 Lambda → v3 K8s 마이크로서비스 | ECG ML 통합 + RAG FastEmbed
> 최종 업데이트: 2026-03-30

## 서비스 구성 (8 Pod)

| Service | Port | 역할 | ML 모델 |
|---------|:----:|------|---------|
| central-orchestrator | 8000 | Bedrock LLM 순차 루프 + DB/Redis | - |
| chest-svc | 8000 | CXR 6-Layer (14 질환) | ONNX x3 |
| ecg-svc | 8000 | ECG 13-class ML | ONNX ResNet |
| blood-svc | 8000 | 혈액검사 30+ 항목 | 규칙 기반 |
| rag-svc | 8000 | 유사 케이스 검색 | FastEmbed + FAISS |
| report-svc | 8000 | 종합 소견서 | Bedrock Claude |
| PostgreSQL | 5432 | 환자/세션/결과 | - |
| Redis | 6379 | 세션 캐시 | - |

## 디렉토리 구조

```
v3/
├── services/
│   ├── central-orchestrator/    # Bedrock 순차 루프
│   ├── chest-svc/               # ONNX x3 + 14 규칙 + Bedrock 소견서
│   ├── ecg-svc/                 # ONNX ResNet 13-class + 응급 바이패스
│   ├── blood-svc/               # 규칙 기반 혈액 분석
│   ├── rag-svc/                 # FastEmbed + FAISS 123K
│   └── report-svc/              # Bedrock 종합 소견서
├── shared/schemas.py            # 공통 Pydantic 스키마
├── k8s/base/                    # K8s 매니페스트
├── k8s/overlays/local/          # Docker Desktop
├── k8s/overlays/eks/            # AWS EKS
├── models/                      # ONNX 모델 (Git 미포함, S3)
└── docker-compose.yml

tests/v3/
├── chest-svc/static/            # CXR 테스트 대시보드
├── ecg-svc/static/              # ECG ML 테스트 대시보드
├── ecg-svc/testdata/            # ECG .npy 신호 파일
└── central-orchestrator/static/ # 통합 Jaeger-style 대시보드

docs/
├── 01-plan/features/            # PDCA Plan
├── 02-design/features/          # PDCA Design
├── 03-analysis/                 # Gap 분석
└── 04-report/features/          # 완료 보고서
```

## 모델 파일 (S3 관리)

```
s3://say2-6team/hyunwoo/models/
├── chest-svc/   (unet, densenet, yolov8 — 156MB)
└── ecg-svc/     (ecg_resnet — 33MB)
```
