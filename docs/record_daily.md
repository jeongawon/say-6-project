# 박현우 - 일일 개발 기록

---

## 2026-03-20

### 1. MIMIC-CXR 전처리 파이프라인 구축
- **목적:** 원본 CSV 3종이 분리되어 있어 학습에 바로 사용 불가 → 단일 Master CSV로 통합 필요
- **내용:** metadata(377,110 이미지) + split(train/val/test) + chexpert(14개 질환 라벨)를 dicom_id/study_id 기준으로 병합
- **결과:** Master CSV 생성 완료 (377,095행)

### 2. PA View 필터링
- **목적:** 흉부 X-Ray 판독은 PA(정면) 뷰가 표준 → 다른 뷰(Lateral 등) 제거하여 데이터 품질 확보
- **내용:** ViewPosition == 'PA' 조건으로 필터링
- **결과:** 377,095 → 96,155장으로 축소

### 3. 불량 데이터 제거 + U-Ones 라벨 변환
- **목적:** CheXpert 라벨에 -1(불확실) 값 존재 → 학습에 부적합하므로 처리 필요
- **내용:** 불량 데이터 제거 후, Uncertain(-1) 라벨을 1(양성)로 변환 (U-Ones 정책)
- **결과:** 96,155 → 94,380장

### 4. pos_weight 계산 및 학습용 CSV 생성
- **목적:** 14개 질환별 클래스 불균형 해소를 위한 가중치 필요 + p10 그룹으로 소규모 실험셋 구성
- **내용:** 질환별 양성/음성 비율 기반 pos_weight 산출, p10 환자군 필터링 후 train/val/test 분리
- **결과:** pos_weights.json 저장, 최종 CSV 9,118장 (train 8,993 / val 65 / test 60)

---

## 2026-03-21

### 1. p10 테스트 → 전체 PA 프로덕션 학습 전환
- **목적:** p10 서브셋(9,118장) 테스트 단계가 복잡도만 증가시킴 → 바로 전체 PA(94,380장) 프로덕션 학습으로 전환
- **내용:** 기존 multi-step 노트북 방식 폐기, SageMaker Training Job 내부에서 데이터 준비+학습을 모두 처리하는 all-in-one 스크립트로 재설계
- **결과:** 학습 파이프라인 단순화 (5단계 → 1단계 제출)

### 2. U-Net 세그멘테이션 학습 스크립트 (train_unet.py)
- **목적:** CheXmask 데이터 기반 폐/심장 세그멘테이션 모델 학습 — CTR(심흉비) 계산의 전제조건
- **내용:** CheXmask CSV(4.4GB) S3 캐싱 + aria2c 16병렬 다운로드, RLE on-the-fly 디코딩(~1ms/이미지, NPZ 중간파일 제거), S3 선택적 이미지 다운로드(ThreadPoolExecutor 32병렬), U-Net+EfficientNet-B4 4클래스 세그멘테이션
- **결과:** all-in-one 스크립트 완성, Training Job 제출 (unet-lung-heart-v2, ml.g5.xlarge spot)

### 3. DenseNet-121 전체 PA 학습 스크립트 (train.py)
- **목적:** 14개 질환 multi-label 분류 — 흉부 모달의 핵심 Stage 1
- **내용:** 메타데이터/split/chexpert CSV를 S3에서 직접 로드하여 전체 PA CSV 빌드, 2-Stage Fine-tuning (Stage1: classifier 5에폭, Stage2: full 25에폭), BCEWithLogitsLoss + pos_weight
- **결과:** all-in-one 스크립트 완성, Training Job 제출 (densenet121-full-pa-v1, ml.g4dn.xlarge spot)

### 4. 원클릭 제출 노트북 (submit_training_jobs.ipynb)
- **목적:** 셀 2개 실행만으로 양쪽 Training Job 동시 제출 — "딸깍 한번 누르고 자기"
- **내용:** train_unet.py/train.py 각각 tar.gz 패키징 → S3 업로드 → boto3 create_training_job() 호출
- **결과:** 노트북 완성, 예상 비용 ~$4-7 (스팟)

### 5. SageMaker 인스턴스 쿼터 이슈 해결
- **목적:** ml.g5.xlarge 스팟 쿼터 1개 제한으로 DenseNet 제출 실패
- **내용:** ResourceLimitExceeded 에러 확인 → DenseNet을 ml.g4dn.xlarge로 변경
- **결과:** 양쪽 Training Job 모두 정상 제출 완료

---

## 2026-03-22

### 1. Training Job 실패 분석 + Layer 1 HF 전환 (세션 1)
- **목적:** 제출한 Training Job들의 실패 원인 파악 + 대안 마련
- **내용:** unet-lung-heart-v3 (CheXmask wget 타임아웃), densenet121-full-pa-v2 (80GB 디스크 부족) 원인 분석. Layer 1을 U-Net 직접학습 → HF 사전학습 모델(ianpan/chest-x-ray-basic)로 전환
- **결과:** layer1_segmentation/segmentation_model.py 구현 (EfficientNetV2-S + U-Net, Dice 0.95+)

### 2. Layer 1/2 Lambda 배포 (세션 2~3)
- **목적:** Layer 1(Segmentation), Layer 2(DenseNet) 각각 독립 Lambda 엔드포인트 배포
- **내용:** ECR 리포지토리 생성 → Docker 컨테이너 이미지 빌드 → Lambda Function URL 활성화
- **결과:**
  - Layer 1: `https://jwhljyevn3hm44nhvs5zcdstmi0tmuvi.lambda-url.ap-northeast-2.on.aws/`
  - Layer 2: `https://pk67s3qrp3b3xluqkcp6neqly40kduol.lambda-url.ap-northeast-2.on.aws/`

### 3. Layer 3 Clinical Logic Engine 전체 구현 (세션 4)
- **목적:** 14개 질환 Rule-Based 판독 로직 구현 — DenseNet 확률 + YOLO 바운딩 박스 + 해부학 수치를 종합하여 전문의 수준의 임상 근거를 생성
- **내용:**
  - 14개 질환별 개별 Rule 모듈 (`layer3_clinical_logic/rules/`, 14파일)
    - Cardiomegaly: CTR > 0.50 기반, AP 뷰 신뢰도 하향
    - Pleural Effusion: CP angle 둔화 + 볼륨 추정(small/moderate/large)
    - Pneumothorax: DenseNet + 폐 면적비 + tension 감지(기관 편위)
    - Consolidation: YOLO bbox + 폐엽 매핑 + Silhouette sign
    - Edema: 양측 대칭 분석 + butterfly 패턴 + CHF/ARDS 감별
    - Pneumonia: 5-step 임상 상관(경화→활력→검사→감별→ECG)
    - Atelectasis: 폐 면적비 < 0.80 + 종격동 이동 방향
    - Enlarged CM: 종격동 폭 비율 + 기관 편위
    - Fracture: YOLO bbox 늑골 번호 추정 + 동반 손상 교차
    - Lung Lesion: 장축 크기 분류 + Fleischner Society 권고
    - Lung Opacity: 감별 엔진(다른 Rule 결과로 원인 추정)
    - No Finding: 8-area 체크리스트 + 13질환 전부 CLEAR 확인
    - Pleural Other: 낮은 임계값(0.25) + 석면 노출 교차
    - Support Devices: ETT tip-to-carina + NG tube 위치
  - 3-소스 교차검증 (`cross_validation.py`): DenseNet vs YOLO vs Logic → 합의도(high/medium/low)
  - 감별진단 (`differential.py`): 6개 패턴 (CHF, 폐렴, 외상성/긴장성 기흉, 심인성 부종, 무기폐)
  - 위험도 3단계 분류: CRITICAL(alert=True) / URGENT(severe 2개+) / ROUTINE(그 외)
  - 27개 pytest 테스트 전부 통과 (CHF, Pneumonia, Tension Pneumothorax, Normal)
- **결과:** 처리시간 ~0.0003초/건, 순수 Python(GPU 불필요)

### 4. Layer 3 Lambda 배포 (세션 4)
- **목적:** Layer 3 Clinical Logic을 독립 Lambda 엔드포인트로 배포
- **내용:** Docker 이미지 ~200MB(Layer 1/2의 1/7), 메모리 256MB, 4개 API action(list_scenarios, scenario, random, custom)
- **결과:**
  - Function URL: `https://ihq6gjldxbulfke5xd2xexnoqe0vyrxt.lambda-url.ap-northeast-2.on.aws/`
  - 4개 시나리오 전부 정상: CHF→URGENT, Tension→CRITICAL, Pneumonia→ROUTINE, Normal→ROUTINE
  - 비용: 호출당 ~$0.0001 (0.1원)

### 5. API 참조문서 작성
- **목적:** Layer 1~3 엔드포인트 통합 API 문서 — 이후 레이어 추가 시 계속 확장
- **내용:** `docs/API_REFERENCE.md` 작성 (엔드포인트, 요청/응답 스키마, 인프라 비교표, Python/JS 예제)
- **결과:** 로컬 저장 + S3 업로드 완료

### 6. Layer 6 Bedrock Report 전체 구현 (세션 5)
- **목적:** 6-Layer 파이프라인의 최종 단계 — Layer 1~5 결과를 종합하여 전문의 수준의 흉부 X-Ray 소견서 자동 생성
- **내용:**
  - Bedrock Claude Sonnet 4.6 (`global.anthropic.claude-sonnet-4-6`) 호출로 소견서 생성
  - `layer6_bedrock_report/` 패키지 (7개 모듈):
    - `config.py`: Bedrock 모델/파라미터 (temp=0.2, max_tokens=4096, 재시도 temp=0.0)
    - `models.py`: 입출력 dataclass (ReportInput → Layer 1~5 전체 결과 수용, ReportOutput → 구조화+서술형+요약+권고)
    - `report_generator.py`: Bedrock 호출 + 프롬프트 조립 + JSON 파싱 (```json 블록/중괄호 매칭/개행 수정 등 3단계 파싱 + 실패 시 temp 0.0 재시도)
    - `prompt_templates.py`: 한/영 이중언어 지원 (시스템 프롬프트: 응급의학 전문의 역할+판독 원칙 6개+8섹션 구조, 유저 프롬프트: 환자정보/이전검사/해부학/탐지/임상로직/교차검증/감별진단 7섹션)
    - `rag_placeholder.py`: RAG 인터페이스 사전 정의 (Layer 5 연결 시 교체만 하면 됨)
    - `mock_data.py`: 4개 임상 시나리오 (CHF-URGENT, Pneumonia-URGENT, Tension PTX-CRITICAL, Normal-ROUTINE)
  - 소견서 출력 구조: 8섹션 구조화(heart/pleura/lungs/mediastinum/bones/devices/impression/recommendation) + 서술형 판독문 + 1~2문장 요약 + suggested_next_actions
  - AI 내부 수치(DenseNet 확률 등) 소견서 배제, 임상 수치(CTR/CP angle 등)만 포함 원칙
  - 22개 pytest 테스트 전부 통과 (프롬프트 조립 6 + 포맷팅 8 + 응답 파싱 4 + 목데이터 4)
- **결과:** Bedrock 호출 없이 프롬프트/파싱 로직 단위 테스트 완료, Lambda 배포 후 실제 Bedrock 연동

### 7. Layer 6 Lambda 배포 (세션 5)
- **목적:** Layer 6 Bedrock Report를 독립 Lambda 엔드포인트로 배포
- **내용:**
  - `deploy/deploy_layer6.py` 배포 자동화 (5단계: 소스복사→ECR→Docker→Lambda→URL)
  - Docker 이미지 ~150MB (순수 Python + boto3, PyTorch/GPU 불필요 — Layer 1/2의 1/10)
  - Lambda 설정: 256MB 메모리, 120s 타임아웃, 512MB /tmp
  - 테스트 UI: Dark theme, 4개 시나리오 카드, 한/영 언어 선택, 위험도 배지(CRITICAL/URGENT/ROUTINE)
  - 3개 API action: list_scenarios(시나리오 목록), scenario(시나리오 실행), generate(직접 입력 소견서 생성)
- **결과:**
  - ECR: `layer6-bedrock-report`
  - Function URL: `https://ofii46d5p6446ceahn3ucb5f2a0xcvej.lambda-url.ap-northeast-2.on.aws/`
  - Cold Start ~2초 (GPU 없어서 매우 빠름)
  - 비용: Bedrock 호출당 ~$0.05 (입력+출력 토큰)

---

## 2026-03-23

### 1. Layer 5 RAG — 판독문 추출 (Step 1)
- **목적:** MIMIC-IV Note radiology.csv(2.87GB, 2.3M행)에서 CHEST 키워드가 포함된 판독문만 추출
- **내용:** pandas로 S3에서 다운로드 후 로컬 필터링 (S3 Select보다 5배 빠름). IMPRESSION 섹션 파싱하여 reports.jsonl 생성
- **결과:** 880,643건 추출 (1.2GB), S3 업로드 완료

### 2. Layer 5 RAG — GPU 임베딩 (Step 2)
- **목적:** 880K IMPRESSION 텍스트를 벡터화하여 FAISS 검색 가능하게 변환
- **내용:** SageMaker 노트북 인스턴스(ml.g5.xlarge, A10G GPU)에서 bge-small-en-v1.5 모델로 배치 임베딩. 여러 접근 시도 (FastEmbed OOM → SentenceTransformers CPU 느림 → SageMaker Processing Job IAM 제한 → 노트북 Lifecycle 자동화 실패) 끝에 Jupyter 노트북 수동 실행으로 해결
- **결과:** 880,643 × 384d embeddings.npy (1.3GB), S3 업로드 완료. A10G 기준 ~2분

### 3. Layer 5 RAG — 양성 소견 필터링 (Step 3a)
- **목적:** 880K 전체 인덱스(1.3GB)는 Lambda에 안 들어감 → 양성 소견만 필터링하여 50~150K로 축소
- **내용:** 3단계 하이브리드 필터 시도 → ICU 데이터 특성상 대부분 비정상(56~67%) → "급성/신규 소견 + CheXpert 질환 2개 이상" 전략으로 124K 달성. FAISS 검색 품질 검증: 단일 소견(pneumonia만)도 유사도 0.94로 정확 매칭 확인
- **결과:** 123,974건 (14.1%), embeddings_filtered.npy 182MB + metadata_filtered.jsonl 176MB

### 4. Layer 5 RAG — FAISS 인덱스 빌드 + S3 업로드 (Step 3b~4)
- **목적:** 필터링된 124K 벡터로 검색 인덱스 구축 후 Lambda에서 사용할 수 있도록 S3 배포
- **내용:** IndexIVFFlat (nlist=352, Inner Product) 빌드, S3 `rag/` 경로에 3파일 업로드 (faiss_index.bin + metadata.jsonl + config.json)
- **결과:** 인덱스 183MB, 총 합계 359MB → Lambda 1GB /tmp으로 충분

### 5. Layer 5 RAG — Lambda 라이브 배포
- **목적:** Mock 모드에서 실제 FAISS 검색으로 전환하여 124K 실제 MIMIC 판독문에서 라이브 검색
- **내용:** Dockerfile에 fastembed 추가 + 모델 사전 다운로드 → ECR 푸시 → Lambda 설정 (USE_MOCK=false, 메모리 1GB, /tmp 1GB, 타임아웃 120초) → 4개 시나리오 라이브 검증
- **결과:**
  - Function URL: `https://rn32hjcarfgqhopm266iidoeey0lkbkt.lambda-url.ap-northeast-2.on.aws/`
  - Cold Start: ~10초, Warm: ~60ms
  - CHF sim=0.93, Pneumonia sim=0.92, Tension PTX sim=0.88, Normal sim=0.89

### 6. 전체 Layer 테스트 페이지 UI 통일 리디자인 (세션 2)
- **목적:** 6개 Layer의 index.html이 각각 다른 스타일로 되어 있어 일관성 부족 → PACS/EMR 스타일 통일 디자인 시스템 적용
- **내용:**
  - 6개 Layer 전체 index.html을 통일된 디자인 시스템으로 전면 리디자인
  - CSS 변수 시스템 도입 (`--bg-primary`, `--text-primary`, `--accent` 등)
  - PACS/EMR 스타일 다크 테마 적용, AI 느낌(gradient, glow, emoji) 완전 제거
  - `border-radius ≤ 6px`, accent 색상 `#4A9EFF` 하나로 통일
  - JS 기능 100% 보존 (API 호출, 결과 렌더링 등), CSS/HTML 구조만 수정
  - Docker 재빌드 → ECR 푸시 → Lambda 업데이트 (6개 전부 배포)
- **결과:** 모든 Layer가 동일한 시각적 언어로 통일, Function URL에서 즉시 확인 가능
- **기대효과:**
  - 프로젝트 완성도 및 전문성 향상 (포트폴리오 가치 증가)
  - 추후 통합 테스트 페이지 제작 시 디자인 일관성 보장
  - 레이어 간 이동 시 사용자 인지 부하 감소

### 8. 통합 오케스트레이터 구현 + Lambda 배포 (세션 3)
- **목적:** 6개 독립 Layer Lambda를 하나의 파이프라인으로 통합하여 CXR 이미지 1장 → 최종 소견서까지 원클릭 실행
- **내용:**
  - `deploy/chest_modal_orchestrator/` 패키지 구현:
    - `orchestrator.py`: 6-Layer 순차 호출 (L1+L2 병렬 → L3 → L5 → L6)
    - `layer_client.py`: HTTP 호출 클라이언트 (레이어별 타임아웃 설정)
    - `input_parser.py`: base64/S3 입력 파싱
    - `output_formatter.py`: 결과 포맷팅 (summary/full)
    - `test_cases.py`: 5개 임상 시나리오 (CHF, 폐렴, 긴장성 기흉, 정상, 다중소견)
    - `config.py`: 엔드포인트 URL + 타임아웃 + S3 설정
    - `lambda_function.py`: Lambda 핸들러 (run/list_test_cases/test_case/presigned_url 4개 action)
  - 통합 테스트 페이지 `index.html`:
    - 5개 테스트 케이스 버튼 + 직접 업로드 지원
    - Layer 1~6 단계별 진행 표시 (실시간 상태 + 처리시간)
    - **마스크 오버레이**: 원본 CXR 위에 세그멘테이션 마스크 겹침 표시 (Layer 1 테스트 페이지와 동일 방식)
    - **Mask ON/OFF, Measure ON/OFF 토글 버튼**: 마스크/SVG 측정선 표시 제어
    - **SVG 측정선 오버레이**: 종격동(노란점선), 기관(중심선), CP Angle(초록/빨강 원), 횡격막(보라 삼각형)
    - 부위별 측정값 패널: CTR(색상코딩) + 심장폭/흉곽폭/폐면적/CP Angle 등
    - S3 테스트 케이스 시 Presigned URL로 원본 CXR 이미지 자동 로드
    - 결과: 임상 요약 + 위험도 배지 + 소견서 전문 + Layer별 상세 + Raw JSON
  - `deploy/deploy_integrated.py`: 배포 자동화 (ECR→Docker→Lambda→URL)
  - Lambda 설정: 512MB 메모리, 300s 타임아웃, 512MB /tmp
- **결과:**
  - Function URL: `https://emsptg6o6iwonhhbxyxvasm7ga0yjluu.lambda-url.ap-northeast-2.on.aws/`
  - E2E 파이프라인 성공 (63.9초): L1(23.2s) + L2(4.4s) + L3(~0ms) + L5(83ms) + L6(38.9s)
  - 5개 테스트 케이스 모두 정상 동작

### 9. CORS 이중 헤더 버그 수정 (세션 3)
- **목적:** 통합 테스트 페이지에서 Layer 3/5/6 호출 시 "Failed to fetch" 에러 해결
- **원인:** Lambda 코드에서 `Access-Control-Allow-Origin: *` 설정 + Function URL CORS에서 origin 자동 추가 → 브라우저가 이중 값 거부
- **수정:**
  - `layer3_clinical_logic/lambda_function.py`: CORS 헤더 3곳 제거
  - `layer5_rag/lambda_function.py`: `_response()` 헬퍼에서 CORS 헤더 제거
  - `layer6_bedrock_report/lambda_function.py`: `_ok()`, `_error()` 헬퍼에서 CORS 헤더 제거
  - `deploy_layer3.py`, `deploy_layer5.py`, `deploy_layer6.py`: 기존 Function URL에 CORS 업데이트 로직 추가 (`update_function_url_config`)
  - `fix_cors.py`: CORS 설정 유틸리티 스크립트 생성
- **결과:** 3개 Layer 재빌드 + 재배포 → 브라우저 cross-origin 호출 정상 동작

### 10. 전체 Layer Docker 이미지 최적화 (세션 2)
- **목적:** 6개 Lambda 컨테이너 이미지 총 10.3GB → 최소화하여 ECR 비용 절감 + Cold Start 개선
- **방법론:**
  1. `grep "^import |^from "` 으로 각 레이어 실제 사용 패키지 식별
  2. `docker history` 로 레이어별 용량 분석
  3. `docker run --entrypoint python` 으로 패키지별 설치 크기 측정
  4. 미사용 패키지 제거 + 단일 RUN 레이어로 통합 (Docker 레이어 누적 방지)
- **내용 (레이어별):**
  | Layer | 제거한 패키지 | 절감 | 비율 |
  |-------|-------------|------|------|
  | Layer 1 (Segmentation) | torchvision, albumentations, timm, scipy, opencv | -620MB | -23% |
  | Layer 2a (DenseNet) | sympy, networkx, mpmath, torchgen, pip, setuptools | -140MB | -7% |
  | Layer 2b (YOLOv8) | scipy, pandas, matplotlib, fontTools, kiwisolver, sympy | -520MB | -20% |
  | Layer 3 (Clinical Logic) | numpy (실제 미사용 확인) | -93MB | -11% |
  | Layer 5 (RAG) | sympy, mpmath, pygments, pip, setuptools | -120MB | -9% |
  | Layer 6 (Bedrock Report) | boto3 중복 설치 제거 (Lambda 내장 사용) | 0MB | 0% |
  | **합계** | | **-1.5GB** | **-15%** |
- **핵심 발견:**
  - PyTorch CPU wheel 자체가 702MB (ATen/MKL 포함) → `+cpu`는 CUDA만 제거하고 코어 연산 라이브러리는 유지
  - Docker 레이어 누적 문제: 별도 `RUN pip uninstall` 레이어는 크기 감소 효과 없음 → 반드시 단일 RUN에서 install + cleanup
  - Lambda 베이스 이미지(`public.ecr.aws/lambda/python:3.12`)만 560~748MB
- **결과:** 총 10.3GB → 8.8GB (-1.5GB), 원본 Dockerfile 백업(`deploy/_backup/`)
- **기대효과:**
  - ECR 스토리지 비용 월 ~$0.15 절감 (1.5GB × $0.10/GB)
  - Docker 빌드 시간 단축 (불필요 패키지 다운로드/설치 제거)
  - Lambda Cold Start 개선 (이미지 로드 시간 감소)
  - 향후 50% 추가 감축은 PyTorch → ONNX Runtime 전환 시 가능 (torch 702MB → onnxruntime ~60MB)
