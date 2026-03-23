# Dr. AI Radiologist - 프로젝트 폴더 구조

> 마지막 업데이트: 2026-03-23 (v3 — Layer 2b 통합, 마스크 보정, YOLO 오버레이)

```
forpreproject/
│
├── 📋 루트 문서 ─────────────────────────────────────────────
│
│   📖 [학습/공부용 문서] — 나중에 복습할 때 이것부터 읽기
├── CXR_14_PATHOLOGY_READING_CRITERIA.md # ⭐ 14개 질환별 실제 방사선과 전문의 판독 기준
│                                        #    각 질환마다 "어디를, 무엇을, 어떤 징후로" 판독하는지
│                                        #    Atelectasis~Support Devices 14개 전부 정리
│                                        #    출처: Radiopaedia, RSNA, StatPearls 등
├── MODEL_BENCHMARK.md                  # ⭐ DenseNet-121 성능 벤치마크
│                                        #    질환별 AUROC, 학습 설정, 2-Stage Fine-tuning 전략
│                                        #    pos_weight, 데이터 불균형, 성능 등급 분석
├── CHEST_MODAL_V2_REDESIGN.md          # ⭐ 흉부 모달 v2 전면 재설계 문서
│                                        #    실제 응급실 시나리오 (67세 남성 흉통)로 전체 흐름 설명
│                                        #    오케스트레이터가 어떻게 순차적으로 검사를 결정하는지
│                                        #    6-Layer 파이프라인 각 레이어의 역할과 입출력
├── PROJECT_CONTEXT_FULL.md             # ⭐ 프로젝트 전체 컨텍스트 (팀 구성, 5개 모달, 아키텍처)
│                                        #    v1→v2 재설계 이유, 오케스트레이터의 3가지 결정
│                                        #    MIMIC-CXR 데이터셋 구조, 6-Layer 설계 의도
│
│   📋 [운영/기록 문서]
├── CONTEXT.md                          # 세션 간 작업 맥락 (S3 동기화)
├── record_daily.md                     # 일별 개발 기록 (3/20~ 전처리, 학습, 배포 전 과정)
├── CHEST_MODAL_V2_REDESIGN (1).md      # (CHEST_MODAL_V2_REDESIGN 사본)
│
│   📋 [Claude Code 구현 프롬프트] — 각 레이어 구현 시 사용한 상세 스펙
├── PROMPT_Layer3_Clinical_Logic_Engine.md # Layer 3 구현 지시서 (14개 Rule 스펙)
├── PROMPT_Layer5_RAG_FAISS_Titan_With_Details.md # Layer 5 구현 지시서 (FAISS+Titan 스펙)
├── PROMPT_Layer6_Bedrock_Report_Lambda.md # Layer 6 구현 지시서 (Bedrock 소견서 스펙)
├── PROMPT_Integrated_Modal_Orchestrator.md # 통합 오케스트레이터 구현 지시서
├── PROMPT_Docker_Image_Optimization.md   # Docker 이미지 최적화 가이드
├── PROMPT_UI_Redesign_All_Layers.md      # 전 레이어 UI 통일 리디자인 스펙
├── PROMPT_Step3_Filter_Positive_and_Build_Index.md # RAG 인덱스 필터링 스펙
│
│
├── 📋 루트 스크립트 ─────────────────────────────────────────
├── setup_layer1_test.py                # Layer 1 테스트 환경 셋업
├── test_layer1_app.py                  # Layer 1 Lambda 통합 테스트
├── test_layer2.py                      # Layer 2 모델 단위 테스트
├── test_layer2_app.py                  # Layer 2 Lambda 통합 테스트
├── test_layer2_cli.py                  # Layer 2 CLI 테스트
├── submit_densenet_v3.py               # DenseNet v3 SageMaker 학습 제출
├── submit_training_jobs.ipynb          # 학습 작업 제출 노트북
├── index_for.html                      # 포트폴리오 인덱스 페이지
├── train.csv.zip                       # 학습 CSV 압축본
│
│
├── 📁 data/ ── 데이터셋 & 전처리 ────────────────────────────
│   ├── mimic-cxr-csv/                  # MIMIC-CXR 공식 CSV (원본)
│   │   ├── mimic-cxr-2.0.0-chexpert.csv    # CheXpert 14질환 라벨 (9.3MB)
│   │   ├── mimic-cxr-2.0.0-metadata.csv    # 이미지 메타데이터 (58MB)
│   │   └── mimic-cxr-2.0.0-split.csv       # train/val/test 분할 (26MB)
│   │
│   └── preprocessing/                 # 전처리 결과물
│       ├── build_official_master.py        # Master CSV 빌드 스크립트
│       ├── p10_train_ready.csv             # 최종 학습용 CSV (9,118장)
│       ├── p10_train_ready_resplit.csv     # 재분할 버전
│       ├── p10_pa_training.csv             # PA Only 학습 데이터
│       ├── p10_pa_test100.csv              # 테스트 100장
│       ├── p10_pa_image_paths.txt          # 이미지 경로 목록
│       ├── pos_weights.json                # 14질환 클래스 가중치
│       ├── preprocessing_report.txt        # 전처리 리포트
│       └── copied_files.txt                # S3 복사 파일 목록
│
│
├── 📁 layer1_segmentation/ ── [Layer 1] 폐/심장 세그멘테이션 ✅ 배포됨 ──
│   │   모델: ianpan/chest-x-ray-basic (HF pretrained)
│   │   클래스: background=0, R_Lung=1, L_Lung=2, Heart=3
│   │   CXR 규약: 이미지 좌=환자 우(R Lung), 이미지 우=환자 좌(L Lung)
│   │   중심선 보정: 좌우 폐 교차 픽셀 재분류 (16%→0%)
│   ├── preprocessing.py                # 이미지 전처리 (resize, normalize)
│   ├── segmentation_model.py           # UNet 모델 정의
│   ├── train_unet.py                   # UNet 학습 스크립트
│   └── sagemaker/                      # SageMaker 학습 설정
│       ├── 01_download_chexmask.ipynb      # ChexMask 다운로드 노트북
│       ├── 01_download_chexmask.py         # ChexMask 다운로드 스크립트
│       ├── 02_train_unet.ipynb             # UNet 학습 노트북
│       └── training_job_config.json        # 학습 작업 설정
│
│
├── 📁 layer2_detection/ ── [Layer 2] 14질환 탐지 모델 ✅ 배포됨 ──
│   ├── densenet/                       # DenseNet-121 (14-label 분류)
│   │   ├── detection_model.py              # DenseNet 모델 정의
│   │   ├── train.py                        # 단일GPU 학습
│   │   ├── train_multigpu.py               # 멀티GPU 학습
│   │   ├── eval_densenet.py                # 평가 (SageMaker용)
│   │   ├── eval_local.py                   # 로컬 평가
│   │   ├── run_eval.py                     # 평가 실행기
│   │   ├── eval_results.json               # 평가 결과 (AUC 등)
│   │   ├── roc_data.json                   # ROC 곡선 데이터
│   │   ├── training_job_config.json        # 단일GPU 학습 설정
│   │   ├── training_job_config_multigpu.json # 멀티GPU 학습 설정
│   │   ├── DENSENET_WORK_SUMMARY.md        # DenseNet 작업 요약서
│   │   ├── TRAINING_JOB_GUIDE.md           # 학습 작업 가이드
│   │   ├── submit_multigpu_job.ipynb       # 멀티GPU 제출 노트북
│   │   └── sagemaker/
│   │       └── 03_train_densenet_full.ipynb # Full 학습 노트북
│   │
│   └── yolov8/                         # YOLOv8 (병변 위치 탐지)
│       ├── train.py                        # YOLOv8 학습 스크립트
│       ├── preprocess_vindr.py             # VinDr-CXR 전처리
│       ├── preprocess_vindr.ipynb          # VinDr 전처리 노트북
│       ├── yolov8_train_local.ipynb        # 로컬 학습 노트북
│       └── YOLOV8_WORK_SUMMARY.md         # YOLOv8 작업 요약서
│
│
├── 📁 layer3_clinical_logic/ ── [Layer 3] 임상 로직 엔진 ✅ 배포됨 ──
│   ├── __init__.py
│   ├── engine.py                       # 통합 엔진 (14개 Rule 실행)
│   ├── clinical_engine.py              # 임상 판독 엔진 (메인)
│   ├── cross_validation.py             # DenseNet↔YOLO↔Rule 교차검증
│   ├── differential.py                 # 감별진단 생성기
│   ├── models.py                       # 데이터 모델 (Finding, Result)
│   ├── thresholds.py                   # 14질환 판정 임계값
│   ├── mock_data.py                    # 테스트용 mock 데이터
│   ├── rules/                          # 14개 질환별 판정 Rule
│   │   ├── __init__.py
│   │   ├── atelectasis.py                  # 무기폐
│   │   ├── cardiomegaly.py                 # 심비대
│   │   ├── consolidation.py                # 경화
│   │   ├── edema.py                        # 폐부종
│   │   ├── enlarged_cm.py                  # 심종격동 확장
│   │   ├── fracture.py                     # 골절
│   │   ├── lung_lesion.py                  # 폐 병변
│   │   ├── lung_opacity.py                 # 폐 음영
│   │   ├── no_finding.py                   # 정상
│   │   ├── pleural_effusion.py             # 흉수
│   │   ├── pleural_other.py                # 기타 흉막
│   │   ├── pneumonia.py                    # 폐렴
│   │   ├── pneumothorax.py                 # 기흉
│   │   └── support_devices.py              # 삽입 기구
│   └── tests/
│       ├── __init__.py
│       └── test_engine.py              # 27개 단위 테스트
│
│
├── 📁 layer4_cross_validation/ ── [Layer 4] 교차검증 (미구현)
│   └── (비어 있음 — Layer 3에 교차검증 포함됨)
│
│
├── 📁 layer5_rag/ ── [Layer 5] RAG (FAISS + bge-small-en-v1.5) ✅ 배포됨 ──
│   ├── __init__.py
│   ├── config.py                       # RAG 설정 (S3, bge-small-en-v1.5 모델)
│   ├── rag_service.py                  # RAG 서비스 (S3→FAISS 로드 + 검색)
│   ├── query_builder.py                # Layer 3 결과 → 영문 검색 쿼리 변환
│   ├── mock_data.py                    # 테스트용 mock 데이터 (10 reports + 4 scenarios)
│   ├── build_index/                    # FAISS 인덱스 빌드 파이프라인
│   │   ├── __init__.py
│   │   ├── run_all.py                      # 전체 빌드 실행
│   │   ├── step1_extract_reports.py        # MIMIC-IV 판독문 추출 (880K)
│   │   ├── step2_embedding.ipynb           # SageMaker GPU 임베딩 (bge-small-en-v1.5)
│   │   ├── step3_filter_positive.py        # 양성 소견 필터링 (880K → 124K)
│   │   ├── step3_build_faiss_index.py      # FAISS IndexIVFFlat 생성
│   │   └── step4_upload_to_s3.py           # S3 업로드
│   ├── build_output/                   # 빌드 산출물 (로컬, git 제외)
│   │   ├── reports.jsonl               # 880K 판독문 (1.2GB)
│   │   ├── embeddings.npy              # 880K × 384d (1.3GB)
│   │   ├── embeddings_filtered.npy     # 124K × 384d (182MB)
│   │   ├── metadata_filtered.jsonl     # 124K 메타데이터 (176MB)
│   │   └── faiss_index.bin             # FAISS IndexIVFFlat (183MB)
│   └── tests/
│       ├── __init__.py
│       └── test_rag.py                 # RAG 단위 테스트
│
│
├── 📁 layer6_bedrock_report/ ── [Layer 6] Bedrock 소견서 생성 ✅ 배포됨 ──
│   ├── __init__.py
│   ├── config.py                       # Bedrock 모델 설정 (Sonnet 4.6)
│   ├── models.py                       # 입출력 데이터 클래스
│   ├── prompt_templates.py             # 시스템/유저 프롬프트 (KO/EN)
│   ├── report_generator.py             # Bedrock 호출 + JSON 파싱
│   ├── rag_placeholder.py              # RAG placeholder (향후 FAISS)
│   ├── mock_data.py                    # 4개 테스트 시나리오
│   └── tests/
│       ├── __init__.py
│       └── test_report.py              # 27개 단위 테스트
│
│
├── 📁 deploy/ ── Lambda 배포 ─────────────────────────────────
│   ├── DEPLOY_GUIDE.md                 # 배포 가이드 문서
│   ├── deploy_layer1.py                # Layer 1 배포 자동화
│   ├── deploy_layer2.py                # Layer 2 (DenseNet) 배포
│   ├── deploy_layer2b.py               # Layer 2b (YOLOv8) 배포
│   ├── deploy_layer3.py                # Layer 3 배포 자동화
│   ├── deploy_integrated.py            # 통합 오케스트레이터 배포 자동화
│   ├── deploy_layer5.py                # Layer 5 배포 자동화
│   ├── deploy_layer6.py                # Layer 6 배포 자동화
│   ├── fix_cors.py                     # CORS 이중 헤더 버그 수정 스크립트
│   ├── handler.py                      # 공통 Lambda 핸들러 (구버전)
│   ├── status_handler.py               # 상태 확인 핸들러
│   ├── Dockerfile                      # 공통 Dockerfile (구버전)
│   ├── requirements.txt                # 공통 의존성 (구버전)
│   │
│   ├── layer1_segmentation/            # Layer 1 Lambda 컨테이너
│   │   ├── Dockerfile                      # Python 3.12 + PyTorch (~1.5GB)
│   │   ├── lambda_function.py              # GET→테스트UI, POST→분할 API
│   │   │                                   #   중심선(midline) 보정 로직 포함
│   │   │                                   #   L/R 폐 교차 픽셀 재분류 (16%→0%)
│   │   ├── index.html                      # 테스트 웹 UI
│   │   ├── requirements.txt                # torch, torchvision, pillow
│   │   ├── seg_result.json                 # 분할 결과 예시
│   │   └── list_result.json                # 모델 목록 예시
│   │
│   ├── layer2_detection/               # Layer 2 (DenseNet) Lambda
│   │   ├── Dockerfile                      # Python 3.12 + PyTorch (~1.2GB)
│   │   ├── lambda_function.py              # GET→테스트UI, POST→탐지 API
│   │   ├── index.html                      # 테스트 웹 UI
│   │   └── requirements.txt                # torch, torchvision
│   │
│   ├── layer2b_yolov8/                 # Layer 2b (YOLOv8) Lambda
│   │   ├── Dockerfile                      # Python 3.12 + ultralytics
│   │   ├── lambda_function.py              # GET→테스트UI, POST→탐지 API
│   │   ├── index.html                      # 테스트 웹 UI
│   │   └── requirements.txt                # ultralytics, pillow
│   │
│   ├── layer3_clinical_logic/          # Layer 3 Lambda
│   │   ├── Dockerfile                      # Python 3.12 + numpy (~200MB)
│   │   ├── lambda_function.py              # GET→테스트UI, POST→판독 API
│   │   ├── index.html                      # 테스트 웹 UI
│   │   └── requirements.txt                # numpy
│   │
│   ├── layer5_rag/                     # Layer 5 Lambda
│   │   ├── Dockerfile                      # Python 3.12 + boto3
│   │   ├── lambda_function.py              # GET→테스트UI, POST→RAG API
│   │   ├── index.html                      # 테스트 웹 UI
│   │   └── requirements.txt                # boto3
│   │
│   ├── layer6_bedrock_report/          # Layer 6 Lambda
│   │   ├── Dockerfile                      # Python 3.12 + boto3 (~150MB)
│   │   ├── lambda_function.py              # GET→테스트UI, POST→소견서 API
│   │   ├── index.html                      # 테스트 웹 UI (4개 시나리오)
│   │   ├── requirements.txt                # boto3
│   │   └── layer6_bedrock_report/          # 패키지 복사본 (빌드 시 생성)
│   │
│   ├── chest_modal_orchestrator/       # ★ 통합 오케스트레이터 Lambda ✅ 배포됨
│   │   ├── Dockerfile                      # Python 3.12 + requests (~150MB)
│   │   ├── lambda_function.py              # GET→테스트UI, POST→4가지 액션
│   │   │                                   #   run: 6-Layer 순차/병렬 호출
│   │   │                                   #   list_test_cases: 테스트 케이스 목록
│   │   │                                   #   test_case: 특정 케이스 실행
│   │   │                                   #   presigned_url: S3 이미지 프리사인 URL
│   │   ├── orchestrator.py                 # 6-Layer 파이프라인 엔진
│   │   │                                   #   Step 1+2: L1+L2+L2b 3-way 병렬
│   │   │                                   #   Step 3: L3 (L1+L2 의존)
│   │   │                                   #   Step 4: L5 RAG (L3 의존)
│   │   │                                   #   Step 5: L6 Bedrock (L3+L5 의존)
│   │   ├── config.py                       # 7개 Layer URL + 타임아웃 + S3 설정
│   │   ├── input_parser.py                 # 입력 파싱 (base64/S3)
│   │   ├── output_formatter.py             # 출력 포맷터
│   │   ├── layer_client.py                 # Layer 1~6 HTTP 클라이언트
│   │   ├── test_cases.py                   # S3 5개 테스트 케이스 정의
│   │   ├── index.html                      # ★ 통합 테스트 UI
│   │   │                                   #   마스크 오버레이 + SVG 측정선
│   │   │                                   #   YOLO bbox SVG 오버레이
│   │   │                                   #   3개 토글: Mask/Measure/YOLO ON/OFF
│   │   │                                   #   Anatomy Measurements 패널
│   │   │                                   #   7-섹션 구조화 소견서 렌더링
│   │   │                                   #   5개 테스트: CHF/Pneumonia/PTX/Normal/Multi
│   │   └── requirements.txt                # requests
│   │
│   └── test_page/
│       └── index.html                  # 통합 테스트 페이지 (구버전)
│
│
├── 📁 docs/ ── 문서 ──────────────────────────────────────────
│   ├── API_REFERENCE.md                # 전체 API 레퍼런스 (Layer 1~6 + 통합)
│   ├── 01-plan/features/              # PDCA Plan 문서
│   │   ├── folder-restructure.plan.md      # 폴더 구조 변경 계획
│   │   ├── integrated-orchestrator.plan.md # 통합 오케스트레이터 계획
│   │   ├── layer1-deploy.plan.md           # Layer 1 배포 계획
│   │   ├── layer2_yolov8.plan.md           # Layer 2b YOLOv8 계획
│   │   └── unet-segmentation.plan.md       # UNet 학습 계획
│   ├── 02-design/features/            # PDCA Design 문서
│   │   └── integrated-orchestrator.design.md # 통합 오케스트레이터 설계 스펙
│   └── 03-analysis/                   # PDCA Gap 분석 문서
│       └── integrated-orchestrator.analysis.md # Gap 분석 v3 (Match Rate 98%)
│
│
├── 📁 notebooks/ ── 분석 노트북 ──────────────────────────────
│   ├── 01_densenet121_test_100.ipynb   # DenseNet 100장 테스트
│   ├── 02_gradcam_visualization.ipynb  # GradCAM 히트맵 시각화
│   ├── 02_gradcam_visualization.py     # GradCAM 스크립트 버전
│   └── best_model_test.pth            # 테스트용 모델 가중치 (1.9MB)
│
│
├── 📁 pipeline/ ── 데이터 파이프라인 유틸 ─────────────────────
│   ├── config.py                       # 파이프라인 설정
│   ├── schemas.py                      # 데이터 스키마 정의
│   └── chest_modal.py                  # 흉부 모달 처리
│
│
├── 📁 logs/ ── 로그 파일 ─────────────────────────────────────
│   ├── s3_copy_errors.txt              # S3 복사 에러 로그
│   ├── s3_sync_errors_2.txt            # S3 동기화 에러 로그
│   └── s3_policy.json                  # S3 버킷 정책
│
│
├── 📁 train.csv/ ── 학습 데이터 ──────────────────────────────
│   └── train.csv                       # 학습용 CSV 파일
│
│
├── 📁 utils/ ── 유틸리티 (비어 있음) ─────────────────────────
│
│
└── 📁 layer6_report/ ── (레거시, 사용 안 함)
    └── prompt_templates/               # (비어 있음)
```

---

## AWS 리소스 (내가 만든 것만)

> 리전: ap-northeast-2 (서울) / 계정: 666803869796

### Lambda Functions

| 함수명 | 패키지 | 메모리 | 타임아웃 | Function URL | 상태 |
|--------|--------|--------|----------|-------------|------|
| `layer1-segmentation` | Container Image | 3,008 MB | 120s | `https://jwhljyevn3hm44nhvs5zcdstmi0tmuvi.lambda-url.ap-northeast-2.on.aws/` | ✅ Active |
| `layer2-detection` | Container Image | 3,008 MB | 180s | `https://pk67s3qrp3b3xluqkcp6neqly40kduol.lambda-url.ap-northeast-2.on.aws/` | ✅ Active |
| `layer2b-yolov8` | Container Image | 3,008 MB | 180s | `https://yoaval7laoc4ngnkr7uod7dufm0nmxib.lambda-url.ap-northeast-2.on.aws/` | ✅ Active |
| `layer3-clinical-logic` | Container Image | 256 MB | 30s | `https://ihq6gjldxbulfke5xd2xexnoqe0vyrxt.lambda-url.ap-northeast-2.on.aws/` | ✅ Active |
| `layer5-rag` | Container Image | 1,024 MB | 30s | `https://rn32hjcarfgqhopm266iidoeey0lkbkt.lambda-url.ap-northeast-2.on.aws/` | ✅ Active |
| `layer6-bedrock-report` | Container Image | 256 MB | 120s | `https://ofii46d5p6446ceahn3ucb5f2a0xcvej.lambda-url.ap-northeast-2.on.aws/` | ✅ Active |
| `chest-modal-integrated` | Container Image | 512 MB | 300s | `https://emsptg6o6iwonhhbxyxvasm7ga0yjluu.lambda-url.ap-northeast-2.on.aws/` | ✅ Active |

- IAM Role: `arn:aws:iam::666803869796:role/say-2-lambda-bedrock-role`
- AuthType: NONE (공개 접근)
- 모든 함수 태그: `project: pre-project-6team`

### ECR Repositories (Docker 이미지)

| 리포지토리 | 이미지 크기 | 용도 |
|-----------|-----------|------|
| `layer1-segmentation` | ~590 MB | PyTorch + HF transformers + UNet |
| `layer2-detection` | ~430 MB | PyTorch + torchvision + DenseNet-121 |
| `layer2b-yolov8` | ~588 MB | ultralytics + YOLOv8 |
| `layer3-clinical-logic` | ~1.2 KB (초경량) | 순수 Python + numpy |
| `layer5-rag` | ~224 MB | boto3 + FAISS |
| `layer6-bedrock-report` | ~180 MB | boto3 (Bedrock 호출) |
| `chest-modal-integrated` | ~150 MB | requests (6-Layer 순차/병렬 호출) |

### S3 버킷: `pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an`

> 총 45,167 객체 / 49.3 GiB

```
s3://pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an/
│
├── 📋 루트 파일
├── CONTEXT.md                                    # 세션 컨텍스트
├── API_REFERENCE.md                              # API 레퍼런스
├── PROJECT_STRUCTURE.md                          # 프로젝트 구조 문서
│
├── 📁 models/ ── 학습 완료 모델 가중치 ─────────────────────
│   ├── segmentation/
│   │   └── chest-x-ray-basic/                    # Layer 1 HF 사전학습 모델
│   │       ├── model.safetensors                     # 85.0 MiB (EfficientNetV2-S + UNet)
│   │       ├── config.json                           # 모델 설정
│   │       ├── configuration.py                      # HF 설정 클래스
│   │       ├── modeling.py                           # 모델 정의
│   │       └── unet.py                               # UNet 아키텍처
│   ├── detection/
│   │   └── densenet121.pth                       # Layer 2 DenseNet (27.2 MiB, 30 epoch)
│   ├── yolov8s.pt                                # YOLOv8 기본 모델 (21.5 MiB)
│   └── yolov8_vindr_best.pt                      # Layer 2b YOLOv8 best (21.6 MiB)
│
├── 📁 checkpoints/ ── 학습 중간 체크포인트 ──────────────────
│   ├── densenet121/
│   │   └── checkpoint.pth                        # v1 p10 체크포인트 (80.6 MiB)
│   ├── densenet121-full-pa-v3/
│   │   └── checkpoint.pth                        # v3 Full PA 체크포인트 (27.3 MiB)
│   └── densenet121-full-pa-v6-multigpu/
│       └── checkpoint.pth                        # v6 멀티GPU 체크포인트 (80.6 MiB)
│
├── 📁 output/ ── SageMaker 학습 결과 ───────────────────────
│   ├── densenet121-mimic-cxr-v1/                 # v1 (p10, Mean AUROC 0.7475)
│   │   ├── output/model.tar.gz                       # 최종 모델 (25.3 MiB)
│   │   └── gradcam/                                  # GradCAM 시각화 (8장)
│   │       ├── gradcam_01.png ~ gradcam_10.png       # 히트맵 이미지
│   │       └── gradcam_results.json                  # GradCAM 결과
│   ├── densenet121-full-pa-v2/
│   │   └── output/model.tar.gz                   # (0 bytes — 디스크 부족 실패)
│   ├── densenet121-full-pa-v3/
│   │   └── output/model.tar.gz                   # v3 Full PA 모델 (25.3 MiB)
│   ├── densenet121-full-pa-v6-multigpu/
│   │   └── output/model.tar.gz                   # v6 멀티GPU 모델 (25.3 MiB)
│   ├── densenet121-eval/
│   │   └── eval_results.json                     # 평가 결과 (AUC 등)
│   ├── yolov8_vindr/                             # YOLOv8 VinDr-CXR 학습 결과
│   │   ├── weights/
│   │   │   ├── best.pt                               # 최적 모델 (21.6 MiB)
│   │   │   ├── last.pt                               # 마지막 모델 (21.6 MiB)
│   │   │   └── epoch{0,10,20,...,70}.pt              # 에포크별 체크포인트 (각 64.2 MiB)
│   │   ├── results.csv                               # 학습 지표
│   │   ├── results.png                               # 학습 그래프
│   │   ├── confusion_matrix.png                      # 혼동 행렬
│   │   ├── confusion_matrix_normalized.png           # 정규화 혼동 행렬
│   │   ├── F1_curve.png                              # F1 곡선
│   │   ├── PR_curve.png                              # PR 곡선
│   │   ├── P_curve.png / R_curve.png                 # 정밀도/재현율 곡선
│   │   ├── labels.jpg / labels_correlogram.jpg       # 라벨 분포
│   │   ├── train_batch{0,1,2}.jpg                    # 학습 배치 시각화
│   │   └── val_batch{0,1,2}_{labels,pred}.jpg        # 검증 배치 시각화
│   ├── yolov8s-vindr-0322-0938/
│   │   └── output/output.tar.gz                  # 초기 학습 시도 (1.6 MiB)
│   └── yolov8s-vindr-cxr-20260322-0918/
│       └── output/output.tar.gz                  # 초기 학습 시도 (1.1 KiB)
│
├── 📁 code/ ── SageMaker 학습 소스코드 ─────────────────────
│   ├── train_unet.py                             # UNet 학습 스크립트 (25.5 KiB)
│   ├── densenet/train.py                         # DenseNet 학습 스크립트 (20.6 KiB)
│   ├── yolov8/train.py                           # YOLOv8 학습 스크립트 (7.8 KiB)
│   ├── 02_gradcam_visualization.ipynb            # GradCAM 노트북 (10.7 KiB)
│   ├── submit_training_jobs.ipynb                # 학습잡 제출 노트북 (8.8 KiB)
│   ├── sourcedir.tar.gz                          # DenseNet v1 소스 아카이브
│   ├── densenet_full_sourcedir.tar.gz            # DenseNet Full PA 소스
│   ├── densenet_multigpu_sourcedir.tar.gz        # DenseNet 멀티GPU 소스
│   ├── unet_sourcedir.tar.gz                     # UNet 소스 아카이브
│   └── yolov8_sourcedir.tar.gz                   # YOLOv8 소스 아카이브 (19.9 MiB)
│
├── 📁 data/ ── 학습 이미지 데이터 (45.1 GiB) ──────────────
│   └── p10_pa/files/p10/                         # MIMIC-CXR PA Only 이미지
│       ├── p10000032/                                # 환자 ID별 디렉토리
│       │   └── s50414267/                            #   └ 스터디별 서브디렉토리
│       │       └── 02aa804e-...jpg                   #       └ DICOM→JPG 변환 이미지
│       ├── p10000898/
│       ├── p10000935/
│       ├── ... (총 ~5,221 환자 디렉토리)
│       └── p10XXXXXX/
│       (약 29,000+ 이미지 파일, 45.1 GiB)
│
├── 📁 mimic-cxr-csv/ ── 공식 CSV 사본 ─────────────────────
│   ├── mimic-cxr-2.0.0-chexpert.csv              # CheXpert 라벨
│   ├── mimic-cxr-2.0.0-metadata.csv              # 메타데이터
│   └── mimic-cxr-2.0.0-split.csv                 # 분할 정보
│
├── 📁 preprocessing/ ── 전처리 결과 ────────────────────────
│   ├── build_official_master.py                  # Master CSV 빌드 스크립트
│   ├── p10_train_ready.csv                       # 최종 학습용 CSV
│   ├── p10_train_ready_resplit.csv               # 재분할 버전
│   └── pos_weights.json                          # 14질환 클래스 가중치
│
├── 📁 web/ ── 테스트 웹페이지 + 샘플 이미지 ────────────────
│   ├── test-layer1/
│   │   ├── index.html                            # Layer 1 테스트 페이지
│   │   └── samples/                              # 샘플 CXR 이미지 3장
│   │       ├── sample_1.jpg (1.8 MiB)
│   │       ├── sample_4.jpg (1.1 MiB)
│   │       ├── sample_5.jpg (1.4 MiB)
│   │       └── samples.json
│   ├── test-layer2/
│   │   └── samples/                              # 샘플 CXR 이미지 5장
│   │       ├── 096052b7.jpg ~ e084de3b.jpg
│   └── test-layer2b/
│       └── samples/                              # 샘플 CXR 이미지 5장
│           ├── 096052b7.jpg ~ e084de3b.jpg
│
├── 📁 docs/
│   └── API_REFERENCE.md                          # API 레퍼런스 사본
│
└── 📁 config/
    └── kaggle.json                               # Kaggle API 인증 (75 B)
```

### S3 버킷 용량 요약

| 카테고리 | 크기 | 객체 수 | 설명 |
|----------|------|---------|------|
| `data/` | 45.1 GiB | ~29,900 | MIMIC-CXR PA 이미지 |
| `output/` | ~0.8 GiB | ~40 | SageMaker 학습 결과물 |
| `models/` | ~155 MiB | 8 | 최종 모델 가중치 |
| `checkpoints/` | ~189 MiB | 3 | 학습 체크포인트 |
| `code/` | ~20 MiB | 10 | SageMaker 소스코드 |
| `web/` | ~18 MiB | 15 | 테스트 페이지 + 샘플 |
| 기타 (csv, docs) | ~90 MiB | — | 전처리 CSV, 문서 |
| **합계** | **49.3 GiB** | **45,167** | |

---

## 파이프라인 흐름

```
흉부 X-Ray 이미지 (base64 또는 S3 key)
     │
     ▼
[Orchestrator] 통합 오케스트레이터 ✅
     Lambda: chest-modal-integrated (512MB, 300s)
     6-Layer 순차/병렬 호출, E2E ~40초
     │
     │  ┌─── Step 1+2: 3-way 병렬 (ThreadPoolExecutor, max_workers=3) ───┐
     │  │                                                                  │
     ├──→ [Layer 1] 세그멘테이션 → 마스크 + CTR + 해부학 계측 ✅          │
     │     Lambda: layer1-segmentation (3GB, 120s)                         │
     │     모델: ianpan/chest-x-ray-basic (85MB, HF pretrained)            │
     │     후처리: 중심선 L/R 보정 (교차 픽셀 16%→0%)                      │
     │                                                                     │
     ├──→ [Layer 2] DenseNet-121 → 14질환 확률 ✅                         │
     │     Lambda: layer2-detection (3GB, 180s)                            │
     │     모델: densenet121.pth (27MB, MIMIC-CXR 94K fine-tuned)          │
     │                                                                     │
     ├──→ [Layer 2b] YOLOv8 → bbox 위치 탐지 (optional) ✅               │
     │     Lambda: layer2b-yolov8 (3GB, 180s)                              │
     │     모델: yolov8_vindr_best.pt (22MB, VinDr-CXR fine-tuned)         │
     │  └──────────────────────────────────────────────────────────────────┘
     │
     └──→ [Layer 3] Clinical Logic → 14개 Rule + 교차검증 + 감별진단 ✅
           Lambda: layer3-clinical-logic (256MB, 30s)
           순수 Python (모델 없음), Layer 1+2 결과 의존
              │
              ├──→ [Layer 5] RAG → 유사 케이스 검색 (FAISS + bge-small) ✅
              │     Lambda: layer5-rag (1GB, 30s)
              │
              └──→ [Layer 6] Bedrock → 최종 소견서 (7-섹션 구조화 + 서술형) ✅
                    Lambda: layer6-bedrock-report (256MB, 120s)
                    Bedrock: Claude Sonnet 4.6
                    입력: L1 anatomy + L2 densenet + L2b yolo + L3 logic + L5 rag

프론트엔드 (index.html):
  ├── CXR 이미지 뷰어 + 3중 오버레이 (마스크 + SVG 측정선 + YOLO bbox)
  ├── 토글 3개: Mask ON/OFF, Measure ON/OFF, YOLO ON/OFF
  ├── Anatomy Measurements 패널 (CTR, CP angle, 폐면적 등)
  ├── 7-섹션 소견서 렌더링 (HEART/PLEURA/LUNGS/MEDIASTINUM/BONES/DEVICES/IMPRESSION)
  └── 5개 테스트 케이스: CHF, Pneumonia, Tension PTX, Normal, Multi-finding
```

---

## 파일 통계

| 분류 | 파일 수 |
|------|---------|
| Python 소스 (.py) | ~98 |
| Jupyter 노트북 (.ipynb) | 9 |
| 마크다운 문서 (.md) | ~28 |
| HTML (테스트 UI) | 8 |
| Dockerfile | 10 |
| JSON 설정/결과 | ~24 |
| 데이터 (CSV/TXT) | 9 |
| **총 로컬 파일 수** | **~245** |

### AWS 리소스 통계

| 리소스 | 수량 |
|--------|------|
| Lambda Functions | 7 |
| ECR Repositories | 7 |
| S3 버킷 객체 | 45,167 (49.3 GiB) |
| 학습 완료 모델 | 3 (UNet + DenseNet + YOLOv8) |
| Function URL (공개) | 7 |

---

## 학습/복습 가이드

> 나중에 프로젝트 내용을 공부할 때 아래 순서로 읽으면 됨

### 1단계: 프로젝트 전체 그림 이해

| 순서 | 파일 | 핵심 내용 |
|------|------|-----------|
| 1 | `PROJECT_CONTEXT_FULL.md` | 프로젝트 목표, 팀 구성 (5명 5개 모달), v1→v2 재설계 이유, 오케스트레이터 개념 |
| 2 | `CHEST_MODAL_V2_REDESIGN.md` | 흉부 모달 6-Layer 전체 흐름, 실제 응급실 시나리오로 설명 (67세 남성 흉통 사례) |
| 3 | `record_daily.md` | 3/20~3/22 매일 뭘 했는지 시간순 기록 (전처리→학습→배포 전 과정) |

### 2단계: 의학 지식 (방사선과 판독)

| 순서 | 파일 | 핵심 내용 |
|------|------|-----------|
| 4 | `CXR_14_PATHOLOGY_READING_CRITERIA.md` | 14개 질환별 실제 전문의 판독법. 어디를, 무엇을, 어떤 징후로 판독하는지. 각 질환마다 핵심 Sign 정리 (Golden S sign, Sail sign, Deep sulcus sign 등) |

### 3단계: 모델/학습 이해

| 순서 | 파일 | 핵심 내용 |
|------|------|-----------|
| 5 | `MODEL_BENCHMARK.md` | DenseNet-121 성능. 질환별 AUROC, 2-Stage Fine-tuning, pos_weight 전략, 성능 등급 분석 |
| 6 | `layer2_detection/densenet/DENSENET_WORK_SUMMARY.md` | DenseNet 전체 작업 과정 요약 (v1~v6, 실패 원인, 최종 결과) |
| 7 | `layer2_detection/yolov8/YOLOV8_WORK_SUMMARY.md` | YOLOv8 병변 탐지 작업 요약 (VinDr-CXR 데이터, 학습 결과) |

### 4단계: 각 레이어 구현 스펙

| 순서 | 파일 | 핵심 내용 |
|------|------|-----------|
| 8 | `PROMPT_Layer3_Clinical_Logic_Engine.md` | Layer 3 설계 스펙 — 14개 Rule 로직 상세 (CTR 계산, CP angle 판정, 교차검증 등) |
| 9 | `PROMPT_Layer5_RAG_FAISS_Titan_With_Details.md` | Layer 5 설계 스펙 — FAISS 인덱스, Titan 임베딩, 유사 케이스 검색 구조 |
| 10 | `PROMPT_Layer6_Bedrock_Report_Lambda.md` | Layer 6 설계 스펙 — Bedrock 프롬프트 설계, 소견서 JSON 구조 |
| 11 | `docs/API_REFERENCE.md` | 전체 API 레퍼런스 — Layer 1~6 요청/응답 구조, 인프라 스펙 |

### 핵심 개념 요약 (시험/발표용)

| 개념 | 어디서 배우는지 |
|------|-----------------|
| CheXpert 14개 질환이 뭔지 | `CXR_14_PATHOLOGY_READING_CRITERIA.md` |
| CTR(심흉비)이 뭐고 왜 0.50이 기준인지 | `CXR_14_PATHOLOGY_READING_CRITERIA.md` > Cardiomegaly |
| DenseNet-121이 뭐고 왜 선택했는지 | `MODEL_BENCHMARK.md` + `DENSENET_WORK_SUMMARY.md` |
| pos_weight가 뭐고 왜 필요한지 | `MODEL_BENCHMARK.md` + `record_daily.md` (3/20) |
| AUROC가 뭔지, 0.7이면 좋은 건지 | `MODEL_BENCHMARK.md` > 질환별 AUROC 표 |
| Rule-Based vs ML 하이브리드 접근 | `CHEST_MODAL_V2_REDESIGN.md` > Layer 3 설계 |
| 오케스트레이터가 뭔지 | `PROJECT_CONTEXT_FULL.md` > 시스템 아키텍처 v2 |
| Lambda 컨테이너 배포가 뭔지 | `deploy/DEPLOY_GUIDE.md` |
| 오케스트레이터 구현 (6-Layer 순차/병렬) | `PROMPT_Integrated_Modal_Orchestrator.md` + `deploy/chest_modal_orchestrator/orchestrator.py` |
| 통합 오케스트레이터 설계 vs 구현 Gap | `docs/03-analysis/integrated-orchestrator.analysis.md` (98% Match Rate) |
| 세그멘테이션 마스크 L/R 보정 원리 | `deploy/layer1_segmentation/lambda_function.py` (중심선 보정) |
| RAG가 뭐고 왜 필요한지 | `PROMPT_Layer5_RAG_FAISS_Titan_With_Details.md` |
| Bedrock이 뭐고 어떻게 쓰는지 | `PROMPT_Layer6_Bedrock_Report_Lambda.md` |
| CORS 이중 헤더 문제와 해결법 | `record_daily.md` (3/23 섹션 9) |
