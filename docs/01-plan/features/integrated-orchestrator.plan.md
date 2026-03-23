# 흉부 모달 통합 오케스트레이터 구축 계획

> **Summary**: 6개 Layer를 하나의 통합 엔드포인트로 묶어 CXR 이미지 1장 → 전체 파이프라인 → 최종 소견서 반환
>
> **Project**: Dr. AI Radiologist (MIMIC-CXR)
> **Author**: hyunwoo
> **Date**: 2026-03-23
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 6개 Layer가 각각 독립 Lambda로 운영 중이나, 통합 호출 수단이 없음. CXR 이미지 한 장으로 전체 파이프라인을 돌리려면 수동으로 5개 API를 순차 호출해야 함 |
| **Solution** | 통합 오케스트레이터 Lambda를 신규 배포하여, 기존 6개 Layer를 HTTP 호출로 연결. 유연한 입력(어떤 형태든 수용) + 구조화된 출력(전체 결과 보관, 반환 형태만 변환) |
| **Function/UX Effect** | 이미지 1장 + 환자정보 입력 → 실시간 파이프라인 진행 표시 → 소견서 + 위험도 + 감별진단 + 권고조치 한 화면에 표시. 발표 시 임팩트 극대화 |
| **Core Value** | 6-Layer 파이프라인의 실질적 완성. 다른 모달(ECG, 혈액검사)과의 연동 인터페이스 사전 확보. 포트폴리오 최종 데모 가능 |

---

## 1. 현재 상태

### 1.1 완료된 것 (기존 인프라)
- [x] Layer 1 Segmentation Lambda 배포 완료 (Function URL 활성)
- [x] Layer 2a DenseNet Lambda 배포 완료 (Function URL 활성)
- [x] Layer 2b YOLOv8 Lambda 배포 완료 (Function URL 활성)
- [x] Layer 3 Clinical Logic Lambda 배포 완료 (Function URL 활성)
- [x] Layer 5 RAG Lambda 배포 완료 (Function URL 활성, FAISS 124K 라이브)
- [x] Layer 6 Bedrock Report Lambda 배포 완료 (Function URL 활성)
- [x] API 참조 문서 작성 완료 (`docs/API_REFERENCE.md`)
- [x] 전체 Layer UI 통일 리디자인 완료
- [x] Docker 이미지 최적화 완료 (10.3GB → 8.8GB)

### 1.2 아직 안 된 것
- [ ] 통합 오케스트레이터 Lambda 구현 + 배포
- [ ] 통합 테스트 페이지 (실시간 파이프라인 진행 표시)
- [ ] 테스트용 CXR 샘플 이미지 5장 S3 준비
- [ ] 엔드-투-엔드 5개 시나리오 테스트

### 1.3 환경 제약
| 환경 | 가능한 것 | 불가능한 것 |
|------|-----------|-------------|
| **로컬 CLI** (`aws-say2-11`) | Lambda, ECR, S3, CloudFront, Docker 빌드 | SageMaker |
| **SageMaker** | S3, 학습/추론 | Docker, Lambda, ECR |

---

## 2. 아키텍처

### 2.1 파이프라인 흐름

```
[통합 오케스트레이터 Lambda] — HTTP 호출만, 자체 모델 없음
    │
    │  입력: CXR 이미지 (base64 or S3 key) + 환자 정보 (선택)
    │
    ├── Step 1+2: Layer 1 + Layer 2a 병렬 호출
    │     Layer 1 → 세그멘테이션, CTR, 해부학 측정
    │     Layer 2a → 14개 질환 확률 + 양성/음성 판정
    │     (Layer 2b YOLOv8도 병렬 추가 가능)
    │
    ├── Step 3: Layer 3 호출 (Layer 1+2 결과 필요)
    │     → 14개 질환 임상 판독 + 교차검증 + 감별진단 + 위험도
    │
    ├── Step 4: Layer 5 호출 (Layer 3 결과 필요)
    │     → 유사 판독문 Top-K 검색 (FAISS)
    │
    └── Step 5: Layer 6 호출 (모든 결과 필요)
          → Bedrock 소견서 생성 (구조화 + 서술형 + 요약 + 권고)
```

### 2.2 핵심 원칙

1. **기존 6개 Layer Lambda는 절대 수정하지 않음** — HTTP 호출만
2. **유연한 입력** — 어떤 형태로 오든 필요한 것만 추출, 없는 필드는 기본값
3. **전체 결과 보관** — 모든 Layer 결과를 원본 그대로 저장, 반환 형태만 OutputFormatter에서 변환
4. **레이어 실패 시 부분 계속** — 한 레이어가 실패해도 나머지는 계속 진행
5. **say1-pre-project-* 버킷 쓰기 절대 금지**

---

## 3. 기존 레이어 엔드포인트

```python
ENDPOINTS = {
    "layer1": "https://jwhljyevn3hm44nhvs5zcdstmi0tmuvi.lambda-url.ap-northeast-2.on.aws/",
    "layer2": "https://pk67s3qrp3b3xluqkcp6neqly40kduol.lambda-url.ap-northeast-2.on.aws/",
    "layer2b": "https://yoaval7laoc4ngnkr7uod7dufm0nmxib.lambda-url.ap-northeast-2.on.aws/",
    "layer3": "https://ihq6gjldxbulfke5xd2xexnoqe0vyrxt.lambda-url.ap-northeast-2.on.aws/",
    "layer5": "https://rn32hjcarfgqhopm266iidoeey0lkbkt.lambda-url.ap-northeast-2.on.aws/",
    "layer6": "https://ofii46d5p6446ceahn3ucb5f2a0xcvej.lambda-url.ap-northeast-2.on.aws/",
}
```

### 3.1 각 레이어 API 요약 (상세: docs/API_REFERENCE.md)

| Layer | 입력 | 출력 핵심 | 타임아웃 |
|-------|------|-----------|----------|
| Layer 1 | `image_base64` or `s3_key` | measurements, mask, view, age_pred, sex_pred | 120s |
| Layer 2a | `image_base64` or `s3_key` | findings, probabilities, positive_findings | 180s |
| Layer 2b | `image_base64` or `s3_key` | detections, annotated_image_base64 | 180s |
| Layer 3 | `action:"custom"` + anatomy + densenet + patient_info | findings, cross_validation, differential, risk_level | 30s |
| Layer 5 | `action:"custom"` + clinical_logic + top_k | results (유사 판독문 Top-K), query_text | 120s |
| Layer 6 | `action:"generate"` + 전체 결과 + patient_info + language | report (structured + narrative + summary), suggested_next_actions | 120s |

### 3.2 데이터 변환 포인트

Layer 간 데이터를 넘길 때 변환이 필요한 지점:

1. **Layer 1 → Layer 3**: `measurements` 내 중첩 구조를 평탄화 (mediastinum.status → mediastinum_status 등)
2. **Layer 2a → Layer 3**: `probabilities`의 키에서 공백을 언더스코어로 변환 ("Pleural Effusion" → "Pleural_Effusion")
3. **Layer 3 → Layer 5**: Layer 3의 `result` 객체를 `clinical_logic` 필드로 전달
4. **전체 → Layer 6**: anatomy_measurements, densenet_predictions, clinical_logic, cross_validation_summary, rag_evidence, patient_info를 조합

---

## 4. 통합 모달 입력/출력 설계

### 4.1 입력 (유연한 구조)

```json
{
  "image_base64": "data:image/jpeg;base64,...",   // 필수 (또는 s3_key)
  "s3_key": "data/mimic-cxr-jpg/files/...",       // 필수 (또는 image_base64)

  "patient_info": {                                // 선택
    "patient_id": "p10000032",
    "age": 72, "sex": "M",
    "chief_complaint": "흉통, 호흡곤란",
    "vitals": { "temperature": 38.2, "heart_rate": 110, "spo2": 88 }
  },

  "prior_results": [                               // 선택 — 다른 모달 결과
    { "modal": "ecg", "summary": "동성빈맥", "findings": {} }
  ],

  "options": {                                     // 선택
    "report_language": "ko",                       // "ko" | "en" (기본: "ko")
    "include_rag": true,                           // RAG 포함 여부 (기본: true)
    "top_k": 3,                                    // RAG Top-K (기본: 3)
    "skip_layers": [],                             // 특정 레이어 스킵 (테스트용)
    "return_mask": true,                           // 세그멘테이션 마스크 반환
    "return_annotated_image": true                 // YOLO bbox 이미지 반환
  }
}
```

**입력 파싱 전략**: 필드 이름 다양성 수용 (image_base64 / image / cxr_image, sex / gender 등). 없는 필드는 None/기본값. 원본 입력도 `raw_input`으로 보관.

### 4.2 출력 (구조화)

```json
{
  "modal": "chest_xray",
  "request_id": "req_20260323_001",
  "timestamp": "2026-03-23T15:30:00+09:00",
  "status": "success",

  "summary": {
    "risk_level": "URGENT",
    "detected_diseases": ["Cardiomegaly", "Pleural_Effusion", "Edema"],
    "detected_count": 3,
    "primary_diagnosis": "울혈성 심부전 (CHF)",
    "one_line": "심비대 + 양측 흉수 + 폐부종 → CHF 의심. URGENT.",
    "alert_flags": []
  },

  "suggested_next_actions": [...],
  "report": { "structured": {...}, "narrative": "...", "summary": "..." },

  "layer_results": {
    "layer1_segmentation": { "status": "success", ... },
    "layer2_densenet": { "status": "success", ... },
    "layer2b_yolov8": { "status": "success" | "skipped", ... },
    "layer3_clinical_logic": { "status": "success", ... },
    "layer5_rag": { "status": "success", ... },
    "layer6_bedrock": { "status": "success", ... }
  },

  "pipeline_metadata": {
    "total_processing_time_ms": 44590,
    "layers_executed": [...],
    "layers_skipped": [...],
    "layers_failed": [],
    "options_used": {...}
  }
}
```

---

## 5. 구현 파일 구조

```
deploy/chest_modal_orchestrator/
├── Dockerfile                  ← 경량 (requests만, PyTorch 없음)
├── requirements.txt            ← requests
├── lambda_function.py          ← Lambda 핸들러 (GET → HTML, POST → JSON)
├── orchestrator.py             ← 파이프라인 오케스트레이션 로직 (핵심)
├── input_parser.py             ← 유연한 입력 파싱
├── output_formatter.py         ← 출력 형태 변환 (default/summary_only/orchestrator_format)
├── layer_client.py             ← 각 Layer HTTP 호출 클라이언트
├── config.py                   ← 엔드포인트 URL, 옵션 기본값
├── test_cases.py               ← 5개 테스트 케이스 데이터
└── index.html                  ← 통합 테스트 웹 페이지 (실시간 파이프라인 진행)
```

### 5.1 Dockerfile (초경량)

```dockerfile
FROM public.ecr.aws/lambda/python:3.12
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && rm -rf /root/.cache /tmp/*
COPY *.py ./
COPY index.html ./
CMD ["lambda_function.handler"]
```

예상 이미지 크기: **~760MB** (베이스 이미지 748MB + requests 패키지 ~12MB)
→ 기존 Layer 1~6 중 가장 가벼움 (PyTorch/모델 없이 HTTP 호출만)

### 5.2 Lambda 설정

| 항목 | 값 | 이유 |
|------|-----|------|
| 함수 이름 | `chest-modal-integrated` | |
| 메모리 | 512MB | HTTP 호출만, 모델 로드 없음 |
| 타임아웃 | **300초 (5분)** | Layer 1~6 순차 실행 시 최대 ~3분 (Cold Start 포함) |
| /tmp | 512MB | |
| ECR | `chest-modal-integrated` | |
| AuthType | NONE (공개) | |
| IAM Role | `say-2-lambda-bedrock-role` (기존 공유) | S3 접근 + Lambda 호출 권한 |

---

## 6. 핵심 모듈 설계

### 6.1 orchestrator.py — 파이프라인 실행 순서

```
┌─────────────────────────────────────────────┐
│ Step 1+2: Layer 1 + Layer 2a 병렬 호출       │
│  ThreadPoolExecutor(max_workers=3)           │
│  (Layer 2b도 있으면 병렬 추가)                │
├─────────────────────────────────────────────┤
│ Step 3: Layer 3 호출                          │
│  입력: Layer 1 measurements(평탄화)           │
│       + Layer 2a probabilities(키 변환)       │
│       + patient_info + prior_results         │
├─────────────────────────────────────────────┤
│ Step 4: Layer 5 RAG 호출                      │
│  입력: Layer 3 result → clinical_logic       │
│  (options.include_rag가 false면 스킵)         │
├─────────────────────────────────────────────┤
│ Step 5: Layer 6 Bedrock 소견서 호출            │
│  입력: 전체 Layer 결과 + patient_info         │
│       + rag_evidence + language              │
├─────────────────────────────────────────────┤
│ 결과 취합: summary + next_actions + report   │
└─────────────────────────────────────────────┘
```

**에러 처리**: 각 Layer 호출은 try/except로 감싸서, 실패 시 해당 Layer만 `"status": "error"` 표시하고 나머지는 계속 진행. Layer 1 또는 2가 실패하면 Layer 3 이하는 스킵.

### 6.2 input_parser.py — 데이터 변환

Layer 1 → Layer 3 변환 시 평탄화 필요:
```
measurements.mediastinum.status → anatomy.mediastinum_status
measurements.trachea.midline → anatomy.trachea_midline
measurements.cp_angle.right.status → anatomy.right_cp_status
measurements.cp_angle.right.angle_degrees → anatomy.right_cp_angle_degrees
... (총 12개 필드 평탄화)
```

Layer 2a → Layer 3 변환:
```
probabilities["Pleural Effusion"] → densenet["Pleural_Effusion"]
(공백 → 언더스코어 치환)
```

### 6.3 layer_client.py — HTTP 호출

- `requests.Session()` 사용 (connection reuse)
- 각 Layer별 타임아웃 설정 (Layer 1: 120s, Layer 2: 180s, Layer 3: 30s, Layer 5: 120s, Layer 6: 120s)
- 응답 시간 자동 측정 (`processing_time_ms`)

---

## 7. 테스트 페이지 설계

### 7.1 방식: 방법 B (JS 직접 순차 호출)

테스트 페이지에서 통합 Lambda를 호출하는 대신, **각 Layer를 JS에서 직접 순차 호출**하여 실시간 진행 표시.

장점:
- 발표 시 각 Layer가 하나씩 완료되는 과정을 **실시간으로** 보여줄 수 있음
- 통합 Lambda도 별도 API로 존재하여 프로그래밍 호출 가능

### 7.2 UI 구조

```
┌─────────────────────────────────────────────────────────┐
│ Chest X-Ray Modal — Integrated Pipeline                 │
│ 6-Layer Sequential Analysis                             │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  TEST CASES                                             │
│  [CHF] [Pneumonia] [Tension PTX] [Normal] [Multi]       │
│  + 직접 이미지 업로드                                     │
│                                                         │
├─────────────┬───────────────────────────────────────────┤
│  CXR 이미지  │  Pipeline Progress                       │
│  (미리보기)   │  ✅ Layer 1: Segmentation    1.2s        │
│             │  ✅ Layer 2: DenseNet        0.9s         │
│             │  ⏳ Layer 3: Clinical Logic  ...          │
│             │  ⬜ Layer 5: RAG                           │
│             │  ⬜ Layer 6: Bedrock Report                │
│             │  Total: 42.5s                             │
├─────────────┴───────────────────────────────────────────┤
│  SUMMARY          RISK: [URGENT]                        │
│  감별진단: 1. CHF  2. ...                                │
├─────────────────────────────────────────────────────────┤
│  REPORT (소견서) — 8섹션 구조화 판독문                    │
├─────────────────────────────────────────────────────────┤
│  LAYER DETAILS (접기/펼치기)                             │
│  ▶ Layer 1~6 각각의 원본 결과                            │
├─────────────────────────────────────────────────────────┤
│  RAW JSON (접기/펼치기) — 디버깅용                       │
└─────────────────────────────────────────────────────────┘
```

### 7.3 주요 UI 기능

| 기능 | 설명 |
|------|------|
| 테스트 케이스 탭 | 5개 시나리오 + 직접 업로드 |
| 실시간 진행 표시 | 각 Layer 호출 시 ⬜→⏳→✅/❌ 상태 전환 |
| 위험도 배지 | ROUTINE(회색), URGENT(주황), CRITICAL(빨강+깜빡임) |
| 소견서 렌더링 | 구조화 8섹션을 의료 판독문 스타일로 표시 |
| Layer별 상세 | 접기/펼치기로 각 Layer 원본 결과 확인 |
| RAW JSON | 디버깅용 요청/응답 JSON 전문 |
| 디자인 시스템 | PROMPT_UI_Redesign_All_Layers.md 디자인 그대로 적용 |

---

## 8. 테스트 케이스 5개

| # | 시나리오 | 설명 | 예상 Risk | 핵심 검증 포인트 |
|---|---------|------|-----------|-----------------|
| 1 | **CHF (심부전)** | 72세 남성, 호흡곤란 2주, 하지 부종 | URGENT | CTR > 0.50 + 흉수 + 부종 → CHF 감별 |
| 2 | **Pneumonia (폐렴)** | 67세 남성, 발열 38.5°C, 기침, 농성 객담 | URGENT | 경화 + 발열 + WBC 교차 → 폐렴 판정 |
| 3 | **Tension PTX (긴장성 기흉)** | 25세 남성, 교통사고 후 좌측 흉통 | CRITICAL | 기흉 + 기관 편위 → alert=true |
| 4 | **Normal (정상)** | 35세 여성, 건강검진 | ROUTINE | 8-area 체크리스트 전부 통과 |
| 5 | **Multi-finding (다중 소견)** | 80세 여성, 낙상 후 흉통, COPD 기왕력 | URGENT | 골절 + 기흉 + 무기폐 등 복합 |

각 테스트 케이스에는 환자 정보(vitals 포함) + prior_results(ECG/Lab) 포함.
샘플 CXR 이미지: 기존 Layer 테스트에서 사용하던 이미지를 `web/test-integrated/samples/`에 복사.

---

## 9. 성능 예상치

### 9.1 처리 시간

| 단계 | Cold Start | Warm Start | 비고 |
|------|-----------|------------|------|
| Step 1+2 (Layer 1+2 병렬) | ~25초 | ~2초 | 병렬 실행, 느린 쪽 기준 |
| Step 3 (Layer 3) | ~2초 | <0.01초 | 순수 Python |
| Step 4 (Layer 5 RAG) | ~10초 | ~0.06초 | FAISS 검색 |
| Step 5 (Layer 6 Bedrock) | ~42초 | ~40초 | Bedrock API 호출 (대부분 여기) |
| **합계** | **~80초** | **~43초** | |

### 9.2 비용 (호출당)

| 항목 | 비용 |
|------|------|
| Orchestrator Lambda | ~$0.0004 (512MB × 300s) |
| Layer 1 Lambda | ~$0.002 |
| Layer 2a Lambda | ~$0.002 |
| Layer 3 Lambda | ~$0.0001 |
| Layer 5 Lambda | ~$0.0001 |
| Layer 6 Lambda (Bedrock 토큰) | ~$0.03-0.05 |
| **합계** | **~$0.04/건** (~50원) |

---

## 10. 배포 계획

### 10.1 배포 스크립트: `deploy/deploy_integrated.py`

기존 Layer 배포 스크립트(`deploy_layer*.py`)와 동일한 패턴:

```
1. 소스 파일 → deploy/chest_modal_orchestrator/ 복사 (필요시)
2. ECR 리포지토리 생성: chest-modal-integrated
3. Docker 빌드 + ECR 푸시
4. Lambda 함수 생성/업데이트
5. Function URL 생성 + 테스트 호출
```

### 10.2 작업 순서 (13단계)

| # | 작업 | 예상 시간 | 의존성 |
|---|------|----------|--------|
| 1 | 폴더 구조 생성 (`deploy/chest_modal_orchestrator/`) | 1분 | - |
| 2 | config.py — 엔드포인트 URL + 기본값 | 3분 | - |
| 3 | input_parser.py — 유연한 입력 파싱 | 5분 | - |
| 4 | output_formatter.py — 출력 형태 변환 | 3분 | - |
| 5 | layer_client.py — HTTP 호출 클라이언트 | 5분 | 2 |
| 6 | orchestrator.py — 파이프라인 오케스트레이션 | 10분 | 2,3,4,5 |
| 7 | lambda_function.py — Lambda 핸들러 | 5분 | 6 |
| 8 | test_cases.py — 5개 테스트 데이터 | 3분 | - |
| 9 | index.html — 테스트 웹페이지 (방법 B) | 20분 | 8 |
| 10 | Dockerfile + requirements.txt | 2분 | - |
| 11 | 샘플 이미지 5장 S3 복사 | 3분 | - |
| 12 | deploy_integrated.py — 배포 자동화 | 5분 | 10 |
| 13 | 배포 + 5개 시나리오 테스트 | 15분 | 1~12 |

---

## 11. 리스크 및 대응

| 리스크 | 영향 | 대응 |
|--------|------|------|
| 통합 Lambda 타임아웃 (300s) 초과 | Layer 6 Bedrock이 Cold Start + 응답 합쳐 2분 이상 | 충분한 타임아웃 설정, 필요시 600s |
| 기존 Layer Cold Start 연쇄 | 전체 80초+ 소요 | 테스트 전 각 Layer 1회 warm-up 호출 |
| Layer 간 데이터 변환 오류 | Layer 3가 잘못된 입력으로 오작동 | API 문서 기반 엄격한 변환 + 단위 테스트 |
| 테스트 페이지 CORS 문제 | 브라우저에서 Lambda 직접 호출 시 | Lambda Function URL은 기본 CORS 허용 확인 |
| 샘플 이미지 S3 접근 권한 | 테스트 케이스 이미지 로드 실패 | presigned URL 또는 public read 설정 |

---

## 12. 완료 기준

- [ ] 통합 오케스트레이터 Lambda 배포 + Function URL 활성
- [ ] 5개 테스트 케이스 모두 정상 완료 (기대 Risk Level 일치)
- [ ] 테스트 페이지에서 실시간 파이프라인 진행 표시 동작
- [ ] 소견서 (구조화 8섹션 + 서술형) 정상 렌더링
- [ ] 에러 처리: 단일 Layer 실패 시 나머지 계속 진행 확인
