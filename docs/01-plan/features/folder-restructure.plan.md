# Plan: forpreproject 폴더 재구조화

## Executive Summary

| 관점 | 내용 |
|------|------|
| **Problem** | 교육용 문서, 프롬프트, 구버전 파일이 실제 배포 코드와 뒤섞여 있어 프로젝트 구조 파악이 어려움 |
| **Solution** | 3-영역 분리: `docs/` (교육·관리), `src/` (실행 코드), `deploy/` (배포) |
| **Function UX Effect** | 파일 찾기 시간 단축, S3 업로드 대상 명확화, 새 팀원 온보딩 용이 |
| **Core Value** | 교육 자료와 프로덕션 코드의 명확한 경계 → 관리 효율성 |

---

## 1. 현재 구조 분석

### 루트 디렉토리 문제점
```
forpreproject/
├── CHEST_MODAL_V2_REDESIGN.md          ← 교육/설계 문서 (루트에 산재)
├── CHEST_MODAL_V2_REDESIGN (1).md      ← 중복 파일
├── PROJECT_CONTEXT_FULL.md             ← 교육/관리 문서
├── CONTEXT.md                          ← 세션 컨텍스트
├── CXR_14_PATHOLOGY_READING_CRITERIA.md ← 의학 참고자료
├── MODEL_BENCHMARK.md                  ← 벤치마크 기록
├── PROMPT_Layer3_*.md                  ← 프롬프트 설계 문서 x3
├── record_daily.md                     ← 일일 작업 기록
├── train.csv / train.csv.zip           ← VinDr-CXR 데이터 (루트에 방치)
├── submit_densenet_v3.py               ← 일회성 스크립트
├── test_layer*.py x4                   ← 테스트 스크립트 (루트에 산재)
├── setup_layer1_test.py                ← 일회성 스크립트
│
├── layer1_segmentation/                ← OK (레이어별 코드)
├── layer2_detection/                   ← OK
├── layer3_clinical_logic/              ← OK
├── layer4_cross_validation/            ← OK
├── layer5_rag/                         ← OK
├── layer6_bedrock_report/              ← OK
├── layer6_report/                      ← 구버전 (layer6_bedrock_report로 대체됨)
│
├── data/                               ← CSV + 전처리 결과
├── deploy/                             ← Lambda 배포 코드
├── docs/                               ← bkit PDCA 문서 (미완)
├── logs/                               ← S3 에러 로그
├── notebooks/                          ← 실험 노트북 + 모델 파일 (!!)
├── pipeline/                           ← 통합 파이프라인 (구버전)
└── utils/                              ← 빈 폴더
```

### 주요 문제
1. **교육/관리 문서가 루트에 산재** — 8개 MD 파일이 코드와 혼재
2. **중복 파일** — `CHEST_MODAL_V2_REDESIGN` 2개, `layer6_report` + `layer6_bedrock_report`
3. **일회성 스크립트 루트 방치** — `submit_densenet_v3.py`, `test_*.py` x4
4. **데이터 파일 루트 방치** — `train.csv`, `train.csv.zip` (42MB)
5. **빈 폴더** — `utils/`
6. **모델 파일이 notebooks에** — `best_model_test.pth`
7. **S3 업로드 대상 불명확** — 어디까지가 프로덕션 코드인지 구분 안 됨

---

## 2. 제안 구조

```
forpreproject/
│
├── README.md                           # 프로젝트 개요 + 구조 설명
├── CONTEXT.md                          # 세션 컨텍스트 (Claude용)
├── record_daily.md                     # 일일 작업 기록
│
├── docs/                               # ★ 교육 · 관리 · 참고자료
│   ├── architecture/                   # 시스템 설계 문서
│   │   ├── CHEST_MODAL_V2_REDESIGN.md
│   │   └── API_REFERENCE.md
│   ├── prompts/                        # 레이어별 프롬프트 설계
│   │   ├── PROMPT_Layer3_Clinical_Logic_Engine.md
│   │   ├── PROMPT_Layer5_RAG_FAISS_Titan_With_Details.md
│   │   └── PROMPT_Layer6_Bedrock_Report_Lambda.md
│   ├── reference/                      # 의학·ML 참고자료
│   │   ├── CXR_14_PATHOLOGY_READING_CRITERIA.md
│   │   ├── MODEL_BENCHMARK.md
│   │   └── PROJECT_CONTEXT_FULL.md
│   └── 01-plan/                        # bkit PDCA 문서 (기존 유지)
│       └── features/
│
├── src/                                # ★ 레이어별 소스 코드
│   ├── layer1_segmentation/
│   │   └── sagemaker/
│   ├── layer2_detection/
│   │   ├── densenet/
│   │   └── yolov8/
│   ├── layer3_clinical_logic/
│   │   ├── rules/
│   │   └── tests/
│   ├── layer4_cross_validation/
│   ├── layer5_rag/
│   │   ├── build_index/
│   │   └── tests/
│   └── layer6_bedrock_report/
│       └── tests/
│
├── deploy/                             # ★ Lambda 배포 (기존 유지)
│   ├── deploy_layer1.py
│   ├── deploy_layer2.py
│   ├── deploy_layer2b.py
│   ├── deploy_layer3.py
│   ├── deploy_layer6.py
│   ├── handler.py
│   ├── status_handler.py
│   ├── layer1_segmentation/
│   ├── layer2_detection/
│   ├── layer2b_yolov8/
│   ├── layer3_clinical_logic/
│   ├── layer5_rag/
│   ├── layer6_bedrock_report/
│   └── test_page/
│
├── data/                               # ★ 로컬 데이터 (S3 미러)
│   ├── mimic-cxr-csv/                  # Master CSV 3종
│   └── preprocessing/                  # 전처리 결과 CSV
│
├── notebooks/                          # ★ 실험·분석 노트북
│   ├── 01_densenet121_test_100.ipynb
│   └── 02_gradcam_visualization.ipynb
│
└── scripts/                            # ★ 일회성·유틸리티 스크립트
    ├── submit_densenet_v3.py
    ├── setup_layer1_test.py
    └── test_layer*.py
```

---

## 3. 작업 항목

### Phase 1: 폴더 생성
| # | 작업 | 설명 |
|---|------|------|
| 1 | `docs/architecture/` 생성 | 시스템 설계 문서 |
| 2 | `docs/prompts/` 생성 | 프롬프트 설계 문서 |
| 3 | `docs/reference/` 생성 | 참고자료 |
| 4 | `src/` 생성 | 소스 코드 통합 |
| 5 | `scripts/` 생성 | 일회성 스크립트 |

### Phase 2: 파일 이동
| # | 대상 | From → To |
|---|------|-----------|
| 1 | 설계 문서 | `CHEST_MODAL_V2_REDESIGN.md` → `docs/architecture/` |
| 2 | 프롬프트 x3 | `PROMPT_Layer*.md` → `docs/prompts/` |
| 3 | 참고자료 x3 | `CXR_14_*.md`, `MODEL_BENCHMARK.md`, `PROJECT_CONTEXT_FULL.md` → `docs/reference/` |
| 4 | 레이어 코드 x6 | `layer{1-6}_*/` → `src/layer{1-6}_*/` |
| 5 | 스크립트 x5 | `submit_*.py`, `test_*.py`, `setup_*.py` → `scripts/` |
| 6 | VinDr 데이터 | `train.csv`, `train.csv.zip` → `data/vindr-cxr/` |

### Phase 3: 삭제
| # | 대상 | 이유 |
|---|------|------|
| 1 | `CHEST_MODAL_V2_REDESIGN (1).md` | 중복 |
| 2 | `layer6_report/` | `layer6_bedrock_report/`로 대체됨 |
| 3 | `utils/` | 빈 폴더 |
| 4 | `logs/` | S3 에러 로그, 불필요 |
| 5 | `pipeline/` | 구버전 통합 파이프라인, `deploy/handler.py`로 대체 |
| 6 | `notebooks/best_model_test.pth` | 모델 파일은 S3에 보관 |
| 7 | `notebooks/02_gradcam_visualization.py` | .ipynb와 중복 |

### Phase 4: 문서 작성
| # | 파일 | 내용 |
|---|------|------|
| 1 | `README.md` | 프로젝트 개요, 6-Layer 구조, 폴더 설명, S3 경로 매핑 |

---

## 4. S3 ↔ 로컬 매핑

| 로컬 경로 | S3 경로 | 용도 |
|-----------|---------|------|
| `src/layer2_detection/densenet/` | `code/densenet/` | DenseNet 학습 코드 |
| `src/layer2_detection/yolov8/` | `code/yolov8/` | YOLOv8 학습 코드 |
| `deploy/layer*_*/` | Lambda Container | 배포 코드 (ECR 경유) |
| `data/mimic-cxr-csv/` | `vindr-cxr/raw/` | 원본 CSV |
| `data/preprocessing/` | — | 로컬 전용 |
| — | `models/` | 학습된 모델 (S3만) |
| — | `output/` | 학습 결과 (S3만) |
| `docs/` | — | 교육/관리 문서 (로컬만) |

---

## 5. 주의사항

- `deploy/` 내 import 경로 변경 없음 (Lambda 컨테이너는 독립)
- `layer3_clinical_logic/` 내부에 `from layer3_clinical_logic.engine import ...` 패턴 → `src/` 이동 시 import 경로 확인 필요
- `.bkit/`, `.claude/`, `.pytest_cache/` 등 도구 디렉토리는 이동하지 않음
- `CONTEXT.md`, `record_daily.md`는 루트 유지 (세션 관리용)

---

## 6. 예상 소요

- Phase 1~3 (이동/삭제): 10분
- Phase 4 (README): 5분
- Import 경로 확인: 필요 시 추가
