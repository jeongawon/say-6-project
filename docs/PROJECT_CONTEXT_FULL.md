# Dr. AI Radiologist — 프로젝트 전체 컨텍스트 (Claude Code용)

> 최종 업데이트: 2026-03-23 (v3 — Layer 2b 통합 + 마스크 보정 + YOLO 오버레이)
> 작성자: 팀원 A (흉부 X-Ray 담당, 박현우)
> 팀: SKKU 2기 6팀 (#skku-2기-6팀, Slack 채널 ID: C0AKW57PFK5)
> 이 문서는 Claude Code에게 프로젝트 전체 맥락을 전달하기 위한 종합 컨텍스트입니다.

---

## 1. 프로젝트 개요

### 목표
응급실에서 환자가 내원하면, 중앙 AI 오케스트레이터(Bedrock+RAG)가 실제 응급의학과 전문의처럼 "다음에 어떤 검사를 해야 하는지"를 판단하고, 해당 검사 모달을 호출하고, 결과를 보고 다음 단계를 결정하는 과정을 반복하여 최종 종합 소견서를 자동 생성하는 시스템.
소견서 작성 시간: 30~60분 → 5~10분 단축 목표.

### 핵심 차별점 (v2 오케스트레이터 기반)
기존 v1(5개 모델 병렬 실행 → 종합)에서 v2(중앙 오케스트레이터가 순차적으로 의사결정)로 재설계됨.
실제 의사가 하는 것처럼 "흉통이요" → ECG 먼저 → 정상이면 X-Ray → 폐렴이면 혈액검사 → 확정 → 소견서 순서로 진행.
환자마다 검사 경로가 다르며, 단순 케이스는 검사 1회로 끝나고 복잡한 케이스는 여러 검사+즉시 조치를 거침.

### 오케스트레이터의 3가지 결정
1. 추가 검사 지시 — 다음에 어떤 모달을 호출할지
2. 즉시 조치 지시 — 약물 투여, 심도자실 활성화 등 (검사가 아닌 치료 행위)
3. 소견서 생성 — 충분한 정보가 모였을 때 최종 소견서 작성

---

## 2. 팀 구성 및 5개 모달

| 팀원 | 모달 | 데이터 | 담당 영역 |
|------|------|--------|-----------|
| A (나, 박현우) | 흉부 X-Ray | MIMIC-CXR (377K장) | DenseNet-121 + Grad-CAM++ + PubMedBERT RAG + Bedrock |
| B | ECG 심전도 | MIMIC-IV-ECG (80만건) | ECG 자동 판독 |
| C | EHR/혈액검사 | MIMIC-IV (9.9GB) | 검사수치 해석 + 환자요약 |
| D | 임상 텍스트 RAG | MIMIC-IV Note (6.25GB) | 유사 케이스 검색 |
| E | 유전체 위험 | ClinVar + PharmGKB | 약물 금기/유전자 변이 |

공동 작업: 오케스트레이터 설계, Bedrock 프롬프트, 중앙 DB 스키마, 테스트 시나리오

---

## 3. 시스템 아키텍처 v2

### 전체 흐름
```
환자 응급실 내원
    ↓
초기 정보 수집 (나이, 성별, 주소, 활력징후)
    ↓
중앙 오케스트레이터 (Bedrock LLM + RAG)
    ↓ ← 반복 루프
    ├── 추가 검사 지시 → 해당 모달 호출 → 결과 중앙 DB 저장
    ├── 즉시 조치 지시 → 조치 기록 중앙 DB 저장
    └── 소견서 생성 → 전체 이력 종합 → KTAS 등급 포함 소견서
    ↓
담당 의사 검토/승인
```

### AWS 서비스 매핑
- 오케스트레이터 엔진: Amazon Bedrock (Claude)
- RAG 지식베이스: Bedrock Knowledge Base + OpenSearch Serverless
- 중앙 데이터베이스: DynamoDB (이벤트 저장, 시간순 조회)
- 환자 마스터 DB: PostgreSQL
- 검사 모달: AWS Lambda (서버리스 함수)
- 워크플로우: AWS Step Functions (루프, 에러 핸들링, 타임아웃)
- 파일 저장: Amazon S3

### 기술 스택 (확정)
- 프론트엔드: React + Tailwind CSS + Recharts/D3.js
- 백엔드: FastAPI (Python)
- ML 프레임워크: PyTorch
- LLM: Amazon Bedrock (Claude)
- RAG: PubMedBERT + FAISS (흉부 모달 내부) + Bedrock KB + OpenSearch (오케스트레이터)
- DB: DynamoDB (시계열) + PostgreSQL (정형) + S3 (파일)
- 컨테이너: Docker + AWS ECS (Fargate)
- CI/CD: GitHub Actions
- 모니터링: Prometheus + Grafana

---

## 4. 흉부 모달 (팀원 A) — 내 담당 영역

### 4단계 내부 파이프라인
```
CXR 이미지 입력
    ↓
[Stage 1] DenseNet-121 → 14-질환 확률 (0~1)
    ↓
[Stage 2] Grad-CAM++ → 병변 위치 시각화 (어노테이션 이미지)
    ↓
[Stage 3] PubMedBERT + FAISS → 유사 판독문 Top-3 검색
    ↓
[Stage 4] Bedrock 멀티모달 → 이미지+확률+RAG+환자정보 종합 → 흉부과 의견 JSON
    ↓
출력: 중앙 오케스트레이터에 전달
```

### 모달 입력 (중앙 오케스트레이터 → 흉부 모달)
```json
{
  "patient_id": "p10000032",
  "request_id": "req_001",
  "modal": "chest_xray",
  "urgency": "stat",
  "cxr_image_s3_path": "s3://say1-pre-project-5/data/mimic-cxr-jpg/files/p10/p10000032/s50414267/xxx.jpg",
  "patient_info": {
    "age": 67, "sex": "M",
    "chief_complaint": "급성 흉통, 호흡곤란",
    "vitals": {"HR": 110, "BP": "90/60", "SpO2": 88, "RR": 28, "Temp": 36.8}
  },
  "prior_results": [
    {"modal": "ecg", "summary": "정상 동성리듬", "timestamp": "2026-03-21T10:02:00"}
  ]
}
```

### 모달 출력 (흉부 모달 → 중앙 오케스트레이터)
```json
{
  "modal": "chest_xray",
  "timestamp": "2026-03-21T10:05:00",
  "request_id": "req_001",
  "densenet_predictions": {
    "Pneumonia": 0.87, "Pleural Effusion": 0.62, "Atelectasis": 0.31,
    "Cardiomegaly": 0.12, "...(14개 전체)": "..."
  },
  "primary_finding": {
    "diagnosis": "Pneumonia",
    "location": "right_lower_lobe",
    "confidence": 0.87,
    "evidence": "DenseNet-121 확률 0.87 + Grad-CAM++ 우하엽 집중"
  },
  "secondary_findings": [
    {"diagnosis": "Pleural Effusion", "location": "right", "confidence": 0.62}
  ],
  "gradcam_image_s3_path": "s3://team-bucket/gradcam/req_001.jpg",
  "bedrock_visual_interpretation": "우하엽에 경화 소견, 우측 소량 흉수 동반",
  "rag_evidence": [
    {"similar_case": "s12345678", "similarity": 0.91, "impression": "RLL pneumonia with small effusion"}
  ],
  "thoracic_impression": "우하엽 폐렴 의심 (87%), 우측 소량 흉수 동반",
  "alert_flags": [],
  "recommendations": ["혈액검사 CBC/CRP", "항생제 경험적 투여 고려"],
  "suggested_next_actions_for_orchestrator": [
    {"action": "order_test", "modal": "lab", "tests": ["CBC", "CRP", "Blood Culture"]},
    {"action": "immediate_action", "description": "경험적 항생제 투여 고려"}
  ]
}
```

### 14개 질환 분류 목록 (DenseNet-121 출력)
| # | 영문명 | 한글명 |
|---|--------|--------|
| 1 | Atelectasis | 무기폐 |
| 2 | Cardiomegaly | 심비대 |
| 3 | Consolidation | 경화 |
| 4 | Edema | 부종 |
| 5 | Enlarged Cardiomediastinum | 종격동 확대 |
| 6 | Fracture | 골절 |
| 7 | Lung Lesion | 폐 병변 |
| 8 | Lung Opacity | 폐 음영 |
| 9 | No Finding | 소견 없음 |
| 10 | Pleural Effusion | 흉수 |
| 11 | Pleural Other | 기타 흉막 이상 |
| 12 | Pneumonia | 폐렴 |
| 13 | Pneumothorax | 기흉 |
| 14 | Support Devices | 의료 기구 |

Multi-label: 한 이미지에 여러 질환 동시 존재 가능. Sigmoid 출력, 확률 0.5 이상을 양성으로 판정.

---

## 5. 데이터 현황

### 데이터 출처 — 전부 공식
- 라벨: mimic-cxr-2.0.0-chexpert.csv (CheXpert NLP Labeler, 227,827 studies)
- 메타: mimic-cxr-2.0.0-metadata.csv (377,110 이미지, ViewPosition 등)
- 분할: mimic-cxr-2.0.0-split.csv (patient-level train/validate/test, 377,110 이미지)
- 이미지: S3 say1-pre-project-5/data/mimic-cxr-jpg/files/p10~p19/

### S3 버킷 구성
- say1-pre-project-2: MIMIC-IV EHR (환자 기본정보, 입원기록)
- say1-pre-project-5: MIMIC-CXR X-Ray 이미지 (377,105장, ~570GB)
  - 경로: data/mimic-cxr-jpg/files/p{10~19}/p{subject_id}/s{study_id}/{dicom_id}.jpg
  - 0-byte 파일 존재 (알려진 v2.0.0 이슈)
- say1-pre-project-7: MIMIC-IV Note (radiology.csv 2.67GB, discharge.csv 3.28GB)
- 작업 버킷: pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an (내 CSV, 모델, 결과물)

### 로컬 파일 구조
```
forpreproject/
├── CONTEXT.md                           (S3 동기화용 세션 컨텍스트)
├── PROJECT_CONTEXT_FULL.md              (본 문서 — 프로젝트 전체 컨텍스트)
├── record_daily.md                      (일일 작업 기록)
├── submit_training_jobs.ipynb           (원클릭 Training Job 제출 노트북)
├── .bkit-memory.json                    (PDCA 상태 추적)
│
├── mimic-cxr-csv/
│   ├── mimic-cxr-2.0.0-chexpert.csv     (8.9MB, 227,827 study별 14개 질환 라벨)
│   ├── mimic-cxr-2.0.0-metadata.csv     (55.4MB, 377,110 이미지 메타정보)
│   └── mimic-cxr-2.0.0-split.csv        (24.8MB, 377,110 이미지 split)
│
├── preprocessing/
│   ├── build_official_master.py
│   ├── mimic_cxr_official_master.csv     (377,095행, 62.66MB, 전체 뷰)
│   ├── mimic_cxr_official_pa_only.csv    (96,155행, PA 뷰만)
│   ├── p10_train_ready.csv               (9,118행, p10 + U-Ones, 테스트용)
│   ├── pos_weights.json                  (14개 질환별 클래스 가중치)
│   └── preprocessing_report.txt
│
├── layer1_segmentation/
│   ├── segmentation_model.py             (HF 사전학습 모델 래퍼)
│   └── train_unet.py                     (구버전, 사용 안 함)
│
├── layer2_detection/
│   └── densenet/
│       ├── train.py                      (all-in-one DenseNet-121 학습 스크립트)
│       └── training_job_config.json
│
├── layer3_clinical_logic/                (★ Layer 3 Clinical Logic Engine)
│   ├── models.py                         (입출력 데이터 클래스)
│   ├── thresholds.py                     (질환별 DenseNet 임계값)
│   ├── engine.py                         (4-Phase 메인 오케스트레이터)
│   ├── cross_validation.py               (3-소스 교차검증)
│   ├── differential.py                   (6개 감별진단 패턴)
│   ├── clinical_engine.py                (ChestModal 호환 래퍼)
│   ├── mock_data.py                      (4개 테스트 시나리오)
│   ├── rules/                            (14개 질환별 Rule)
│   └── tests/test_engine.py              (27개 pytest)
│
├── deploy/
│   ├── layer1_segmentation/              (Layer 1 Lambda 컨테이너)
│   │   ├── Dockerfile
│   │   └── lambda_function.py            (세그멘테이션 + 측정 + 중심선 보정)
│   ├── layer2_detection/                 (Layer 2 Lambda 컨테이너)
│   │   ├── Dockerfile
│   │   └── lambda_function.py            (DenseNet-121 추론)
│   ├── layer2b_yolov8/                   (Layer 2b Lambda 컨테이너)
│   │   ├── Dockerfile
│   │   └── lambda_function.py            (YOLOv8 Object Detection)
│   ├── layer3_clinical_logic/            (Layer 3 Lambda 컨테이너)
│   │   ├── Dockerfile
│   │   └── lambda_function.py
│   ├── layer5_rag/                       (Layer 5 Lambda 컨테이너)
│   │   ├── Dockerfile
│   │   └── lambda_function.py            (bge-small + FAISS 검색)
│   ├── layer6_bedrock_report/            (Layer 6 Lambda 컨테이너)
│   │   ├── Dockerfile
│   │   └── lambda_function.py            (Bedrock Claude 소견서 생성)
│   ├── chest_modal_orchestrator/         (★ 통합 오케스트레이터 Lambda)
│   │   ├── Dockerfile
│   │   ├── lambda_function.py            (HTTP 핸들러: GET→HTML, POST→pipeline)
│   │   ├── orchestrator.py               (6-Layer 순차/병렬 실행 엔진)
│   │   ├── layer_client.py               (Layer 1~6 HTTP 클라이언트)
│   │   ├── config.py                     (URL + 타임아웃 설정)
│   │   ├── input_parser.py               (입력 파싱)
│   │   └── index.html                    (통합 테스트 UI — 이미지뷰어+소견서)
│   ├── test_page/                        (레거시 테스트 페이지)
│   ├── _backup/                          (배포 백업)
│   └── DEPLOY_GUIDE.md                   (배포 가이드)
│
└── docs/
    ├── 01-plan/features/                 (PDCA Plan 문서)
    ├── 02-design/features/               (PDCA Design 문서)
    │   └── integrated-orchestrator.design.md
    ├── 03-analysis/                      (PDCA Gap Analysis 보고서)
    │   └── integrated-orchestrator.analysis.md  (v3, Match Rate 98%)
    └── API_REFERENCE.md                  (Layer 1~6 API 참조문서)
```

### CSV 3종 병합 과정 (이미 완료)
1. metadata(377,110) + split(377,110) → dicom_id 기준 JOIN → 377,110행
2. + chexpert(227,827) → subject_id + study_id 기준 JOIN → 377,095행 (15행 라벨 없음 제외)
3. image_path 생성: files/p{subject_id 앞2자리}/p{subject_id}/s{study_id}/{dicom_id}.jpg

---

## 6. 6-Layer 파이프라인 구현 현황 (2026-03-23 기준)

> v1(4-Stage)에서 v2(6-Layer + 2b)로 재설계됨. 상세 설계: `docs/02-design/features/integrated-orchestrator.design.md`
> 통합 오케스트레이터 Gap Analysis: **98% Match Rate** (v3, `docs/03-analysis/integrated-orchestrator.analysis.md`)

| Layer | 이름 | 상태 | Lambda URL | 비고 |
|-------|------|------|-----------|------|
| Layer 1 | Segmentation | ✅ 완료 | `jwhljyevn3...on.aws` | HF ianpan/chest-x-ray-basic, 중심선 L/R 보정 적용 |
| Layer 2 | Detection (DenseNet) | ✅ 완료 | `pk67s3qrp3...on.aws` | DenseNet-121, 14-질환 확률 |
| Layer 2b | Detection (YOLOv8) | ✅ 완료 | `yoaval7lao...on.aws` | YOLOv8 Object Detection, bbox + class_name + confidence |
| Layer 3 | Clinical Logic | ✅ 완료 | `ihq6gjldxb...on.aws` | 14-질환 Rule-Based + 3-소스 교차검증 |
| Layer 4 | Cross-Validation | ⬜ 스킵 | — | Layer 3에 교차검증 포함됨 |
| Layer 5 | RAG | ✅ 완료 | `rn32hjcarf...on.aws` | bge-small-en-v1.5 + FAISS, 124K 벡터 |
| Layer 6 | Bedrock Report | ✅ 완료 | `ofii46d5p6...on.aws` | Claude Sonnet 4.6, 구조화 소견서 생성 |
| **Integrated** | **Orchestrator** | ✅ 완료 | `emsptg6o6i...on.aws` | 6-Layer E2E 파이프라인, ~40s |

### 파이프라인 실행 흐름
```
이미지 입력 (base64 또는 S3 key)
    ↓
[Step 1+2] Layer 1 + Layer 2 + Layer 2b 병렬 실행 (ThreadPoolExecutor, max_workers=3)
    ↓
[Step 3] Layer 3 Clinical Logic (Layer 1+2 결과 의존)
    ↓
[Step 4] Layer 5 RAG (Layer 3 결과 의존, include_rag 옵션)
    ↓
[Step 5] Layer 6 Bedrock Report (Layer 1~5 결과 종합 → 소견서)
    ↓
결과 취합: summary + report + suggested_next_actions
```

### Layer 1 상세 (Segmentation)
- **모델**: HF `ianpan/chest-x-ray-basic` (사전학습)
- **클래스**: 4개 (background=0, R Lung=1, L Lung=2, Heart=3)
  - CXR 규약: 이미지 왼쪽 = 환자 오른쪽(R Lung), 이미지 오른쪽 = 환자 왼쪽(L Lung)
- **중심선(midline) 보정**: 모델 출력 후 좌우 폐 교차 픽셀 재분류 (16% 오분류 → 0%)
  - 폐 영역 중심점 계산 → 중심선 왼쪽의 L Lung 픽셀을 R Lung으로, 오른쪽의 R Lung 픽셀을 L Lung으로 재분류
- **측정값**: CTR, CP angle (L/R), 폐 면적비, 종격동 폭, 기관 편위, 횡격막 상태
- **시각화**: RGB 컬러 마스크 (파랑=R Lung, 초록=L Lung, 빨강=Heart) + SVG 측정선

### Layer 2b 상세 (YOLOv8 Object Detection)
- **모델**: YOLOv8 (흉부 이상 소견 bbox 탐지)
- **출력**: `detections[]` 배열 — 각 항목: `{class_name, confidence, bbox:[x1,y1,x2,y2], color}`
- **파이프라인 역할**: Layer 6에 `yolo_detections` 전달, 프론트엔드 SVG bbox 오버레이
- **Optional**: 실패 시 빈 배열 `[]`로 fallback, 파이프라인 중단 없음

### Layer 3 상세 (Clinical Logic)
- **14개 질환 Rule-Based 판독**: 각 질환별 독립 Rule 모듈 (CTR, CP angle, Silhouette sign 등)
- **3-소스 교차검증**: DenseNet 확률 vs YOLO bbox vs Clinical Logic 합의도
- **6개 감별진단 패턴**: CHF, 폐렴, 외상성/긴장성 기흉, 심인성 부종, 무기폐
- **위험도 3단계**: CRITICAL (alert) / URGENT (severe 2개+) / ROUTINE
- **처리시간**: ~0.0003초/건, 비용 ~0.1원/건
- **테스트**: 27개 pytest 전부 통과 (4개 시나리오)
- **API 문서**: `docs/API_REFERENCE.md`

### Layer 6 상세 (Bedrock Report)
- **모델**: Amazon Bedrock Claude Sonnet 4.6
- **입력**: anatomy(L1) + densenet(L2) + yolo(L2b) + clinical_logic(L3) + rag(L5) + patient_info
- **출력**: 7-섹션 구조화 소견서 (HEART/PLEURA/LUNGS/MEDIASTINUM/BONES/DEVICES/IMPRESSION) + RECOMMENDATION + NARRATIVE
- **처리시간**: ~35-40초 (Bedrock LLM 추론)

### 통합 오케스트레이터 프론트엔드
- **5개 테스트 케이스**: CHF(심부전), Pneumonia(폐렴), Tension PTX(긴장성기흉), Normal(정상), Multi-finding(다중소견)
- **이미지 뷰어**: 원본 CXR + 세그멘테이션 마스크 오버레이 + SVG 측정선 + YOLO bbox SVG
- **토글 버튼 3개**: Mask ON/OFF, Measure ON/OFF, YOLO ON/OFF
- **Anatomy Measurements 패널**: CTR, 폐 면적, 종격동, CP angle 등
- **소견서 렌더링**: 섹션별 접이식 표시
- **Pipeline Progress**: 6-Layer 진행률 실시간 표시

---

## 7. 전처리 완료 현황

### 1단계: CSV 정리 + 라벨 변환 (완료)

| 단계 | 입력 | 출력 | 비고 |
|------|------|------|------|
| CSV 3종 병합 | 공식 CSV 3개 | 377,095행 | metadata+split+chexpert JOIN |
| PA 뷰 필터링 | 377,095 | 96,155 | ViewPosition == 'PA' |
| 불량 제거 | 96,155 | 94,380 | 라벨 전부 NaN 1,775행 제거 |
| U-Ones 변환 | 94,380 | 94,380 | -1→1, NaN→0, 모든 라벨 0/1 |
| p10 필터 (테스트) | 94,380 | 9,118 | p10 그룹만 |
| pos_weight 계산 | train split | 14개 값 | BCEWithLogitsLoss용 |

### U-Ones 변환이란
CheXpert 라벨의 -1(불확실, "possible pneumonia")을 1(양성)로 변환.
NaN(미언급)은 0(음성)으로 변환.
CheXpert 논문에서 이 방법이 성능이 가장 좋았음.

### 학습 데이터 분할 (전체 PA 94,380장)
| split | 이미지 수 | 비율 |
|-------|-----------|------|
| train | 92,671 | 98.2% |
| validate | 747 | 0.8% |
| test | 998 | 1.1% |
| 합계 | 94,380 | |

### p10 테스트용 분할 (9,118장)
| split | 이미지 수 |
|-------|-----------|
| train | 8,993 |
| validate | 65 |
| test | 60 |
| 합계 | 9,118 |

주의: p10의 val/test가 매우 적음. 테스트용으로는 괜찮지만 성능 평가 신뢰도 낮음.
해결 방안: p10 내에서 환자(subject_id) 단위 8:1:1 재분할 가능.

### 14개 질환별 분포 (전체 PA, U-Ones 후, train split 92,671장 기준)
| 질환 | 양성 수 | 양성% | pos_weight | 비고 |
|------|---------|-------|------------|------|
| No Finding | 49,235 | 53.13% | 0.88 | |
| Lung Opacity | 14,630 | 15.79% | 5.33 | |
| Pleural Effusion | 13,091 | 14.13% | 6.08 | |
| Atelectasis | 12,423 | 13.41% | 6.46 | |
| Pneumonia | 11,462 | 12.37% | 7.09 | |
| Cardiomegaly | 10,769 | 11.62% | 7.61 | |
| Support Devices | 6,727 | 7.26% | 12.78 | |
| Edema | 5,496 | 5.93% | 15.86 | |
| Lung Lesion | 3,612 | 3.90% | 24.66 | |
| Enlarged Cardiomediastinum | 3,078 | 3.32% | 29.11 | |
| Consolidation | 2,895 | 3.12% | 31.01 | |
| Pneumothorax | 2,550 | 2.75% | 35.34 | |
| Fracture | 2,220 | 2.40% | 40.74 | |
| Pleural Other | 1,431 | 1.54% | 63.76 | <2% 극희귀 |

pos_weight 100 이상은 100으로 클리핑 (학습 불안정 방지).

---

## 7. 다음 단계: 전처리 2단계 — Dataset/DataLoader 구현

### 목표
CSV의 이미지 경로 → S3에서 이미지 로드 → 모델 입력 형태로 변환하는 PyTorch 파이프라인

### 이미지 전처리 파이프라인 (이미지 1장 기준)
```
S3에서 JPG 다운로드 (원본 해상도, 흑백 1채널)
    ↓
RGB 변환 (Image.open().convert('RGB') → 3채널)
    ↓
리사이즈 (짧은 변 256으로)
    ↓
[Train만] RandomRotation(10), ColorJitter(brightness=0.1, contrast=0.1), RandomCrop(224)
[Val/Test] CenterCrop(224)
    ↓
ToTensor (0~255 정수 → 0.0~1.0 실수)
    ↓
Normalize (mean=[0.485,0.456,0.406], std=[0.229,0.224,0.225])
    ↓
배치 32장 묶기 → GPU
```

### 필요한 구현물
1. MIMICCXRDataset 클래스 (PyTorch Dataset)
   - __getitem__: image_path → S3/로컬에서 로드 → transform → (image_tensor, label_tensor)
   - 이미지 로드 실패 시 검은 이미지 반환 (학습 중단 방지)
   - S3 직접 모드 / 로컬 캐시 모드 선택 가능

2. get_dataloaders 함수
   - CSV에서 split별 분리 → 각 split에 맞는 transform 적용
   - train: shuffle=True, drop_last=True
   - val/test: shuffle=False, drop_last=False
   - batch_size=32, num_workers=4, pin_memory=True

3. download_to_local 함수 (선택)
   - S3에서 로컬로 이미지 일괄 다운로드 (캐시)
   - 이미 있는 파일 스킵, 0-byte 스킵, 진행률 표시

4. verify_dataset 함수
   - 배치 1개 로드 → shape 확인, 값 범위 확인, 샘플 시각화

### S3 접근 정보
- 이미지 버킷: say1-pre-project-5
- 이미지 prefix: data/mimic-cxr-jpg/
- 전체 S3 경로: s3://say1-pre-project-5/data/mimic-cxr-jpg/{image_path}
- image_path 예시: files/p10/p10000032/s50414267/02aa804e-bde0afdd-112c0b34-7bc16630-4e384014.jpg

### 주의사항
- boto3 client는 num_workers > 0일 때 프로세스마다 새로 생성 (fork safety)
- __getitem__에서 lazy initialization 패턴 사용
- 이미지 로드 실패 시 try/except로 학습 중단 방지

---

## 8. 다음 단계: DenseNet-121 학습

### 왜 DenseNet-121인가
- CheXpert 논문(Stanford, 2019)과 MIMIC-CXR 공식 벤치마크의 표준 모델
- Dense Connection으로 미세한 음영 차이가 중요한 흉부 X-Ray에 유리
- 논문과 직접 성능 비교 가능 (Mean AUROC 기준)

### 모델 구성
- ImageNet pretrained DenseNet-121 가져오기
- 마지막 classifier 층: 1024 → 14로 교체 (nn.Linear(1024, 14))
- Sigmoid 출력 (multi-label, 각 질환 독립 이진 분류)
- Softmax가 아닌 이유: multi-label이라 한 이미지에 여러 질환 동시 가능

### 학습 전략: 2-Stage Fine-tuning
- Stage 1 (Classifier Only, ~10에폭):
  - backbone freeze (features 파라미터 requires_grad=False)
  - 새로 붙인 classifier만 학습 (lr=1e-3, Adam)
  - ImageNet 지식 보존, classifier가 대략적 매핑 학습
- Stage 2 (Full Fine-tuning, ~30에폭):
  - 전체 unfreeze
  - Discriminative LR: 앞쪽 레이어 lr 작게, 뒤쪽 크게
  - lr=1e-4 (backbone), lr=1e-3 (classifier)

### Loss 함수
- BCEWithLogitsLoss (내부적으로 Sigmoid + BCE)
- pos_weight: pos_weights.json에서 로드 (클래스 불균형 보정)

### 최적화
- Optimizer: Adam (또는 AdamW)
- Scheduler: CosineAnnealingLR 또는 ReduceLROnPlateau
- Mixed Precision (fp16): GradScaler + autocast (GPU 메모리 절약, 속도 향상)
- Early Stopping: val loss 5에폭 연속 개선 없으면 중단

### 평가 지표
- Per-pathology AUROC (14개 질환 각각)
- Mean AUROC: 14개 평균 → 0.85 이상 목표 (CheXpert 논문 ~0.89)
- Accuracy는 사용하지 않음 (multi-label + 불균형에서 무의미)

---

## 9. 학습 후 파이프라인

### Stage 2: Grad-CAM++ (별도 학습 불필요)
- 학습 완료된 DenseNet-121의 마지막 dense block에서 히트맵 추출
- pytorch-grad-cam 라이브러리 사용
- 양성 질환(확률 0.5+)마다 개별 히트맵 생성
- 원본 이미지 위에 반투명 오버레이 → 어노테이션 이미지
- 위치(right_lower_lobe 등), 면적(%), bounding box 추출

### Stage 3: RAG 지식베이스 (PubMedBERT + FAISS)
- 데이터: MIMIC-IV Note의 radiology.csv (판독문)
- PubMedBERT로 판독문 임베딩 → FAISS 인덱스 구축
- 검색 쿼리: DenseNet-121 양성 소견을 텍스트로 변환
- 코사인 유사도로 유사 판독문 Top-3 반환

### Stage 4: Bedrock 멀티모달
- Bedrock Claude에 어노테이션 이미지(base64) + 14-label 확률 + RAG 결과 + 환자정보 전달
- 시스템 프롬프트: "당신은 흉부영상의학과 전문의입니다"
- JSON 형태로 종합 의견 출력

---

## 10. 테스트 케이스 시나리오

### 케이스 A: 단순 (X-Ray 1회 종결)
- 28세 여성, 기침 2주, 미열
- 오케스트레이터: 기침+미열 → X-Ray → 우하엽 경화 87% → 소견서
- 총 검사 1회

### 케이스 B: 복잡 (여러 검사 + 즉시 조치)
- 67세 남성, 급성 흉통, 식은땀, 왼팔 저림
- 오케스트레이터: ECG → STEMI 95% → 즉시 조치 3건(아스피린/헤파린/심도자실) → 혈액검사 → 트로포닌 극상승 → 유전체 → CYP2C19 변이 → 소견서
- 총 검사 3회 + 즉시 조치 3건

### 케이스 C: 중등도 (불확실 → 추가 검사)
- 45세 남성, 호흡곤란
- 오케스트레이터: ECG+X-Ray 동시 → 심방세동+흉수+심비대 → 혈액검사 → BNP 극상승 → RAG → 소견서
- 총 검사 4회 + 조치 2건

---

## 11. AWS 환경 정보

- AWS 계정: 666803869796
- IAM user: aws-say2-11
- 리전: ap-northeast-2 (서울)
- SageMaker ExecutionRole: AmazonSageMaker-ExecutionRole-20260317T130080
- 학습 인스턴스: ml.g4dn.xlarge (T4 16GB, $0.73/h) 권장
- 전처리 인스턴스: ml.t3.medium ($0.05/h)
- EBS 볼륨: 200GB 이상 (PA 이미지 캐시 ~145GB)

### IAM 권한 이슈
- SageMaker ExecutionRole에 S3 GetObject 권한 없음
- 해결: os.environ으로 AWS 키 직접 주입 방식 사용
- ⚠️ 이전 세션에서 AWS 키 노출됨 → 키 교체 필요

---

## 12. 완료된 작업

- [x] 시스템 아키텍처 v1→v2 재설계 (병렬→순차 오케스트레이터)
- [x] 5모달 재구성 (ECG 추가, 비응급 제거)
- [x] Slack 캔버스 7개 데이터셋 정의서 + 목차 허브
- [x] v2 오케스트레이터 캔버스
- [x] 다이어그램 4종 (아키텍처, 테스트케이스, 입출력, 14-질환표)
- [x] 흉부 모달 4단계 파이프라인 설계
- [x] PhysioNet CITI 윤리교육 이수 + Training 승인
- [x] 공식 CSV 3종 확보 (Kaggle 경유, CheXpert+metadata+split)
- [x] 전처리 1단계: CSV 3종 병합 → 377,095행 Master CSV
- [x] 전처리 1단계: PA 필터 → U-Ones → 불량 제거 → 94,380장
- [x] 전처리 1단계: p10 테스트셋 9,118장 + pos_weight 계산
- [x] 기술 스택 확정 (React+FastAPI+PyTorch+Bedrock+Docker)
- [x] 프론트엔드 대시보드 와이어프레임 설계
- [x] 팀 업무 프로세스 통일 안건 정리
- [x] U-Net 세그멘테이션 학습 스크립트 작성 (all-in-one, CheXmask 통합)
- [x] DenseNet-121 분류 학습 스크립트 작성 (all-in-one, 전체 PA 94,380장)
- [x] SageMaker Training Job 원클릭 제출 노트북 작성 (submit_training_jobs.ipynb)
- [x] U-Net Training Job 제출 (unet-lung-heart-v2, ml.g5.xlarge spot)
- [x] DenseNet Training Job 제출 (densenet121-full-pa-v1, ml.g4dn.xlarge spot)
- [x] Layer 1 Segmentation Lambda 배포 (HF 사전학습 모델)
- [x] Layer 2 Detection Lambda 배포 (DenseNet-121)
- [x] Layer 3 Clinical Logic Lambda 배포 (14개 질환 Rule-Based)
- [x] Layer 5 RAG 전체 파이프라인 구축 (판독문 추출 → 임베딩 → 필터링 → FAISS 인덱스)
- [x] Layer 5 RAG Lambda 라이브 배포 (124K 벡터, bge-small-en-v1.5 + FAISS)

- [x] Layer 6 Bedrock Report 구현 + Lambda 배포 (Claude Sonnet 4.6 소견서 생성)
- [x] 통합 오케스트레이터 구현 + Lambda 배포 (6-Layer 파이프라인 E2E ~40s)
- [x] CORS 이중 헤더 버그 수정 (Layer 3/5/6)
- [x] 통합 테스트 페이지 (마스크 오버레이 + SVG 측정선 ON/OFF + Presigned URL)
- [x] 전체 Layer UI 리디자인 + Docker 이미지 최적화 (10.3→8.8GB)
- [x] Layer 2b YOLOv8 Object Detection Lambda 배포 (bbox 탐지)
- [x] Layer 2b 오케스트레이터 통합 (백엔드: 3-way 병렬 + 프론트엔드: 12개 터치포인트)
- [x] Layer 1 세그멘테이션 마스크 L/R 중심선 보정 (교차 픽셀 16% → 0%)
- [x] YOLO 바운딩 박스 SVG 오버레이 (이미지 위 bbox 시각화 + ON/OFF 토글)
- [x] PDCA Gap Analysis v3: 98% Match Rate (48항목 중 47일치, Critical 0건)
- [x] 5개 테스트 케이스 UI (CHF, Pneumonia, Tension PTX, Normal, Multi-finding)

## 13. 전체 엔드포인트 (2026-03-23 기준)

| Layer | Lambda | Function URL |
|---|---|---|
| **Integrated** | chest-modal-integrated | `https://emsptg6o6iwonhhbxyxvasm7ga0yjluu.lambda-url.ap-northeast-2.on.aws/` |
| Layer 1 | layer1-segmentation | `https://jwhljyevn3hm44nhvs5zcdstmi0tmuvi.lambda-url.ap-northeast-2.on.aws/` |
| Layer 2 | layer2-detection | `https://pk67s3qrp3b3xluqkcp6neqly40kduol.lambda-url.ap-northeast-2.on.aws/` |
| Layer 2b | layer2b-yolov8 | `https://yoaval7laoc4ngnkr7uod7dufm0nmxib.lambda-url.ap-northeast-2.on.aws/` |
| Layer 3 | layer3-clinical-logic | `https://ihq6gjldxbulfke5xd2xexnoqe0vyrxt.lambda-url.ap-northeast-2.on.aws/` |
| Layer 5 | layer5-rag | `https://rn32hjcarfgqhopm266iidoeey0lkbkt.lambda-url.ap-northeast-2.on.aws/` |
| Layer 6 | layer6-bedrock-report | `https://ofii46d5p6446ceahn3ucb5f2a0xcvej.lambda-url.ap-northeast-2.on.aws/` |

## 14. 미완료 (향후)

- [ ] PhysioNet credentialing 신청 (추천인 확보 필요)
- [ ] 모델 평가 (Per-pathology AUROC, Mean AUROC, Dice Score)
- [ ] Grad-CAM++ 시각화 구현
- [ ] 프론트엔드 대시보드 구현 (React) — 현재 Lambda 통합 테스트 UI로 대체 중
- [ ] Upload Image 기능 완성 (사용자 직접 CXR 업로드)
- [ ] 발표 자료 준비

---

## 15. SageMaker Training Job 아키텍처 (2026-03-21 구축)

### All-in-One 학습 스크립트 설계
p10 테스트 단계를 건너뛰고 전체 PA 데이터셋으로 프로덕션 학습 전환.
SageMaker Training Job이 데이터 준비부터 학습까지 모두 자체 처리하는 올인원 방식.

```
Training Job 컨테이너 내부 실행 흐름:
Phase 1: 데이터 준비 (자동)
  ├── CheXmask CSV 다운로드 (S3 캐시 → PhysioNet aria2c 16병렬)
  ├── Split CSV 로드 (S3 다중 경로 시도 → hash 기반 fallback)
  ├── 필요한 이미지만 S3에서 선택 다운로드 (ThreadPoolExecutor 32병렬)
  └── 매니페스트/CSV 구축
Phase 2: 모델 학습
  ├── Dataset/DataLoader 구성
  ├── 학습 루프 (Mixed Precision, 체크포인트)
  └── 결과 저장 (모델 + results.json)
```

### U-Net 세그멘테이션 (layer1_segmentation/train_unet.py)
- 모델: U-Net + EfficientNet-B4 encoder
- 데이터: CheXmask (PhysioNet) — RLE 인코딩된 폐/심장 마스크
- 핵심: RLE on-the-fly 디코딩 (Dataset.__getitem__에서 ~1ms/이미지)
- 클래스: 4개 (background=0, R_Lung=1, L_Lung=2, Heart=3) — CXR 규약: 이미지 좌=환자 우(R), 이미지 우=환자 좌(L)
- 손실: Dice + CrossEntropy
- 인스턴스: ml.g5.xlarge (A10G 24GB), 스팟
- 이미지 수: ~94,380장 (PA only)
- Job 이름: unet-lung-heart-v2

### DenseNet-121 분류 (layer2_detection/densenet/train.py)
- 모델: DenseNet-121 (ImageNet pretrained)
- 데이터: 전체 PA 94,380장 (p10이 아닌 전체)
- 학습: 2-Stage Fine-tuning (Stage1: classifier only 5에폭, Stage2: full 25에폭)
- 손실: BCEWithLogitsLoss + pos_weight
- 인스턴스: ml.g4dn.xlarge (T4 16GB), 스팟
- Job 이름: densenet121-full-pa-v1

### 핵심 기술 결정
- SageMaker Data Channel 미사용: 전체 4.7TB 다운로드 방지, boto3 직접 선택 다운로드
- CheXmask S3 캐싱: 첫 실행 시 PhysioNet→S3 캐시, 이후 S3에서 ~1분 다운로드
- aria2c 16병렬: PhysioNet 다운로드 속도 개선 (기존 177KB/s → 수십MB/s)
- Hash 기반 split fallback: split CSV 404 시 md5(subject_id)로 결정론적 분할

### 제출 노트북: submit_training_jobs.ipynb
- 셀 2개 실행으로 양쪽 Training Job 동시 제출
- 예상 비용: ~$4-7 (스팟 인스턴스)
- 결과 확인: 셀 3-4 (상태 체크 + 모델 다운로드)

---

## 16. 로드맵

| 주차 | 목표 |
|------|------|
| 1~2주차 | 각 팀원 독립 모달 완성 (JSON 입출력 함수 형태) |
| 3주차 | 오케스트레이터 구축 (Bedrock 프롬프트 + 중앙 DB + 루프) |
| 4주차 | 테스트 케이스 3개 실행 + 의사결정 품질 평가 |
| 5주차 | 발표 자료 준비 (시각화, 성능 지표, v1 vs v2 비교) |

---

## 16. 참고 Slack 캔버스

- 데이터셋 정의서 01~07: F0ALBBX0N7R ~ F0AM5P202MP
- 목차 허브: F0AMM4HJVLY
- v2 오케스트레이터 설계: F0AM3A2E21H
- 팀 업무 프로세스: F0AMW78DD3N

---

## 17. 데이터셋 검증 (별도)

- mimic_verification_prompt_v2.md에 전수 검사 계획서 작성 완료
- SageMaker ml.m5.2xlarge에서 수행 예정
- 3개 버킷(EHR, X-Ray, Note)의 subject_id 교차 검증
- 아직 미실행
