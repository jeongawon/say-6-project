# DR-AI v3 — Emergency Medical Diagnostic Platform

> **AI 기반 응급실 다중 모달 진단 보조 플랫폼**
>
> CXR(흉부 X-Ray), ECG(심전도), Blood(혈액검사) 3개 모달의 AI 분석 결과를
> LLM이 통합하여 **구조화된 의료 소견서**를 자동 생성합니다.

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![Kubernetes](https://img.shields.io/badge/Kubernetes-326CE5?logo=kubernetes&logoColor=white)
![AWS](https://img.shields.io/badge/AWS-EKS%20%7C%20Bedrock-FF9900?logo=amazonwebservices&logoColor=white)
![ONNX](https://img.shields.io/badge/ONNX-Runtime-005CED?logo=onnx&logoColor=white)

---

## Architecture

```
                    ┌─────────────────────┐
                    │  central-orchestrator │
                    │  (Bedrock LLM Loop)  │
                    └──────┬──────────────┘
                           │ POST /predict
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ chest-svc│ │  ecg-svc │ │ blood-svc│
        │ ONNX x3  │ │ ONNX ML  │ │ Rule-base│
        │ UNet     │ │ ResNet   │ │ 30+ items│
        │ DenseNet │ │ 13-class │ │          │
        │ YOLOv8   │ │          │ │          │
        └────┬─────┘ └──────────┘ └──────────┘
             │
        ┌────▼─────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐
        │  rag-svc │ │report-svc│ │PostgreSQL│ │  Redis  │
        │ FastEmbed│ │ Bedrock  │ │          │ │         │
        │ FAISS    │ │ 종합소견 │ │          │ │         │
        └──────────┘ └──────────┘ └──────────┘ └─────────┘
```

## Services (6 Microservices + 2 Infra)

| Service | 역할 | 핵심 기술 | Docker Image |
|---------|------|----------|:------------:|
| **central-orchestrator** | Bedrock LLM 순차 루프 + 세션 관리 | FastAPI, Bedrock, PostgreSQL, Redis | 364MB |
| **chest-svc** | 흉부 X-Ray 6-Layer 분석 (14 질환) | ONNX x3 (UNet, DenseNet, YOLOv8) | 821MB |
| **ecg-svc** | 12-lead ECG ML 분석 (13 질환) | ONNX ResNet + 응급 바이패스 | 1.05GB |
| **blood-svc** | 혈액검사 30+ 항목 분석 | 규칙 기반 참조 범위 | 303MB |
| **rag-svc** | 유사 케이스 검색 (MIMIC-IV) | FastEmbed + FAISS 123K 벡터 | 1.2GB |
| **report-svc** | Bedrock LLM 종합 소견서 | Claude Sonnet | 330MB |
| **PostgreSQL** | 환자/세션/결과 저장 | PostgreSQL 16 | - |
| **Redis** | 세션 캐시 | Redis 7 | - |

## Key Features

### ECG ML Integration (v3.1)
- **ONNX ResNet 13-class** ECG 병리 분류 (STEMI, AFib, VFib 등)
- **응급 라벨 바이패스** — 생명 위협 질환 놓침 방지
- **signal_path 분기** — ML(raw .npy) / 규칙(JSON) 하위 호환
- **lifespan 프리로드** + readyz ml_model 상태 연동

### RAG FastEmbed Migration (v3.1)
- **sentence-transformers → fastembed** 교체
- **PyTorch 의존 완전 제거** — Docker 이미지 8.84GB → 1.2GB (86% 감소)
- **기존 FAISS 인덱스 호환** — 재빌드 불필요

### Chest-svc 6-Layer Pipeline
- Layer 1: UNet 폐 영역 세그멘테이션
- Layer 2: DenseNet 14-class + YOLOv8 객체 검출
- Layer 3: 14개 질환별 임상 규칙 엔진
- Layer 4: Pertinent Negative + 감별 진단
- Layer 5: RAG 유사 케이스 검색
- Layer 6: Bedrock 한국어 소견서 생성

## Project Structure

```
v3/
├── services/
│   ├── central-orchestrator/   # LLM 순차 루프 + DB/Redis 세션
│   ├── chest-svc/              # ONNX x3 + 6-Layer CXR 파이프라인
│   ├── ecg-svc/                # ONNX ResNet 13-class ECG ML
│   │   ├── main.py             # lifespan 프리로드 + ML/규칙 분기
│   │   ├── inference.py        # ONNX 추론 엔진
│   │   ├── thresholds.py       # 임계값 SSOT (Lambda 동일)
│   │   ├── signal_processing.py # HR/QTc (scipy)
│   │   ├── model_loader.py     # 단순 ONNX 로더
│   │   └── analyzer.py         # 규칙 기반 폴백
│   ├── blood-svc/              # 혈액검사 규칙 기반 분석
│   ├── rag-svc/                # FastEmbed + FAISS 검색
│   └── report-svc/             # Bedrock 종합 소견서
├── shared/
│   └── schemas.py              # 공통 Pydantic 스키마
├── k8s/
│   ├── base/                   # K8s manifest (6 svc + DB + Redis)
│   └── overlays/
│       ├── local/              # Docker Desktop K8s
│       └── eks/                # AWS EKS
├── models/                     # ONNX 모델 (Git 미포함, S3 관리)
│   ├── chest-svc/              # unet.onnx, densenet.onnx, yolov8.onnx
│   └── ecg-svc/                # ecg_resnet.onnx
└── docker-compose.yml

tests/v3/
├── chest-svc/static/           # CXR 테스트 대시보드
├── ecg-svc/
│   ├── static/                 # ECG 테스트 대시보드
│   └── testdata/               # stemi.npy, normal.npy, afib.npy, hf.npy
└── central-orchestrator/
    └── static/                 # 통합 테스트 대시보드 (Jaeger-style)

docs/
├── 01-plan/features/           # PDCA Plan 문서
├── 02-design/features/         # PDCA Design 문서
├── 03-analysis/                # Gap 분석 문서
└── 04-report/features/         # 완료 보고서
```

## Quick Start (Local K8s)

### Prerequisites
- Docker Desktop + Kubernetes 활성화
- AWS CLI (Bedrock 접근용)
- Python 3.11+

### 1. 모델 파일 다운로드
```bash
# S3에서 모델 다운로드
aws s3 cp s3://say2-6team/hyunwoo/models/ v3/models/ --recursive
```

### 2. Docker 이미지 빌드
```bash
cd v3
for svc in chest-svc ecg-svc blood-svc central-orchestrator rag-svc report-svc; do
  docker build -f services/$svc/Dockerfile -t $svc:latest .
done
```

### 3. K8s 배포
```bash
# AWS 시크릿 설정 (overlays/local/secrets.yaml 수정)
kubectl apply -k k8s/overlays/local/
```

### 4. 확인
```bash
kubectl get pods -n dr-ai
# 8개 Pod 전부 Running 확인
```

## Model Files (S3)

모델 파일은 Git에 포함되지 않습니다. S3에서 다운로드:

```
s3://say2-6team/hyunwoo/models/
├── chest-svc/
│   ├── unet.onnx + unet.onnx.data (85MB)
│   ├── densenet.onnx + densenet.onnx.data (28MB)
│   └── yolov8.onnx (43MB)
└── ecg-svc/
    └── ecg_resnet.onnx (33MB)
```

## Tech Stack

| Category | Technology |
|----------|-----------|
| Language | Python 3.11 |
| Framework | FastAPI + uvicorn |
| ML Runtime | ONNX Runtime |
| Embedding | FastEmbed (bge-small-en-v1.5) |
| Vector DB | FAISS (IVFFlat, 123K vectors) |
| LLM | AWS Bedrock Claude Sonnet |
| Container | Docker |
| Orchestration | Kubernetes (Docker Desktop / EKS) |
| Database | PostgreSQL 16 |
| Cache | Redis 7 |
| IaC | Kustomize (base + overlays) |

## Team

프로젝트 6팀 — 성균관대 AWS AI/ML 과정

## License

Academic Use Only
