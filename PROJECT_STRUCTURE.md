# Dr. AI Radiologist v3 — 프로젝트 구조도

> v2 Lambda → v3 EKS 마이크로서비스
> 최종 업데이트: 2026-03-29

---

## 전체 디렉토리 구조

```
say-6-project/
│
├── v3/                                           ← 배포 전용 (컨테이너 + K8s)
│   ├── .dockerignore                                빌드 시 .env, README.md 등 제외
│   ├── docker-compose.yml                           로컬 통합 테스트 (8서비스 + PG + Redis)
│   │
│   ├── models/                                   ← 모델/인덱스 (서비스별 분리)
│   │   ├── chest-svc/                               ONNX 모델 3개 (156MB)
│   │   │   ├── densenet.onnx + .data                  DenseNet-121 14질환 분류
│   │   │   ├── unet.onnx                              UNet 폐/심장 세그멘테이션
│   │   │   └── yolov8.onnx                            YOLOv8 이상소견 탐지
│   │   ├── rag-svc/                                 RAG 인덱스 + 임베더 (489MB)
│   │   │   ├── chest/                                 흉부 판독문 인덱스
│   │   │   │   ├── faiss_index.bin
│   │   │   │   ├── metadata.jsonl
│   │   │   │   └── config.json
│   │   │   ├── ecg/                                   심전도 판독문 인덱스 (원정아 담당)
│   │   │   ├── blood/                                 혈액검사 판독문 인덱스 (팀원C 담당)
│   │   │   └── embedding-model/
│   │   │       └── bge-small-en-v1.5/                 SentenceTransformer 로컬 캐시
│   │   ├── ecg-svc/                                 (규칙 기반, 현재 비어있음)
│   │   └── blood-svc/                               (규칙 기반, 현재 비어있음)
│   │
│   ├── shared/
│   │   └── schemas.py                               공통 Pydantic 스키마 (전 서비스 공유)
│   │
│   ├── services/
│   │   │
│   │   ├── chest-svc/                   [박현우] 흉부 X-Ray 6-Layer 파이프라인
│   │   │   ├── main.py                      FastAPI + lifespan + 조건부 static 서빙
│   │   │   ├── config.py                    환경변수 (MODEL_DIR, RAG_URL, BEDROCK)
│   │   │   ├── pipeline.py                  Seg→DenseNet→YOLO→Clinical→RAG→Report 통합
│   │   │   ├── .env                         로컬 개발용 환경변수
│   │   │   ├── README.md                    서비스 설명 문서
│   │   │   ├── Dockerfile / requirements.txt
│   │   │   ├── layer1_segmentation/         UNet ONNX — 폐/심장 마스크 + CTR 계산
│   │   │   │   ├── __init__.py
│   │   │   │   ├── preprocessing.py             이미지 리사이즈, 정규화
│   │   │   │   └── model.py                     ONNX Runtime 세그멘테이션
│   │   │   ├── layer2_detection/            DenseNet-121 + YOLOv8 ONNX
│   │   │   │   ├── __init__.py
│   │   │   │   ├── densenet.py                  14질환 확률 분류
│   │   │   │   ├── yolo.py                      병변 bbox 검출
│   │   │   │   └── yolo_postprocess.py          YOLO 후처리 (NMS, bbox 정제)
│   │   │   ├── layer3_clinical_logic/       14 Rule + 교차검증 + 감별진단
│   │   │   │   ├── __init__.py
│   │   │   │   ├── engine.py                    임상 분석 엔진 (메인)
│   │   │   │   ├── cross_validation.py          소견 간 교차검증
│   │   │   │   ├── differential.py              감별진단 로직
│   │   │   │   ├── pertinent_negatives.py       관련 음성 소견 보고
│   │   │   │   ├── models.py                    데이터 모델 (dataclass)
│   │   │   │   └── rules/                       14개 질환 규칙
│   │   │   │       ├── __init__.py
│   │   │   │       ├── cardiomegaly.py          심비대
│   │   │   │       ├── pneumonia.py             폐렴
│   │   │   │       ├── pleural_effusion.py      흉수
│   │   │   │       ├── edema.py                 폐부종
│   │   │   │       ├── atelectasis.py           무기폐
│   │   │   │       ├── consolidation.py         경화
│   │   │   │       ├── pneumothorax.py          기흉
│   │   │   │       ├── enlarged_cm.py           종격동 확장
│   │   │   │       ├── lung_opacity.py          폐 혼탁
│   │   │   │       ├── lung_lesion.py           폐 병변
│   │   │   │       ├── fracture.py              골절
│   │   │   │       ├── support_devices.py       지지 장치
│   │   │   │       ├── pleural_other.py         기타 흉막
│   │   │   │       └── no_finding.py            정상 소견
│   │   │   └── report/                      Bedrock Claude → 흉부 소견서 생성
│   │   │       ├── __init__.py
│   │   │       ├── chest_report_generator.py
│   │   │       └── prompt_templates.py
│   │   │
│   │   ├── ecg-svc/                     [원정아] 12-lead ECG 분석
│   │   │   ├── main.py                      FastAPI + lifespan + /healthz + /readyz
│   │   │   ├── config.py / analyzer.py / README.md
│   │   │   ├── report/ecg_report_generator.py
│   │   │   ├── Dockerfile / requirements.txt
│   │   │
│   │   ├── blood-svc/                   [팀원C] 혈액검사 분석
│   │   │   ├── main.py / config.py / analyzer.py / reference_ranges.py / README.md
│   │   │   ├── report/blood_report_generator.py
│   │   │   ├── Dockerfile / requirements.txt
│   │   │
│   │   ├── central-orchestrator/        [팀원D] LLM 순차 검사 루프
│   │   │   ├── main.py                      FastAPI + lifespan + 조건부 static 서빙
│   │   │   ├── config.py / orchestrator.py / session_manager.py
│   │   │   ├── modal_client.py / prompts.py / db.py / README.md
│   │   │   ├── Dockerfile / requirements.txt
│   │   │
│   │   ├── rag-svc/                     [팀원E] 공유 RAG 검색
│   │   │   ├── main.py / config.py / rag_service.py / query_builder.py / README.md
│   │   │   ├── Dockerfile / requirements.txt
│   │   │
│   │   └── report-svc/                  [팀원E] 종합 소견서 생성
│   │       ├── main.py / config.py / report_generator.py / prompt_templates.py / README.md
│   │       ├── Dockerfile / requirements.txt
│   │
│   └── k8s/                                      ← Kubernetes 매니페스트
│       ├── base/                                    전 환경 공통
│       │   ├── namespace.yaml                       dr-ai 네임스페이스
│       │   ├── config.yaml                          공통 ConfigMap
│       │   ├── chest-svc.yaml / ecg-svc.yaml / blood-svc.yaml
│       │   ├── central-orchestrator.yaml / rag-svc.yaml / report-svc.yaml
│       │   └── kustomization.yaml
│       └── overlays/                                네이밍: {용도}.yaml 통일
│           ├── local/                               Docker Desktop K8s
│           │   ├── config.yaml                        로컬 환경 ConfigMap
│           │   ├── secrets.yaml                       AWS 크레덴셜
│           │   ├── storage.yaml                       PV/PVC — hostPath
│           │   ├── postgres.yaml / redis.yaml         로컬 전용 인프라
│           │   └── kustomization.yaml
│           └── eks/                                 AWS EKS
│               ├── config.yaml                        RDS/ElastiCache 엔드포인트
│               ├── secrets.yaml                       AWS 크레덴셜
│               ├── storage.yaml                       EFS StorageClass + PVC
│               └── kustomization.yaml
│
├── tests/                                        ← 테스트 자산
│   └── v3/
│       ├── chest-svc/
│       │   ├── static/                              테스트 UI + 이미지
│       │   │   ├── index.html
│       │   │   └── test-images/ (5장)
│       │   ├── test_chest_svc.py                    통합 테스트
│       │   ├── images/dummy/                        더미 테스트 이미지
│       │   ├── results/                             테스트 결과 JSON + 보고서
│       │   ├── PIPELINE_STAGE_ANALYSIS.md
│       │   └── YOLO_DETECTION_REPORT.md
│       └── central-orchestrator/
│           └── static/index.html                    통합 테스트 UI
│
├── analysis/                                     ← 분석/최적화 결과
│   └── threshold_optimization/
│       ├── youden_optimal_thresholds.json
│       ├── youden_retest_final.json
│       └── youden_retest_results.json
│
├── docs/                                         ← PDCA 문서 + 프로젝트 문서
│   ├── 01-plan/features/
│   ├── 02-design/
│   ├── 03-analysis/
│   ├── 04-report/
│   └── v3-migration/
│       └── V3_MIGRATION_PLAN.md
│
└── PROJECT_STRUCTURE.md                          ← 이 문서
```

---

## 배포 경계

```
v3/ 안에 있으면 = 컨테이너 이미지로 빌드되어 K8s에 올라감
v3/ 밖에 있으면 = 개발/테스트/문서 자산

예외:
  docker-compose.yml  → v3/ 안에 있지만 로컬 개발 도구
  .dockerignore       → README.md, .env 등은 이미지에서 제외
  v3/models/          → Git 추적 (클론 후 바로 사용 가능), 런타임에 볼륨 마운트
```

## 모델 마운트 전략

| 환경 | 스토리지 | 설정 파일 |
|------|---------|----------|
| **docker-compose** | 볼륨 마운트 (`./models/{svc}:/models:ro`) | docker-compose.yml |
| **K8s 로컬** | hostPath → PV/PVC + subPath | k8s/overlays/local/storage.yaml |
| **K8s EKS** | EFS → StorageClass → PV/PVC + subPath | k8s/overlays/eks/storage.yaml |

각 서비스는 컨테이너 내부 `/models` 경로에서 자기 모델만 읽음 (서비스별 subPath 분리)

---

## 서비스 간 통신 흐름

```
[ 사용자 ] → [ ALB / ingress ]
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

## 환경별 실행

| 환경 | 실행 | 설정 |
|------|------|------|
| **uvicorn 로컬** | `cd v3/services/chest-svc && uvicorn main:app` | .env |
| **docker-compose** | `cd v3 && docker-compose up --build` | common-env 앵커 |
| **K8s 로컬** | `kubectl apply -k v3/k8s/overlays/local` | config + secrets |
| **K8s EKS** | `kubectl apply -k v3/k8s/overlays/eks` | ConfigMap + IRSA |

---

## 기술 스택

| 영역 | 기술 |
|------|------|
| 언어 | Python 3.11 |
| 웹 프레임워크 | FastAPI + Uvicorn |
| ML 추론 | ONNX Runtime (CPU) |
| 임계값 최적화 | Youden Index (J-statistic) |
| 컨테이너 | Docker |
| 오케스트레이션 | Kubernetes (Docker Desktop K8s → EKS) |
| DB | PostgreSQL 16 |
| 캐시 | Redis 7 |
| LLM | AWS Bedrock (Claude Sonnet 4.6) |
| RAG | FAISS + bge-small-en-v1.5 |
| 환경 관리 | Kustomize (base + overlays) |
