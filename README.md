# Dr. AI — Emergency Medical Diagnostic Platform

> **AI 기반 응급실 다중 모달 진단 보조 플랫폼**
>
> CXR(흉부 X-Ray), ECG(심전도), Blood(혈액검사) 3개 모달의 AI 분석 결과를
> LLM이 통합하여 **구조화된 의료 소견서**를 자동 생성합니다.

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![Kubernetes](https://img.shields.io/badge/Kubernetes-326CE5?logo=kubernetes&logoColor=white)
![AWS](https://img.shields.io/badge/AWS-EKS%20%7C%20Bedrock-FF9900?logo=amazonwebservices&logoColor=white)
![License](https://img.shields.io/badge/License-Academic-blue)

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [Services](#services)
- [Quick Start](#quick-start)
- [Deployment](#deployment)
- [Model Pipeline (chest-svc)](#model-pipeline-chest-svc)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Data Sources](#data-sources)
- [Team](#team)
- [Version History](#version-history)
- [Disclaimer](#disclaimer)

---

## Overview

**Dr. AI**는 응급실 환경에서 의료진의 판독을 보조하기 위한 **다중 모달 AI 진단 플랫폼**입니다.

환자의 흉부 X-Ray, 심전도, 혈액검사 데이터를 각각의 전문 마이크로서비스가 분석하고,
LLM 기반 오케스트레이터가 **"다음에 어떤 검사를 해야 하는가"** 를 판단하며,
최종적으로 3개 모달의 분석 결과를 종합한 **구조화된 의료 소견서**를 생성합니다.

### 현재 구현 상태

| 모달 | 서비스 | AI 모델 | 상태 |
|------|--------|---------|------|
| **흉부 X-Ray** | chest-svc | UNet + DenseNet-121 + YOLOv8 (ONNX) | **구현 완료** |
| **심전도** | ecg-svc | 규칙 기반 12-lead 분석 | 스켈레톤 |
| **혈액검사** | blood-svc | 규칙 기반 30+ 항목 분석 | 스켈레톤 |

> **첫 번째 Use Case**: MIMIC-CXR 데이터셋 기반 흉부 X-Ray 14질환 분석

---

## Key Features

- **6-Layer Deep Pipeline** — 세그멘테이션 → 분류 → 탐지 → 임상로직 → RAG → 소견서, 단일 API 호출로 전체 파이프라인 실행
- **LLM 기반 검사 오케스트레이션** — Bedrock Claude가 환자 상태에 따라 다음 검사를 자동 결정
- **Evidence-Based Report** — FAISS 벡터DB에서 유사 전문의 판독문을 검색하여 RAG 근거 삽입
- **14-Disease Clinical Rules** — CheXpert 14개 질환별 임상 규칙 엔진 + Youden 최적 임계값
- **Kustomize Multi-Environment** — 로컬(Docker Desktop) / EKS(프로덕션) 동일 매니페스트, overlay만 교체
- **ONNX Runtime CPU 추론** — GPU 없이 CPU만으로 실시간 추론 (PyTorch 대비 1/15 크기)

---

## Architecture

```
                          ┌──────────────────────────────────────┐
                          │          Kubernetes Cluster           │
                          │                                      │
[ Client ] ── ALB ──────▶ │  central-orchestrator                │
                          │    │  Bedrock "다음 검사?" 루프       │
                          │    │                                  │
                          │    ├──▶ chest-svc ──▶ rag-svc        │
                          │    │    UNet/DenseNet    FAISS 검색   │
                          │    │    /YOLOv8(ONNX)   bge-small    │
                          │    │                                  │
                          │    ├──▶ ecg-svc                      │
                          │    │    12-lead 규칙 분석              │
                          │    │                                  │
                          │    ├──▶ blood-svc                    │
                          │    │    CBC/BMP/BNP 규칙 분석         │
                          │    │                                  │
                          │    └──▶ report-svc                   │
                          │         Bedrock 종합 소견서           │
                          │                                      │
                          │  ┌─────────┐  ┌─────────┐           │
                          │  │ Postgres │  │  Redis  │           │
                          │  │  (영구)  │  │ (세션)  │           │
                          │  └─────────┘  └─────────┘           │
                          └──────────────────────────────────────┘
                                         │
                          ┌──────────────────────────────────────┐
                          │       Models Volume (PVC/EFS)         │
                          │  chest-svc/  rag-svc/  ecg-svc/ ...  │
                          └──────────────────────────────────────┘
```

---

## Services

| 서비스 | 포트 | 엔드포인트 | 역할 |
|--------|:----:|-----------|------|
| **chest-svc** | 8000 | `POST /predict` | 흉부 X-Ray 이미지 → 6-Layer 파이프라인 → 흉부 소견서 |
| **ecg-svc** | 8000 | `POST /predict` | 12-lead ECG 데이터 → 규칙 기반 분석 → 심전도 소견서 |
| **blood-svc** | 8000 | `POST /predict` | 혈액검사 JSON → 30+ 항목 분석 → 혈액 소견서 |
| **central-orchestrator** | 8000 | `POST /examine` | 환자 세션 → LLM 검사 순서 결정 → 결과 누적 → 종합 요청 |
| **rag-svc** | 8000 | `POST /search` | 소견 텍스트 → FAISS 유사도 검색 → Top-K 판독문 |
| **report-svc** | 8000 | `POST /generate` | 3모달 소견서 + RAG 근거 → Bedrock 종합 소견서 |

모든 서비스는 `/healthz` (liveness) + `/readyz` (readiness) 헬스체크를 제공합니다.

---

## Quick Start

### 사전 요구사항

- Docker Desktop (K8s 활성화) 또는 Docker Compose
- AWS 계정 (Bedrock Claude 접근 권한)
- 약 700MB 디스크 (모델 파일 포함)

### 1. 클론 및 환경 설정

```bash
git clone https://github.com/<org>/say-6-project.git
cd say-6-project
```

모델 파일은 Git에 포함되어 있으므로 별도 다운로드가 필요 없습니다.

### 2. AWS 크레덴셜 설정

```bash
# v3/services/chest-svc/.env (로컬 uvicorn용)
AWS_ACCESS_KEY_ID=your-key
AWS_SECRET_ACCESS_KEY=your-secret

# K8s 배포 시 secrets.yaml에 설정
```

### 3. 실행

```bash
# Option A: Docker Compose (가장 간단)
cd v3
docker-compose up --build

# Option B: Kubernetes (Docker Desktop)
kubectl apply -k v3/k8s/overlays/local

# Option C: 단일 서비스 개발
cd v3/services/chest-svc
pip install -r requirements.txt
uvicorn main:app --reload
```

### 4. 테스트

```bash
# chest-svc 헬스체크
curl http://localhost:8000/healthz

# 흉부 X-Ray 분석 요청
curl -X POST http://localhost:8000/predict \
  -F "file=@test_image.jpg"
```

---

## Deployment

| 환경 | 명령어 | DB/Redis | 모델 스토리지 |
|------|--------|----------|-------------|
| **docker-compose** | `docker-compose up --build` | 컨테이너 내장 | 볼륨 마운트 |
| **K8s 로컬** | `kubectl apply -k v3/k8s/overlays/local` | StatefulSet (파드) | hostPath PV |
| **K8s EKS** | `kubectl apply -k v3/k8s/overlays/eks` | RDS + ElastiCache | EFS PV |

### Kustomize 구조

```
k8s/
├── base/                    # 공통 서비스 정의 (6 서비스 + ConfigMap + Namespace)
└── overlays/
    ├── local/               # imagePullPolicy: Never, hostPath, 로컬 PG/Redis
    └── eks/                 # ECR 이미지, EFS, RDS/ElastiCache 엔드포인트
```

---

## Model Pipeline (chest-svc)

chest-svc의 6-Layer 파이프라인은 단일 `POST /predict` 호출로 아래 순서를 실행합니다:

```
Input Image (JPEG/PNG)
    │
    ▼
┌─ Layer 1: Segmentation ──────────────────────────┐
│  UNet ONNX (85MB)                                 │
│  폐/심장 마스크 → CTR(심흉비) 계산               │
└───────────────────────────────────────────────────┘
    │
    ▼
┌─ Layer 2: Detection ─────────────────────────────┐
│  DenseNet-121 ONNX (27MB) → 14질환 확률          │
│  YOLOv8 ONNX (43MB) → 병변 bbox 검출            │
│  Youden 최적 임계값으로 양성/음성 판정           │
└───────────────────────────────────────────────────┘
    │
    ▼
┌─ Layer 3: Clinical Logic ────────────────────────┐
│  14개 질환별 규칙 엔진                            │
│  교차검증 (소견 간 일관성 체크)                   │
│  감별진단 + 관련 음성 소견 보고                   │
└───────────────────────────────────────────────────┘
    │
    ▼
┌─ Layer 4: RAG ───────────────────────────────────┐
│  rag-svc 호출 → FAISS Top-5 유사 판독문 검색     │
│  bge-small-en-v1.5 임베딩 (384차원)              │
└───────────────────────────────────────────────────┘
    │
    ▼
┌─ Layer 5-6: Report Generation ───────────────────┐
│  AWS Bedrock Claude Sonnet                        │
│  임상 데이터 + RAG 근거 → 구조화된 흉부 소견서   │
└───────────────────────────────────────────────────┘
    │
    ▼
Output: Structured Radiology Report (JSON)
```

### 모델 사양

| 모델 | 파일 | 크기 | 입력 | 출력 |
|------|------|:----:|------|------|
| UNet | `unet.onnx` | 85MB | `(1,1,320,320)` | 폐/심장 마스크 + view/age/sex |
| DenseNet-121 | `densenet.onnx` | 27MB | `(1,3,224,224)` | 14질환 logits |
| YOLOv8 | `yolov8.onnx` | 43MB | `(1,3,1024,1024)` | bbox + class scores |

---

## Tech Stack

| 계층 | 기술 | 용도 |
|------|------|------|
| **Application** | Python 3.11 / FastAPI / Uvicorn | 마이크로서비스 API |
| **ML Inference** | ONNX Runtime (CPU) | UNet, DenseNet, YOLOv8 추론 |
| **LLM** | AWS Bedrock (Claude Sonnet) | 검사 오케스트레이션 + 소견서 생성 |
| **RAG** | FAISS + bge-small-en-v1.5 | 유사 판독문 벡터 검색 |
| **Data** | PostgreSQL 16 / Redis 7 | 영구 저장 / 세션 캐시 |
| **Container** | Docker / Kubernetes | 컨테이너화 + 오케스트레이션 |
| **IaC** | Kustomize (base + overlays) | 환경별 K8s 매니페스트 관리 |
| **Cloud** | AWS EKS / EFS / RDS / ElastiCache | 프로덕션 인프라 |

---

## Project Structure

자세한 디렉토리 트리는 [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)를 참조하세요.

```
say-6-project/
├── v3/                          # 배포 영역 (컨테이너 + K8s)
│   ├── services/                #   6개 마이크로서비스 소스코드
│   ├── models/                  #   ONNX 모델 + FAISS 인덱스 + 임베딩 모델
│   ├── shared/                  #   공통 Pydantic 스키마
│   ├── k8s/                     #   Kubernetes 매니페스트 (base + overlays)
│   ├── docker-compose.yml       #   로컬 통합 테스트
│   └── .dockerignore
├── tests/                       # 테스트 자산
├── analysis/                    # Youden 임계값 최적화 결과
├── docs/                        # PDCA 문서
├── PROJECT_STRUCTURE.md         # 상세 구조도
└── README.md                    # 이 문서
```

---

## Data Sources

| 데이터셋 | 규모 | 용도 |
|----------|------|------|
| **MIMIC-CXR** | 377K 이미지 (PA 96K) | 흉부 X-Ray + CheXpert 14질환 라벨 |
| **MIMIC-IV Note** | 판독문 텍스트 | RAG 벡터DB 원본 (전문의 판독문) |
| **MIMIC-IV EHR** | 전자건강기록 | 환자 컨텍스트 (향후 연동) |

> 학습 데이터: PA view only, p10 그룹 필터링 → 최종 9,118장 (train 8,993 / val 65 / test 60)

---

## Team

| 역할 | 담당자 | 서비스 |
|------|--------|--------|
| chest-svc 개발 / 인프라 설계 | 박현우 | chest-svc, K8s, docker-compose |
| ECG 분석 | 원정아 | ecg-svc |
| 혈액검사 분석 | 팀원C | blood-svc |
| 오케스트레이터 | 팀원D | central-orchestrator |
| RAG + 리포트 | 팀원E | rag-svc, report-svc |

---

## Version History

| 버전 | 브랜치 | 아키텍처 | 상태 |
|------|--------|---------|------|
| v1 | `feature/MIMIC-CXR` | AWS Lambda x7 + PyTorch | 완료 |
| v2 | `feature/MIMIC-CXR-v2` | AWS Lambda x2 + ONNX | 폐기 (IAM 권한 제약) |
| **v3** | **`feature/MIMIC-CXR-v3`** | **Kubernetes 마이크로서비스 x6** | **진행중** |

### v3에서 달라진 점

- Lambda → K8s 마이크로서비스 전환 (IAM 권한 제약 해소)
- PyTorch 700MB → ONNX 155MB (모델 경량화)
- 모놀리식 Lambda → 서비스별 독립 배포/스케일링
- Kustomize로 로컬/EKS 환경 통합 관리
- FAISS + SentenceTransformer 로컬 임베딩 (외부 API 의존성 제거)

---

## Disclaimer

> 이 프로젝트는 **학술 연구 및 교육 목적**으로 개발되었습니다.
> 실제 임상 환경에서의 진단 도구로 사용할 수 없으며,
> 의료 전문가의 판단을 대체하지 않습니다.
>
> MIMIC 데이터셋은 PhysioNet Credentialed Access 하에 사용되며,
> 모든 환자 데이터는 비식별화(de-identified)되어 있습니다.
