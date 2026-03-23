# Dr. AI Radiologist - API Reference

> MIMIC-CXR 기반 응급실 AI 흉부 X-Ray 분석 시스템
> 각 레이어는 독립 Lambda Function URL로 운영됨

---

## 공통 사항

### 인증
- 모든 엔드포인트는 **인증 없이 공개 접근** 가능 (AuthType: NONE)

### 요청 형식
- **GET** → 해당 레이어의 테스트 페이지 (HTML)
- **POST** → JSON API

### 이미지 입력 방식 (모든 레이어 공통)

| 방식 | 필드 | 설명 |
|---|---|---|
| Base64 | `image_base64` | `data:image/jpeg;base64,...` 또는 순수 base64 문자열 |
| S3 경로 | `s3_key` + `bucket`(선택) | S3 오브젝트 키. bucket 미지정 시 기본 작업 버킷 사용 |

### 공통 액션

| 액션 | 설명 |
|---|---|
| `list_samples` | 샘플 이미지 목록 + 프리사인 URL 반환 |

```json
// 샘플 목록 요청
POST {ENDPOINT_URL}
Content-Type: application/json

{"action": "list_samples"}
```

```json
// 샘플 목록 응답
{
  "samples": [
    {
      "filename": "example.jpg",
      "s3_key": "web/test-layer1/samples/example.jpg",
      "url": "https://s3.presigned-url..."
    }
  ]
}
```

### Cold Start
- 첫 요청 시 모델 S3 다운로드 + 로드로 **1~2분** 소요
- 이후 warm start 시 **~1초**

---

## Layer 1: Lung Segmentation

### Endpoint
```
https://jwhljyevn3hm44nhvs5zcdstmi0tmuvi.lambda-url.ap-northeast-2.on.aws/
```

### 모델
- **아키텍처**: HuggingFace AutoModel (chest-x-ray-basic)
- **기능**: 좌/우 폐 + 심장 세그멘테이션, CTR(심흉비) 측정, 해부학적 계측

### 요청

```json
POST https://jwhljyevn3hm44nhvs5zcdstmi0tmuvi.lambda-url.ap-northeast-2.on.aws/
Content-Type: application/json

{
  "image_base64": "data:image/jpeg;base64,/9j/4AAQ..."
}
```

또는 S3 경로:
```json
{
  "s3_key": "web/test-layer1/samples/example.jpg"
}
```

### 응답

```json
{
  "measurements": {
    "ctr": 0.4823,
    "ctr_status": "normal",          // "normal" | "cardiomegaly" (>=0.50) | "severe_cardiomegaly" (>=0.60)
    "heart_width_px": 245,
    "thorax_width_px": 508,
    "right_lung_area_px": 52341,
    "left_lung_area_px": 48923,
    "heart_area_px": 31245,
    "total_lung_area_px": 101264,
    "lung_area_ratio": 0.9347,       // left/right 비율
    "mediastinum": {
      "width_px": 82,
      "measurement_y_level": 145,
      "x_left": 213,
      "x_right": 295,
      "status": "normal"             // "normal" | "unmeasurable"
    },
    "trachea": {
      "mediastinum_center_x": 254.3,
      "thorax_center_x": 256.0,
      "deviation_px": -1.7,
      "deviation_ratio": -0.0033,
      "midline": true,               // |ratio| < 0.03
      "deviation_direction": "none",  // "none" | "left" | "right"
      "alert": false                  // true if |ratio| >= 0.08
    },
    "cp_angle": {
      "right": {
        "point": [45, 480],
        "angle_degrees": 42.3,
        "status": "sharp"            // "sharp" | "blunted" (>70deg, 흉수 의심) | "unmeasurable"
      },
      "left": {
        "point": [467, 475],
        "angle_degrees": 38.7,
        "status": "sharp"
      }
    },
    "diaphragm": {
      "right_dome_point": [180, 470],
      "left_dome_point": [340, 465],
      "height_diff_px": 5,
      "height_diff_ratio": 0.0098,
      "status": "normal",            // "normal" | "elevated_right" | "elevated_left" (>=3%)
      "elevated_side": null
    }
  },
  "view": "PA",                      // "AP" | "PA" | "lateral"
  "age_pred": 62.3,
  "sex_pred": "M",                   // "M" | "F"
  "mask_base64": "iVBORw0KGgo...",   // RGBA PNG (우폐:파랑, 좌폐:초록, 심장:빨강)
  "original_size": [512, 512],       // [height, width]
  "processing_time": 1.23
}
```

### 측정값 해석

| 지표 | 정상 범위 | 이상 | 임상 의미 |
|---|---|---|---|
| CTR | < 0.50 | >= 0.50 | 심비대 (Cardiomegaly) |
| CP Angle | < 70도 (sharp) | > 70도 (blunted) | 흉수 (Pleural Effusion) 초기 징후 |
| Trachea Deviation | < 3% | >= 3% | 종격동 편위 (긴장성 기흉 등) |
| Diaphragm Diff | < 3% | >= 3% | 횡격막 거상 (무기폐, 횡격막 마비) |

---

## Layer 2: 14-Disease Detection

### Endpoint
```
https://pk67s3qrp3b3xluqkcp6neqly40kduol.lambda-url.ap-northeast-2.on.aws/
```

### 모델
- **아키텍처**: DenseNet-121 (ImageNet pretrained -> MIMIC-CXR PA 94K Fine-tuned)
- **기능**: 14개 질환 Multi-label Classification
- **성능**: Mean AUROC 0.701 (998장 테스트셋)

### 14개 질환 목록

| # | 질환 | 설명 | Test AUROC |
|---|---|---|---|
| 1 | Atelectasis | 무기폐 | 0.724 |
| 2 | Cardiomegaly | 심비대 | 0.726 |
| 3 | Consolidation | 경화 | 0.688 |
| 4 | Edema | 부종 | 0.854 |
| 5 | Enlarged Cardiomediastinum | 심종격동 확대 | 0.605 |
| 6 | Fracture | 골절 | 0.612 |
| 7 | Lung Lesion | 폐 병변 | 0.570 |
| 8 | Lung Opacity | 폐 혼탁 | 0.635 |
| 9 | No Finding | 정상 소견 | 0.736 |
| 10 | Pleural Effusion | 흉수 | 0.832 |
| 11 | Pleural Other | 기타 흉막 이상 | 0.709 |
| 12 | Pneumonia | 폐렴 | 0.627 |
| 13 | Pneumothorax | 기흉 | 0.759 |
| 14 | Support Devices | 의료기기 | 0.741 |

### 요청

```json
POST https://pk67s3qrp3b3xluqkcp6neqly40kduol.lambda-url.ap-northeast-2.on.aws/
Content-Type: application/json

{
  "image_base64": "data:image/jpeg;base64,/9j/4AAQ..."
}
```

또는 S3 경로:
```json
{
  "s3_key": "web/test-layer2/samples/example.jpg"
}
```

### 응답

```json
{
  "findings": [
    {
      "disease": "Pleural Effusion",
      "probability": 0.8732,
      "positive": true
    },
    {
      "disease": "Edema",
      "probability": 0.7124,
      "positive": true
    },
    {
      "disease": "No Finding",
      "probability": 0.1203,
      "positive": false
    }
  ],
  "positive_findings": ["Pleural Effusion", "Edema"],
  "negative_findings": ["Atelectasis", "Cardiomegaly", "..."],
  "probabilities": {
    "Atelectasis": 0.3241,
    "Cardiomegaly": 0.1892,
    "Pleural Effusion": 0.8732,
    "...": "..."
  },
  "num_positive": 2,
  "summary": "2 abnormalities: Pleural Effusion, Edema",
  "processing_time": 0.95
}
```

### 판정 기준
- **threshold: 0.5** — probability >= 0.5이면 positive (양성)
- `findings` 배열은 probability 내림차순 정렬
- `summary`: positive가 없거나 No Finding만 있으면 "No significant findings"

---

## Layer 3: Clinical Logic Engine

### Endpoint
```
https://ihq6gjldxbulfke5xd2xexnoqe0vyrxt.lambda-url.ap-northeast-2.on.aws/
```

### 개요
- **GPU 불필요** — 순수 Python Rule Engine
- **기능**: Layer 1/2 출력을 받아 14개 질환별 임상 판독 로직 실행 + 교차검증 + 감별진단 + 위험도 분류
- **이미지 크기**: ~200MB (Layer 1/2의 1/7)
- **Cold start**: ~2초 | **Warm start**: <0.01초
- **메모리**: 256MB | **타임아웃**: 30초

### 액션 목록

| 액션 | 설명 |
|---|---|
| `list_scenarios` | 내장 시나리오 목록 반환 |
| `scenario` | 내장 mock 시나리오 실행 (Layer 1/2 결과 임의 생성됨) |
| `random` | Layer 1/2 출력을 랜덤 생성하여 엔진 검증 |
| `custom` | 사용자가 Layer 1/2 출력을 직접 전달 |

### 요청 — 시나리오 목록

```json
POST {ENDPOINT_URL}
Content-Type: application/json

{"action": "list_scenarios"}
```

```json
// 응답
{
  "scenarios": {
    "chf": {"name": "심부전 (CHF)", "description": "72세 남성, 심비대+양측흉수+폐부종"},
    "pneumonia": {"name": "폐렴 (Pneumonia)", "description": "67세 남성, 좌하엽경화+발열+기침"},
    "tension_pneumo": {"name": "긴장성 기흉", "description": "25세 남성, 교통사고 후 좌측기흉, 기관 우측 편위"},
    "normal": {"name": "정상", "description": "모든 지표 정상 범위"}
  }
}
```

### 요청 — 시나리오 실행

```json
POST {ENDPOINT_URL}
Content-Type: application/json

{
  "action": "scenario",
  "scenario": "chf"
}
```

### 요청 — 랜덤 생성

```json
POST {ENDPOINT_URL}
Content-Type: application/json

{"action": "random"}
```

### 요청 — Custom (Layer 1/2 출력 직접 전달)

```json
POST {ENDPOINT_URL}
Content-Type: application/json

{
  "action": "custom",
  "anatomy": {
    "ctr": 0.62,
    "ctr_status": "severe",
    "heart_width_px": 1500,
    "thorax_width_px": 2400,
    "heart_area_px2": 1200000,
    "right_lung_area_px2": 800000,
    "left_lung_area_px2": 700000,
    "lung_area_ratio": 0.875,
    "total_lung_area_px2": 1500000,
    "mediastinum_status": "normal",
    "trachea_midline": true,
    "right_cp_status": "blunted",
    "right_cp_angle_degrees": 95,
    "left_cp_status": "blunted",
    "left_cp_angle_degrees": 88,
    "diaphragm_status": "normal",
    "view": "PA",
    "predicted_age": 72,
    "predicted_sex": "M"
  },
  "densenet": {
    "Cardiomegaly": 0.92,
    "Edema": 0.85,
    "Pleural_Effusion": 0.78
  },
  "yolo_detections": [
    {
      "class_name": "Consolidation",
      "bbox": [120, 340, 320, 520],
      "confidence": 0.84,
      "lobe": "LLL"
    }
  ],
  "patient_info": {
    "age": 72,
    "sex": "M",
    "chief_complaint": "호흡곤란, 하지부종",
    "temperature": 37.2
  },
  "prior_results": [
    {"modal": "ecg", "summary": "심방세동", "findings": {}},
    {"modal": "lab", "summary": "염증 소견", "findings": {"WBC": 15000, "CRP": 12.5}}
  ]
}
```

### 응답 구조

```json
{
  "mode": "scenario:chf",
  "input_summary": {
    "anatomy": {
      "ctr": 0.62,
      "ctr_status": "severe",
      "view": "PA",
      "lung_area_ratio": 0.875,
      "trachea_midline": true,
      "right_cp_status": "blunted",
      "left_cp_status": "blunted",
      "diaphragm_status": "normal"
    },
    "densenet_high_probs": {
      "Cardiomegaly": 0.92,
      "Edema": 0.85,
      "Pleural_Effusion": 0.78
    },
    "yolo_count": 0,
    "has_patient_info": true,
    "prior_results_count": 1
  },
  "input_data": { "...전체 입력 JSON..." },
  "result": {
    "findings": {
      "Cardiomegaly": {
        "finding": "Cardiomegaly",
        "detected": true,
        "confidence": "high",
        "evidence": [
          "CTR 0.6200 (정상 <0.50)",
          "DenseNet Cardiomegaly: 0.92"
        ],
        "quantitative": {"ctr": 0.62, "heart_width_px": 1500, "thorax_width_px": 2400},
        "location": null,
        "severity": "severe",
        "recommendation": "심초음파 추적 권장",
        "alert": false
      },
      "Pleural_Effusion": { "..." },
      "Pneumothorax": { "..." },
      "...13개 질환...": { "..." },
      "No_Finding": {
        "finding": "No_Finding",
        "detected": false,
        "confidence": "high",
        "evidence": ["3개 항목 실패: heart, no_other_findings, ..."],
        "quantitative": {"checklist": {"heart": false, "...": "..."}, "passed": 7, "failed": 3}
      }
    },
    "cross_validation": {
      "Cardiomegaly": {
        "finding": "Cardiomegaly",
        "sources": {"densenet": true, "yolo": false, "clinical_logic": true},
        "agreement": "2/3",
        "confidence": "medium",
        "flag": null
      },
      "...": "..."
    },
    "differential_diagnosis": [
      {
        "diagnosis": "울혈성 심부전 (CHF)",
        "probability": "high",
        "matched_findings": ["Cardiomegaly", "Pleural_Effusion", "Edema"],
        "matched_flags": ["ctr_elevated"],
        "alert": false
      }
    ],
    "risk_level": "routine",
    "alert_flags": [],
    "detected_count": 3
  },
  "processing_time_sec": 0.0002
}
```

### 14개 질환별 판정 로직 요약

| 질환 | 주요 Rule | 핵심 지표 |
|---|---|---|
| Cardiomegaly | CTR > 0.50 | CTR, DenseNet |
| Pleural_Effusion | CP angle blunted | CP angle 좌/우, 추정량 |
| Pneumothorax | DenseNet + 폐면적비 | tension 여부, 기관 편위 |
| Consolidation | DenseNet + YOLO bbox | Silhouette sign, 폐엽 매핑 |
| Edema | DenseNet + 양측대칭 | symmetry score, butterfly, CTR 교차 |
| Enlarged_CM | 종격동 너비 비율 | mediastinum_width / thorax_width |
| Atelectasis | 폐면적비 < 0.80 + 종격동 동측 이동 | 면적 감소%, 종격동 shift 방향 |
| Fracture | DenseNet + YOLO | 동반손상(기흉, 혈흉) 자동 교차 |
| Lung_Lesion | YOLO bbox 장경 | Fleischner Society 추천 |
| Lung_Opacity | 다른 Rule 결과 종합 | primary_cause 감별 |
| No_Finding | 8영역 체크리스트 전부 통과 | checklist 항목별 pass/fail |
| Pleural_Other | DenseNet (낮은 threshold) | 석면 노출 교차 |
| Pneumonia | 5단계 임상정보 교차 | 경화+발열+기침+WBC+ECG |
| Support_Devices | YOLO bbox + 팁 위치 | ETT 팁~carina 거리 |

### 교차 검증 (Cross-Validation)

3개 소스의 일치도로 confidence 결정:

| 일치 수 | confidence | 의미 |
|---|---|---|
| 3/3 | high | DenseNet + YOLO + Logic 모두 동의 |
| 2/3 | medium | 2개 소스 동의 |
| 1/3 | low | 1개만 양성 → "의사 확인 필요" flag |
| 0/3 | none | 모두 음성 |

### 감별 진단 패턴

| 패턴 | 진단 | 확률 |
|---|---|---|
| Cardiomegaly + Pleural_Effusion + Edema | 울혈성 심부전 (CHF) | high |
| Consolidation + fever + cough | 감염성 폐렴 | high |
| Fracture + Pneumothorax | 외상성 기흉 | high |
| Pneumothorax + trachea 반대측 편위 | **긴장성 기흉 (TENSION)** | critical |
| Consolidation + CTR 상승 + 양측대칭 | 심인성 폐부종 | high |
| Lung_Opacity + 면적감소 + 동측 종격동 이동 | 무기폐 | high |

### 위험도 분류

| risk_level | 조건 | 의미 |
|---|---|---|
| `critical` | alert=true인 소견이 1개 이상 | 응급 — 즉시 의사 확인 |
| `routine` | 모든 소견 alert=false | 일반 판독 |

### Layer 3 인프라

| 항목 | 값 |
|---|---|
| 메모리 | 256 MB |
| 타임아웃 | 30초 |
| /tmp 스토리지 | 512 MB |
| ECR | layer3-clinical-logic |
| 이미지 크기 | ~200MB |
| 호출 비용 | ~$0.0001 (0.1원) |

---

## Layer 6: Bedrock Report Generator

### Endpoint
```
https://ofii46d5p6446ceahn3ucb5f2a0xcvej.lambda-url.ap-northeast-2.on.aws/
```

### 개요
- **모델**: Bedrock Claude Sonnet 4.6 (`global.anthropic.claude-sonnet-4-6`)
- **기능**: Layer 1~5 결과를 종합하여 구조화 소견서 + 서술형 판독문 자동 생성
- **언어**: 한국어 / 영어 이중언어 지원
- **GPU 불필요** — 순수 Python + boto3 (Bedrock API 호출)
- **Cold start**: ~2초 | **이미지 크기**: ~150MB
- **메모리**: 256MB | **타임아웃**: 120초

### 액션 목록

| 액션 | 설명 |
|---|---|
| `list_scenarios` | 내장 시나리오 목록 반환 |
| `scenario` | 내장 mock 시나리오로 Bedrock 호출 → 소견서 생성 |
| `generate` | 사용자가 Layer 1~5 출력을 직접 전달 → 소견서 생성 |

### 요청 — 시나리오 목록

```json
POST {ENDPOINT_URL}
Content-Type: application/json

{"action": "list_scenarios"}
```

```json
// 응답
{
  "scenarios": {
    "chf": {"name": "심부전 (CHF)", "risk": "URGENT"},
    "pneumonia": {"name": "폐렴 (Pneumonia)", "risk": "URGENT"},
    "tension_pneumo": {"name": "긴장성 기흉", "risk": "CRITICAL"},
    "normal": {"name": "정상 (Normal)", "risk": "ROUTINE"}
  }
}
```

### 요청 — 시나리오 실행

```json
POST {ENDPOINT_URL}
Content-Type: application/json

{
  "action": "scenario",
  "scenario": "chf",
  "report_language": "ko"
}
```

### 요청 — Custom (Layer 1~5 출력 직접 전달)

```json
POST {ENDPOINT_URL}
Content-Type: application/json

{
  "action": "generate",
  "report_language": "ko",
  "patient_info": {
    "age": 72, "sex": "M",
    "chief_complaint": "호흡곤란, 하지부종",
    "temperature": 37.2, "heart_rate": 105,
    "blood_pressure": "145/90", "spo2": 91, "respiratory_rate": 24
  },
  "anatomy_measurements": {
    "ctr": 0.62, "ctr_status": "severe",
    "heart_width_px": 1500, "thorax_width_px": 2400,
    "lung_area_ratio": 0.875,
    "trachea_midline": true,
    "right_cp_status": "blunted", "right_cp_angle_degrees": 95,
    "left_cp_status": "blunted", "left_cp_angle_degrees": 88,
    "view": "PA"
  },
  "densenet_predictions": {
    "Cardiomegaly": 0.92, "Edema": 0.85, "Pleural Effusion": 0.78
  },
  "yolo_detections": [],
  "clinical_logic": {
    "risk_level": "URGENT",
    "detected_count": 3,
    "findings": {},
    "differential_diagnosis": [],
    "alert_flags": []
  },
  "cross_validation_summary": {},
  "prior_results": [
    {"modal": "ecg", "summary": "심방세동"}
  ]
}
```

### 응답 구조

```json
{
  "mode": "scenario:chf",
  "scenario_name": "심부전 (CHF)",
  "report": {
    "request_id": "test_chf_001",
    "report": {
      "structured": {
        "heart": "심흉곽비(CTR) 0.62로 심한 심비대...",
        "pleura": "양측 늑횡격막각(CP angle) 둔화...",
        "lungs": "양측 폐야에 혈관 음영 증가...",
        "mediastinum": "종격동 폭 정상 범위...",
        "bones": "급성 골절 소견 없음",
        "devices": "삽입 기구 없음",
        "impression": "⚠️ URGENT\n1. 심한 심비대...",
        "recommendation": "1. 즉각적 산소 공급...\n2. 심초음파 시행..."
      },
      "narrative": "⚠️ URGENT 판독\n\n72세 남성으로...",
      "summary": "72세 남성에서 심비대(CTR 0.62), 양측 흉수...",
      "risk_level": "URGENT",
      "alert_flags": []
    },
    "suggested_next_actions": [
      {
        "action": "lab",
        "description": "혈액 검사",
        "tests": ["BNP", "NT-proBNP", "전해질", "BUN/Cr"]
      },
      {
        "action": "imaging",
        "description": "심초음파",
        "modal": "Echocardiography"
      }
    ],
    "metadata": {
      "model_used": "global.anthropic.claude-sonnet-4-6",
      "input_tokens": 1800,
      "output_tokens": 2800,
      "latency_ms": 40000,
      "rag_used": false,
      "report_language": "ko"
    }
  }
}
```

### 소견서 구조

| 필드 | 설명 |
|---|---|
| `structured.heart` | 심장 소견 (CTR, 심비대 여부) |
| `structured.pleura` | 흉막 소견 (CP angle, 흉수) |
| `structured.lungs` | 폐 소견 (경화, 부종, 결절) |
| `structured.mediastinum` | 종격동 소견 |
| `structured.bones` | 골격 소견 |
| `structured.devices` | 삽입 기구 소견 |
| `structured.impression` | **종합소견** + 감별진단 |
| `structured.recommendation` | 권고사항 (추가 검사, 치료) |
| `narrative` | 서술형 판독문 (완전한 문장) |
| `summary` | 1~2문장 요약 |
| `suggested_next_actions` | 권고 후속 조치 목록 |

### 성능 벤치마크

| 시나리오 | Risk | Input Tokens | Output Tokens | Latency |
|---|---|---|---|---|
| CHF | URGENT | ~1800 | ~2800 | ~40s |
| Pneumonia | URGENT | ~1815 | ~2790 | ~40s |
| Tension Pneumo | CRITICAL | ~1764 | ~2578 | ~39s |
| Normal (KO) | ROUTINE | ~1490 | ~1457 | ~20s |
| Normal (EN) | ROUTINE | ~1030 | ~900 | ~14s |

### Layer 6 인프라

| 항목 | 값 |
|---|---|
| 메모리 | 256 MB |
| 타임아웃 | 120초 |
| /tmp 스토리지 | 512 MB |
| ECR | layer6-bedrock-report |
| 이미지 크기 | ~150MB |
| 호출 비용 | Bedrock: ~$0.03-0.05/건 + Lambda: ~$0.0001 |

---

## Layer 5 — RAG (유사 판독문 검색)

> **엔드포인트:** `https://rn32hjcarfgqhopm266iidoeey0lkbkt.lambda-url.ap-northeast-2.on.aws/`

MIMIC-IV 판독문 124K건에서 유사 케이스를 검색하여 참고 판독문을 제공합니다.
bge-small-en-v1.5 임베딩 + FAISS IndexIVFFlat 기반.

### 액션

| 액션 | 설명 |
|---|---|
| `health` | 서비스 상태 확인 (인덱스 로드 여부, 벡터 수) |
| `scenario` | 4개 사전 정의 시나리오 중 하나로 검색 (chf, pneumonia, tension_pneumo, normal) |
| `list_scenarios` | 사용 가능한 시나리오 목록 반환 |
| `custom` | Layer 3 Clinical Logic 결과를 직접 전달하여 검색 |

### 요청 예시

```json
// scenario 모드
{
  "action": "scenario",
  "scenario": "chf",
  "top_k": 5
}

// custom 모드 — Layer 3 결과 전달
{
  "action": "custom",
  "clinical_logic": {
    "risk_level": "URGENT",
    "findings": {
      "Cardiomegaly": {"detected": true, "severity": "severe"},
      "Pleural_Effusion": {"detected": true, "severity": "moderate"}
    }
  },
  "top_k": 5
}
```

### 응답 구조

```json
{
  "action": "scenario",
  "scenario": "chf",
  "query_text": "cardiomegaly severe enlarged heart pleural effusion bilateral...",
  "results": [
    {
      "rank": 1,
      "similarity": 0.93,
      "impression": "1. Moderate cardiomegaly with bilateral pleural effusions...",
      "findings": "The heart is moderately enlarged...",
      "indication": "Shortness of breath",
      "metadata": {
        "note_id": "12345678",
        "subject_id": "10000032"
      }
    }
  ],
  "count": 5,
  "index_size": 123974,
  "model": "BAAI/bge-small-en-v1.5"
}
```

### 응답 필드 설명

| 필드 | 설명 |
|---|---|
| `query_text` | Layer 3 결과에서 생성된 검색 쿼리 (영문) |
| `results[].similarity` | 코사인 유사도 (0~1, 높을수록 유사) |
| `results[].impression` | IMPRESSION 섹션 (핵심 소견 요약) |
| `results[].findings` | FINDINGS 섹션 (상세 판독) |
| `results[].indication` | INDICATION 섹션 (검사 사유) |
| `index_size` | 검색 인덱스 벡터 수 (123,974) |

### 성능 벤치마크

| 시나리오 | 유사도 | Cold Start | Warm |
|---|---|---|---|
| CHF | 0.93 | ~10초 | ~60ms |
| Pneumonia | 0.92 | ~10초 | ~60ms |
| Tension PTX | 0.88 | ~10초 | ~60ms |
| Normal | 0.89 | ~10초 | ~60ms |

### Layer 5 인프라

| 항목 | 값 |
|---|---|
| 메모리 | 1,024 MB |
| 타임아웃 | 120초 |
| /tmp 스토리지 | 1,024 MB |
| ECR | layer5-rag |
| 이미지 크기 | ~1.37GB |
| 임베딩 모델 | BAAI/bge-small-en-v1.5 (FastEmbed ONNX) |
| 벡터 차원 | 384d |
| 인덱스 크기 | 183MB (IndexIVFFlat, nlist=352) |
| 메타데이터 | 176MB (123,974건) |
| 호출 비용 | ~$0.0001/건 |

---

## 사용 예시 (Python)

```python
import requests
import base64

# 엔드포인트
LAYER1_URL = "https://jwhljyevn3hm44nhvs5zcdstmi0tmuvi.lambda-url.ap-northeast-2.on.aws/"
LAYER2_URL = "https://pk67s3qrp3b3xluqkcp6neqly40kduol.lambda-url.ap-northeast-2.on.aws/"
LAYER3_URL = "https://ihq6gjldxbulfke5xd2xexnoqe0vyrxt.lambda-url.ap-northeast-2.on.aws/"
LAYER5_URL = "https://rn32hjcarfgqhopm266iidoeey0lkbkt.lambda-url.ap-northeast-2.on.aws/"
LAYER6_URL = "https://ofii46d5p6446ceahn3ucb5f2a0xcvej.lambda-url.ap-northeast-2.on.aws/"

# 이미지 읽기
with open("chest_xray.jpg", "rb") as f:
    img_b64 = base64.b64encode(f.read()).decode()

# Layer 1 호출
resp1 = requests.post(LAYER1_URL, json={"image_base64": img_b64})
seg = resp1.json()
print(f"CTR: {seg['measurements']['ctr']} ({seg['measurements']['ctr_status']})")
print(f"View: {seg['view']}, Age: {seg['age_pred']}, Sex: {seg['sex_pred']}")

# Layer 2 호출
resp2 = requests.post(LAYER2_URL, json={"image_base64": img_b64})
det = resp2.json()
print(f"Summary: {det['summary']}")
for f in det['findings']:
    if f['positive']:
        print(f"  [POS] {f['disease']}: {f['probability']:.1%}")

# Layer 3 호출 — Layer 1/2 결과를 조합하여 전달
resp3 = requests.post(LAYER3_URL, json={
    "action": "custom",
    "anatomy": seg['measurements'] | {
        "view": seg['view'],
        "predicted_age": seg['age_pred'],
        "predicted_sex": seg['sex_pred'],
        # Layer 1 하위 측정값 평탄화
        "mediastinum_status": seg['measurements']['mediastinum']['status'],
        "mediastinum_width_px": seg['measurements']['mediastinum']['width_px'],
        "trachea_midline": seg['measurements']['trachea']['midline'],
        "trachea_deviation_direction": seg['measurements']['trachea']['deviation_direction'],
        "trachea_deviation_ratio": seg['measurements']['trachea']['deviation_ratio'],
        "right_cp_status": seg['measurements']['cp_angle']['right']['status'],
        "right_cp_angle_degrees": seg['measurements']['cp_angle']['right']['angle_degrees'],
        "left_cp_status": seg['measurements']['cp_angle']['left']['status'],
        "left_cp_angle_degrees": seg['measurements']['cp_angle']['left']['angle_degrees'],
        "diaphragm_status": seg['measurements']['diaphragm']['status'],
    },
    "densenet": {d.replace(' ', '_'): p for d, p in det['probabilities'].items()},
})
logic = resp3.json()
r = logic['result']
print(f"Risk: {r['risk_level']}, Detected: {r['detected_count']}")
for name, f in r['findings'].items():
    if f['detected'] and name != 'No_Finding':
        print(f"  [{f['severity']}] {name}: {f['evidence'][0]}")
if r['differential_diagnosis']:
    print(f"감별진단: {[d['diagnosis'] for d in r['differential_diagnosis']]}")
```

```python
# Layer 3 단독 사용 — 시나리오 테스트
resp = requests.post(LAYER3_URL, json={"action": "scenario", "scenario": "tension_pneumo"})
data = resp.json()
print(f"Risk: {data['result']['risk_level']}")  # critical
print(f"Alerts: {data['result']['alert_flags']}")  # ['Pneumothorax']

# Layer 3 — 랜덤 생성으로 엔진 검증
resp = requests.post(LAYER3_URL, json={"action": "random"})
data = resp.json()
print(f"Detected: {data['result']['detected_count']}")
```

```javascript
// JavaScript (브라우저) — Layer 1 → Layer 2 → Layer 3 파이프라인
async function analyzeXray(file) {
  const reader = new FileReader();
  const b64 = await new Promise(resolve => {
    reader.onload = e => resolve(e.target.result);
    reader.readAsDataURL(file);
  });

  // Layer 1
  const seg = await (await fetch(LAYER1_URL, {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({image_base64: b64})
  })).json();

  // Layer 2
  const det = await (await fetch(LAYER2_URL, {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({image_base64: b64})
  })).json();

  // Layer 3 — 조합
  const logic = await (await fetch(LAYER3_URL, {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({action: "custom", anatomy: seg.measurements, densenet: det.probabilities})
  })).json();

  return {seg, det, logic};
}
```

---

## Integrated Pipeline (통합 오케스트레이터)

### Endpoint
```
https://emsptg6o6iwonhhbxyxvasm7ga0yjluu.lambda-url.ap-northeast-2.on.aws/
```

### 개요
- **기능**: 6개 Layer를 하나의 파이프라인으로 통합. CXR 이미지 1장 → 최종 소견서까지 원클릭 실행
- **실행 순서**: Layer 1+2 병렬 → Layer 3 → Layer 5 → Layer 6
- **GPU 불필요** — 각 Layer Lambda를 HTTP로 호출하는 오케스트레이터
- **메모리**: 512MB | **타임아웃**: 300초 | **이미지 크기**: ~760MB

### 액션 목록

| 액션 | 설명 |
|---|---|
| `run` | 전체 파이프라인 실행 (이미지 base64 또는 S3 key 입력) |
| `list_test_cases` | 5개 내장 테스트 케이스 목록 |
| `test_case` | 내장 테스트 케이스로 파이프라인 실행 |
| `presigned_url` | S3 이미지의 임시 접근 URL 생성 (300초 유효) |

### 요청 — 전체 파이프라인 실행

```json
// Base64 이미지로 실행
{
  "action": "run",
  "image_base64": "data:image/jpeg;base64,/9j/4AAQ...",
  "patient_info": {
    "patient_id": "P001", "age": 72, "sex": "M",
    "chief_complaint": "호흡곤란",
    "vitals": {"temperature": 36.8, "heart_rate": 98, "spo2": 92}
  },
  "prior_results": [{"modal": "ecg", "summary": "동성빈맥"}],
  "options": {"report_language": "ko", "top_k": 3}
}

// S3 키로 실행
{
  "action": "run",
  "s3_key": "web/test-integrated/samples/chf_sample.jpg",
  "patient_info": {...},
  "options": {}
}
```

### 요청 — 테스트 케이스

```json
{"action": "test_case", "test_case": "chf"}
```

5개 테스트 케이스: `chf`, `pneumonia`, `tension_pneumothorax`, `normal`, `multi_finding`

### 요청 — Presigned URL

```json
{"action": "presigned_url", "s3_key": "web/test-integrated/samples/chf_sample.jpg"}
```

```json
// 응답
{"url": "https://bucket.s3.amazonaws.com/...?X-Amz-Signature=...", "s3_key": "..."}
```

### 응답 — 파이프라인 실행 결과

```json
{
  "layer1": {"measurements": {...}, "mask_base64": "...", "original_size": [512,512], ...},
  "layer2": {"findings": [...], "probabilities": {...}, "summary": "..."},
  "layer3": {"result": {"findings": {...}, "risk_level": "URGENT", ...}},
  "layer5": {"rag_evidence": [...], "total_results": 3},
  "layer6": {"report": {"structured": {...}, "narrative": "...", "summary": "..."}},
  "total_time": 63.9,
  "test_case": {"id": "chf", "name": "심부전 (CHF)", "expected_risk": "URGENT"}
}
```

### E2E 성능

| Layer | 시간 | 비고 |
|---|---|---|
| Layer 1+2 (병렬) | ~23s | 이미지 분석 (Cold 시 ~2분) |
| Layer 3 | ~0ms | Rule-Based |
| Layer 5 | ~80ms | FAISS 검색 |
| Layer 6 | ~39s | Bedrock API |
| **Total** | **~63s** | Warm 기준 |

### Integrated 인프라

| 항목 | 값 |
|---|---|
| 메모리 | 512 MB |
| 타임아웃 | 300초 |
| /tmp | 512 MB |
| ECR | chest-modal-integrated |
| 이미지 크기 | ~760MB |
| Cold Start | ~3초 |
| 호출 비용 | ~$0.04/건 (주로 대기 시간) |

---

## 인프라 정보

| 항목 | Layer 1 | Layer 2 | Layer 3 | Layer 5 | Layer 6 | **Integrated** |
|---|---|---|---|---|---|---|
| 리전 | ap-northeast-2 | ap-northeast-2 | ap-northeast-2 | ap-northeast-2 | ap-northeast-2 | ap-northeast-2 |
| 런타임 | Lambda (컨테이너) | Lambda (컨테이너) | Lambda (컨테이너) | Lambda (컨테이너) | Lambda (컨테이너) | Lambda (컨테이너) |
| 메모리 | 3,008 MB | 3,008 MB | 256 MB | 1,024 MB | 256 MB | **512 MB** |
| 타임아웃 | 120초 | 180초 | 30초 | 120초 | 120초 | **300초** |
| /tmp | 2,048 MB | 2,048 MB | 512 MB | 1,024 MB | 512 MB | 512 MB |
| ECR | layer1-segmentation | layer2-detection | layer3-clinical-logic | layer5-rag | layer6-bedrock-report | **chest-modal-integrated** |
| 이미지 크기 | ~2.06GB | ~1.87GB | ~748MB | ~1.25GB | ~150MB | **~760MB** |
| Cold start | ~25초 | ~20초 | ~2초 | ~10초 | ~2초 | **~3초** |
| 호출 비용 | ~$0.002 | ~$0.002 | ~$0.0001 | ~$0.0001 | ~$0.03-0.05 | **~$0.04** |
| GPU | 불필요 | 불필요 | 불필요 | 불필요 | 불필요 | 불필요 |
| 핵심 의존성 | PyTorch + transformers | PyTorch + torchvision | numpy만 | faiss-cpu + fastembed | boto3 (Bedrock) | **requests (HTTP)** |

| 공통 | 값 |
|---|---|
| S3 버킷 | pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an |
| IAM Role | say-2-lambda-bedrock-role |
| 인증 | AuthType: NONE (공개) |

---

## 버전 이력

| 날짜 | 변경 |
|---|---|
| 2026-03-21 | Layer 1 (Lung Segmentation) 배포 |
| 2026-03-22 | Layer 2 (14-Disease Detection) 배포 |
| 2026-03-22 | Layer 2 모델 best_model.pth로 교체 (30 epoch 완료) |
| 2026-03-22 | Layer 3 (Clinical Logic Engine) 구현 — 14개 질환 Rule + 교차검증 + 감별진단 |
| 2026-03-22 | Layer 6 (Bedrock Report) 구현 — Claude Sonnet 4.6 소견서 생성 (KO/EN, 4개 시나리오) |
| 2026-03-23 | Layer 5 (RAG) 구현 — bge-small-en-v1.5 + FAISS, 124K 벡터, 라이브 배포 |
| 2026-03-23 | **Integrated Pipeline** 구현 — 6-Layer 통합 오케스트레이터 + 테스트 페이지 배포 |
| 2026-03-23 | CORS 이중 헤더 버그 수정 (Layer 3/5/6), Presigned URL 지원, 마스크 오버레이 + 측정선 ON/OFF |
