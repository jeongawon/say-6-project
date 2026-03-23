# Dr. AI Radiologist — Chest X-Ray Modal

> MIMIC-CXR 기반 응급실 AI 흉부 X-Ray 분석 시스템
> 6-Layer Sequential Pipeline: 세그멘테이션 → 14질환 분류 → 병변 위치 탐지 → 임상 로직 → RAG → AI 소견서

## 프로젝트 개요

응급실에 도착한 환자의 흉부 X-Ray를 6단계 AI 파이프라인으로 분석하여,
구조화된 소견서와 서술형 판독문을 자동 생성하는 시스템입니다.

- **팀**: SKKU 2기 6팀 (5명, 5개 모달)
- **담당**: 흉부 X-Ray 모달 (박현우)
- **데이터**: MIMIC-CXR 94,380장 PA + MIMIC-IV Note 124K 판독문

## 파이프라인 구조

```
CXR 이미지 + 환자정보
    ├── Layer 1 (세그멘테이션) ──┐
    ├── Layer 2a (DenseNet) ─────┼── 병렬 실행
    └── Layer 2b (YOLOv8) ───────┘
                                  ↓
                   Layer 3+4 (임상 로직 + 교차검증)
                                  ↓
                   Layer 5 (RAG 유사 케이스)
                                  ↓
                   Layer 6 (Bedrock 소견서 생성)
```

| Layer | 역할 | 모델 |
|---|---|---|
| Layer 1 | 폐/심장 세그멘테이션, CTR, CP angle 측정 | chest-x-ray-basic (HuggingFace) |
| Layer 2a | 14개 질환 Multi-label Classification | DenseNet-121 (MIMIC-CXR 94K fine-tuned) |
| Layer 2b | 병변 위치 탐지 (Bounding Box) | YOLOv8s (VinDr-CXR 18K fine-tuned) |
| Layer 3+4 | 임상 Rule 판정 + 교차검증 + 감별진단 | 순수 Python Rule Engine |
| Layer 5 | 유사 판독문 검색 (124K건) | bge-small-en-v1.5 + FAISS |
| Layer 6 | 구조화 소견서 + 서술형 판독문 생성 | Claude Sonnet 4.6 (Bedrock) |

## 기술 스택

- **학습**: SageMaker (DenseNet, YOLOv8, UNet)
- **서빙**: AWS Lambda (컨테이너 이미지, 7개 함수)
- **임베딩**: bge-small-en-v1.5 (FastEmbed ONNX)
- **벡터 검색**: FAISS IndexIVFFlat (124K 벡터, 384차원)
- **소견서 생성**: Amazon Bedrock (Claude Sonnet 4.6)
- **인프라**: ECR, S3, Lambda Function URL

## 모델 성능

### DenseNet-121 (14-Disease Classification)
- Mean AUROC: 0.701 (998장 테스트셋)
- Best: Edema 0.854, Pleural Effusion 0.832
- 학습: MIMIC-CXR 94,380장 PA, 2-Stage Fine-tuning

### RAG (유사 판독문 검색)
- 인덱스: 123,974건 양성 소견 판독문
- 임베딩: bge-small-en-v1.5 (384차원)
- CHF 시나리오 유사도: 0.93

## 폴더 구조

```
├── layer1_segmentation/      # Layer 1: 폐/심장 세그멘테이션
├── layer2_detection/         # Layer 2: DenseNet + YOLOv8
├── layer3_clinical_logic/    # Layer 3+4: 임상 로직 + 교차검증
├── layer5_rag/               # Layer 5: RAG (FAISS + bge)
├── layer6_bedrock_report/    # Layer 6: Bedrock 소견서
├── deploy/                   # Lambda 배포 (Dockerfile + 핸들러)
│   ├── layer1_segmentation/
│   ├── layer2_detection/
│   ├── layer2b_yolov8/
│   ├── layer3_clinical_logic/
│   ├── layer5_rag/
│   ├── layer6_bedrock_report/
│   └── chest_modal_orchestrator/  # 통합 파이프라인 (6-Layer E2E)
├── data/                     # 전처리 CSV
├── docs/                     # 설계 문서, 벤치마크
└── notebooks/                # 분석 노트북
```

## 라이브 데모

각 엔드포인트에 GET 요청하면 테스트 페이지가 나옵니다.

- **통합 파이프라인**: [Integrated Pipeline](https://emsptg6o6iwonhhbxyxvasm7ga0yjluu.lambda-url.ap-northeast-2.on.aws/)
- **Layer 1**: [Segmentation](https://jwhljyevn3hm44nhvs5zcdstmi0tmuvi.lambda-url.ap-northeast-2.on.aws/)
- **Layer 2**: [DenseNet Detection](https://pk67s3qrp3b3xluqkcp6neqly40kduol.lambda-url.ap-northeast-2.on.aws/)
- **Layer 2b**: [YOLOv8 Detection](https://yoaval7laoc4ngnkr7uod7dufm0nmxib.lambda-url.ap-northeast-2.on.aws/)

> Cold Start 시 첫 요청에 20~25초 소요됩니다.

## 팀 구성

| 팀원 | 모달 | 데이터 |
|---|---|---|
| 박현우 | **흉부 X-Ray** | MIMIC-CXR, MIMIC-IV Note |
| 원정아 | 심전도 (ECG) | MIMIC-IV ECG |
| 홍경태 | EHR/혈액검사 | MIMIC-IV |
| 양정인 | 임상 텍스트 RAG | MIMIC-IV Note |
| 이정인 | 유전체 위험 | ClinVar + PharmGKB |

## 라이선스

이 프로젝트는 교육 목적으로 제작되었습니다.
MIMIC 데이터는 PhysioNet credentialed access가 필요합니다.
