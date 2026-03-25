# chest-svc 파이프라인 스테이지별 입출력 분석

> 테스트 이미지: `096052b7.jpg` (MIMIC-CXR, 3056x2544)
> 환자: 67세 남성, 호흡곤란, 고혈압/당뇨 병력
> 분석일: 2026-03-25

---

## 전체 흐름 요약

```
이미지 (3056x2544 JPG, 1.6MB)
  │
  ├─ Stage 1: UNet 세그멘테이션   0.153s
  ├─ Stage 2a: DenseNet-121       0.044s
  ├─ Stage 2b: YOLOv8             0.413s
  │
  └─ Stage 3: 임상 로직 엔진     0.000s
       │
       ├─ Stage 5: RAG 검색       (미연결)
       │
       └─ Stage 6: Bedrock 소견서  48.7s
                                   ─────
                        총 합계:   ~49.3s
```

---

## Stage 1: UNet 세그멘테이션 (0.153s)

### 입력
- PIL Image (3056, 2544) RGB → 320x320 grayscale로 리사이즈

### 출력
```json
{
  "measurements": {
    "ctr": 0.5204,
    "ctr_status": "cardiomegaly",
    "cp_angle_left": 74.05,
    "cp_angle_right": 87.14,
    "lung_area_ratio": 1.3252,
    "heart_width_px": 96,
    "thorax_width_px": 150,
    "right_lung_area_px": 9780,
    "left_lung_area_px": 12960,
    "heart_area_px": 9331
  },
  "view": "AP",
  "age_pred": null,
  "sex_pred": "M",
  "mask_base64": "(2880 chars — 반투명 RGBA PNG)",
  "original_size": [2544, 3056]
}
```

### 해석
- **CTR 0.5204** — 정상 상한(0.50) 초과 → 경도 심비대
- **CP angle**: 좌 74.05° (정상), 우 87.14° (정상) → 흉수 없음
- **폐면적비 1.325** — 좌우 비대칭 (좌>우 24.5%) → 우측 무기폐 가능
- **AP 촬영** — 심장 확대 과대평가 가능성 있음

---

## Stage 2a: DenseNet-121 14-질환 분류 (0.044s)

### 입력
- PIL Image → 224x224 RGB, ImageNet 정규화 (mean=[0.485,0.456,0.406], std=[0.229,0.224,0.225])

### 출력 (14개 질환 확률)
```
양성 (>0.5):
  Atelectasis:               0.832  !!!
  Edema:                     0.798  !!!
  Pleural_Other:             0.765  !!!
  Fracture:                  0.747  !!!
  Pleural_Effusion:          0.716  !!!
  Lung_Opacity:              0.697  !
  Cardiomegaly:              0.597  !
  Enlarged_Cardiomediastinum: 0.586  !
  Consolidation:             0.573  !
  Pneumonia:                 0.564  !
  Lung_Lesion:               0.515  !

음성 (<0.5):
  Support_Devices:           0.357
  Pneumothorax:              0.294
  No_Finding:                0.131
```

### 해석
- **11개 양성** — 더미 이미지가 아닌 실제 병리 이미지
- 상위: Atelectasis(83%), Edema(80%), Pleural_Other(77%)
- Cardiomegaly 60% — Stage 1의 CTR 0.52와 교차 확인

---

## Stage 2b: YOLOv8 병변 탐지 (0.413s)

### 입력
- PIL Image (3056, 2544) → 1024x1024 letterbox (패딩 + 리사이즈)

### 출력
```json
{
  "detections": [
    {
      "class_name": "Cardiomegaly",
      "confidence": 0.4234,
      "bbox": [1283.87, 2034.73, 2884.99, 2501.56],
      "color": "#ef4444"
    }
  ],
  "image_size": [3056, 2544]
}
```

### 해석
- **1개 탐지**: Cardiomegaly (42.3%) — 원본 좌표계에서 심장 영역 bbox
- bbox 크기: 1601 x 467 px — 이미지 하단 중앙 (심장 위치)
- NMS conf threshold 0.25 이상만 반환

---

## Stage 3: 임상 로직 엔진 (0.0001s)

### 입력
- Stage 1 해부학 측정 (CTR, CP angle, 폐면적비)
- Stage 2a DenseNet 확률 (14개)
- Stage 2b YOLO 탐지 결과
- 환자 정보 (67세 M, 호흡곤란, 고혈압/당뇨)

### 출력
```
검출 질환 (10개, 위험도: CRITICAL):
  1. Cardiomegaly     — CTR 0.52, DenseNet 0.60, YOLO bbox 확인
  2. Pleural_Effusion — DenseNet 0.72
  3. Atelectasis      — 우측 폐면적 24.5% 감소, DenseNet 0.83
  4. Consolidation    — DenseNet 0.57
  5. Edema            — DenseNet 0.80, butterfly 패턴 의심
  6. Enlarged_CM      — DenseNet 0.59, CTR과 연관
  7. Fracture         — DenseNet 0.75, 혈흉 가능
  8. Lung_Lesion      — DenseNet 0.52
  9. Pleural_Other    — DenseNet 0.77
  10. Lung_Opacity    — DenseNet 0.70, 원인: Consolidation

감별진단:
  1. 심인성 폐부종 (high)
  2. 무기폐 (high)
  3. 울혈성 심부전 CHF (high)

교차검증:
  높은 일치: Cardiomegaly (DenseNet + YOLO + CTR 3중 확인)
  중간 일치: 9개 (DenseNet + Logic 2중)
  주의: Pneumonia — 1개 소스만 양성, 의사 확인 필요
```

---

## Stage 5: RAG 유사 케이스 검색 (미연결)

### 전송했을 요청
```json
{
  "url": "http://localhost:8004/search",
  "body": {
    "query": "(clinical summary 텍스트)",
    "modal": "chest",
    "top_k": 3
  }
}
```

### 상태
- rag-svc가 실행 중이 아니어서 **빈 배열** 반환
- 소견서 생성 시 "RAG 시스템 미연결" 메시지로 대체

---

## Stage 6: Bedrock 소견서 생성 (48.7s)

### 모델 정보
- Model ID: `global.anthropic.claude-sonnet-4-6`
- Region: `ap-northeast-2` (서울)
- Temperature: 0.2
- Max tokens: 4096

### 실측 토큰
```
입력: 2,662 tokens (시스템 848자 + 유저 3,437자 = 4,285자)
출력: 3,393 tokens
생성속도: ~70 tokens/s
지연: 48.7초 (= 3393 / 70)
```

### 전송한 System Prompt (848자)

```
당신은 대한민국 응급의학과 전문의이며, 흉부 X선 판독 전문가입니다.
AI 분석 시스템의 정량적 결과와 임상 정보를 종합하여 전문 소견서를 작성합니다.

[판독 원칙]
1. 모든 소견은 정량적 근거(CTR 수치, CP angle 각도, 면적 등)를 포함합니다.
2. 양성 소견을 먼저 기술하고, 음성 소견은 간결하게 "~소견 없음"으로 처리합니다.
3. 감별 진단이 있으면 가장 가능성 높은 진단을 먼저 제시합니다.
4. 이전 검사 결과(ECG, 혈액검사 등)가 있으면 맥락에 반영합니다.
5. 권고 사항은 구체적이고 실행 가능하게 작성합니다.
6. URGENT/CRITICAL 위험도인 경우 소견서 첫 줄에 명시합니다.

[소견서 구조]
- heart, pleura, lungs, mediastinum, bones, devices, impression, recommendation

[RAG 유사 케이스]
현재 RAG 시스템이 연결되지 않았습니다.
일반적인 의학 지식을 바탕으로 소견서를 작성하세요.

[주의]
- AI 내부 수치(DenseNet 확률)는 소견서에 포함하지 마세요.
  CTR, CP angle 같은 임상 수치만 포함합니다.
- 교차 검증 신뢰도가 low인 소견은 "추가 확인 필요"로 표현하세요.
```

### 전송한 User Prompt (3,437자)

```
다음 AI 분석 결과를 바탕으로 흉부 X선 판독 소견서를 작성하세요.

[환자 정보]
나이: 67세
성별: 남성
주소: 호흡곤란

[이전 검사 결과]
이전 검사 없음

[해부학 측정 (Layer 1)]
CTR: 0.5204 (cardiomegaly)
심장폭: 96px, 흉곽폭: 150px
좌/우 폐 면적비: 1.325

[질환 탐지 (Layer 2)]
[DenseNet-121 14-label 확률]
  Atelectasis: 0.8323 !!!
  Edema: 0.7979 !!!
  Pleural_Other: 0.7650 !!!
  Fracture: 0.7467 !!!
  Pleural_Effusion: 0.7159 !!!
  Lung_Opacity: 0.6968 !
  Cardiomegaly: 0.5970 !
  ... (14개 전체)

[YOLOv8 Object Detection]
  Cardiomegaly: conf=0.42, bbox=[1283, 2034, 2884, 2501]

[임상 로직 판정 (Layer 3)]
감지 질환 수: 10

[Cardiomegaly] 양성
  신뢰도: medium, 심각도: mild
  근거: CTR 0.5204, DenseNet 0.60, AP 뷰 고려
  정량: {"ctr": 0.5204, "heart_width_px": 96, "thorax_width_px": 150}

[Pleural_Effusion] 양성
  근거: DenseNet 0.72
  정량: {"estimated_volume": "small"}

[Atelectasis] 양성
  위치: right
  근거: 우측 폐면적 24.5% 감소, DenseNet 0.83

[Edema] 양성
  위치: unilateral
  근거: DenseNet 0.80, butterfly 패턴 의심

... (10개 질환 전체 상세)

[교차 검증 요약]
높은 일치: Cardiomegaly
중간 일치: 9개 질환
주의 필요: Pneumonia (1개 소스만 양성)

[감별 진단]
1. 심인성 폐부종 (high)
2. 무기폐 (high)
3. 울혈성 심부전 CHF (high)

[위험도: critical]

---

위 결과를 종합하여 JSON으로 응답하세요:
{
    "structured": { "heart": "...", "pleura": "...", ... },
    "narrative": "...",
    "summary": "...",
    "suggested_next_actions": [...]
}
```

---

## 병목 분석

```
Stage 1 (seg):       0.153s   0.3%
Stage 2a (densenet): 0.044s   0.1%
Stage 2b (yolo):     0.413s   0.8%
Stage 3 (clinical):  0.000s   0.0%
Stage 5 (rag):       0.000s   (미연결)
Stage 6 (bedrock):  48.700s  98.8%  ◀◀◀ 병목
─────────────────────────────
합계:               49.310s  100%
```

### 병목 원인: Bedrock 출력 토큰 3,393개

- 입력 2,662 토큰 — **적당함** (과도하지 않음)
- 출력 3,393 토큰 — **이게 병목** (7섹션 구조화 + 서술형 + 요약 + 권고)
- 생성 속도 ~70 tok/s — 서울 리전 Sonnet 4.6 정상 범위
- 48.7초 ≈ 3393 / 70 tok/s

### 줄이는 방법 (참고, 미적용)

| 방법 | 예상 효과 |
|------|----------|
| max_tokens 4096→1500 | 48초 → ~20초 |
| detected만 프롬프트에 포함 (14→10) | 입력 약간 감소 |
| 7섹션→3섹션 (impression+recommendation+핵심) | 48초 → ~15초 |
| 스트리밍 응답 | 총 시간 동일, 체감 개선 |
| 음성 소견 프롬프트 제외 | 입력 ~30% 감소 |
