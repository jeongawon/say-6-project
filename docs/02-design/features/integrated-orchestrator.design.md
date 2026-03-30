# 흉부 모달 통합 오케스트레이터 — 상세 설계서

> **Feature**: integrated-orchestrator
> **Plan Reference**: `docs/01-plan/features/integrated-orchestrator.plan.md`
> **Date**: 2026-03-23
> **Status**: Draft

---

## 1. 파일 구조 및 구현 순서

```
deploy/chest_modal_orchestrator/
├── config.py                 ← [1] 엔드포인트 URL + 기본값 상수
├── input_parser.py           ← [2] 유연한 입력 파싱 + 필드 매핑
├── output_formatter.py       ← [3] 출력 형태 변환 (3가지 포맷)
├── layer_client.py           ← [4] 각 Layer HTTP 호출 클라이언트
├── orchestrator.py           ← [5] 파이프라인 오케스트레이션 (핵심)
├── test_cases.py             ← [6] 5개 테스트 케이스 데이터
├── lambda_function.py        ← [7] Lambda 핸들러 (GET/POST 분기)
├── index.html                ← [8] 통합 테스트 웹 페이지
├── Dockerfile                ← [9] 컨테이너 정의
└── requirements.txt          ← [9] requests
```

배포 스크립트: `deploy/deploy_integrated.py` ← [10]

---

## 2. 모듈별 상세 설계

### 2.1 config.py

```python
"""통합 오케스트레이터 설정"""

# === 기존 Layer 엔드포인트 (절대 수정 금지) ===
LAYER1_URL = "https://jwhljyevn3hm44nhvs5zcdstmi0tmuvi.lambda-url.ap-northeast-2.on.aws/"
LAYER2_URL = "https://pk67s3qrp3b3xluqkcp6neqly40kduol.lambda-url.ap-northeast-2.on.aws/"
LAYER2B_URL = "https://yoaval7laoc4ngnkr7uod7dufm0nmxib.lambda-url.ap-northeast-2.on.aws/"
LAYER3_URL = "https://ihq6gjldxbulfke5xd2xexnoqe0vyrxt.lambda-url.ap-northeast-2.on.aws/"
LAYER5_URL = "https://rn32hjcarfgqhopm266iidoeey0lkbkt.lambda-url.ap-northeast-2.on.aws/"
LAYER6_URL = "https://ofii46d5p6446ceahn3ucb5f2a0xcvej.lambda-url.ap-northeast-2.on.aws/"

# === Layer별 타임아웃 (초) ===
LAYER_TIMEOUTS = {
    "layer1": 120,
    "layer2": 180,
    "layer2b": 180,
    "layer3": 30,
    "layer5": 120,
    "layer6": 120,
}

# === 기본 옵션값 ===
DEFAULT_OPTIONS = {
    "report_language": "ko",
    "include_rag": True,
    "top_k": 3,
    "skip_layers": [],
    "return_mask": True,
    "return_annotated_image": True,
}

# === S3 설정 ===
WORK_BUCKET = "pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an"
SAMPLE_S3_PREFIX = "web/test-integrated/samples"
```

---

### 2.2 input_parser.py

**책임**: 어떤 형태의 입력이든 정규화하여 오케스트레이터가 사용할 수 있는 표준 구조로 변환.

```python
def parse_input(body: dict) -> dict:
    """
    입력 파싱 — 다양한 필드명 수용, 없으면 기본값, 원본 보관.

    Returns:
        {
            "image_base64": str | None,
            "s3_key": str | None,
            "patient_info": dict,
            "prior_results": list,
            "options": dict,
            "raw_input": dict,  # 원본 전체
        }

    Raises:
        ValueError: 이미지가 전혀 없을 때
    """
```

**필드 매핑 규칙**:

| 입력 필드명 후보 | 정규화된 필드명 |
|-----------------|---------------|
| `image_base64`, `image`, `cxr_image` | `image_base64` |
| `s3_key`, `s3_path`, `image_s3_path` | `s3_key` |
| `patient_info` (dict) | `patient_info` |
| 루트의 `age`, `sex`, `gender` | `patient_info.age`, `patient_info.sex` |
| `prior_results` (list 또는 dict) | `prior_results` (항상 list) |
| `options` (dict) | `options` (DEFAULT_OPTIONS 머지) |

---

### 2.3 output_formatter.py

**책임**: 내부 전체 결과 → 외부 반환 형태 변환. 3가지 포맷 제공.

```python
class OutputFormatter:
    @staticmethod
    def default(full_result: dict) -> dict:
        """전체 결과 반환 — API 기본"""
        return full_result

    @staticmethod
    def summary_only(full_result: dict) -> dict:
        """요약만 — 다른 모달이 참고할 때"""
        return {
            "modal": "chest_xray",
            "summary": full_result["summary"],
            "suggested_next_actions": full_result["suggested_next_actions"],
            "timestamp": full_result["timestamp"],
        }

    @staticmethod
    def orchestrator_format(full_result: dict) -> dict:
        """오케스트레이터용 — 팀에서 형태 정하면 여기만 수정"""
        return full_result
```

---

### 2.4 layer_client.py

**책임**: 각 Layer에 대한 HTTP 호출 캡슐화. 응답 시간 자동 측정.

```python
import time
import requests

class LayerClient:
    def __init__(self):
        self.session = requests.Session()

    def call_layer1(self, image_payload: dict) -> dict:
        """Layer 1 Segmentation 호출
        입력: {"image_base64": "..."} 또는 {"s3_key": "..."}
        출력: {measurements, mask_base64, view, age_pred, sex_pred, processing_time}
        """

    def call_layer2(self, image_payload: dict) -> dict:
        """Layer 2a DenseNet 호출
        입력: {"image_base64": "..."} 또는 {"s3_key": "..."}
        출력: {findings, probabilities, positive_findings, num_positive, summary}
        """

    def call_layer2b(self, image_payload: dict) -> dict:
        """Layer 2b YOLOv8 호출 (선택)
        입력: {"image_base64": "..."} 또는 {"s3_key": "..."}
        출력: {detections, annotated_image_base64}
        """

    def call_layer3(self, payload: dict) -> dict:
        """Layer 3 Clinical Logic 호출
        입력: {"action":"custom", "anatomy":{...}, "densenet":{...}, "patient_info":{...}, "prior_results":[...]}
        출력: {mode, input_summary, result:{findings, cross_validation, differential_diagnosis, risk_level, alert_flags}}
        """

    def call_layer5(self, clinical_logic: dict, top_k: int = 3) -> dict:
        """Layer 5 RAG 호출
        입력: {"action":"custom", "clinical_logic":{...}, "top_k": 3}
        출력: {results/rag_evidence, query_text/query_used, count/total_results, layer6_formatted}
        """

    def call_layer6(self, payload: dict) -> dict:
        """Layer 6 Bedrock Report 호출
        입력: {"action":"generate", "report_language":"ko",
               "patient_info":{...}, "anatomy_measurements":{...},
               "densenet_predictions":{...}, "yolo_detections":[...],
               "clinical_logic":{...}, "cross_validation_summary":{...},
               "prior_results":[...], "rag_evidence":[...]}
        출력: {mode, report:{request_id, report:{structured, narrative, summary, risk_level}, suggested_next_actions, metadata}}
        """
```

**공통 패턴**:
```python
def _call(self, url: str, payload: dict, timeout: int) -> dict:
    start = time.time()
    resp = self.session.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    data["_processing_time_ms"] = int((time.time() - start) * 1000)
    return data
```

---

### 2.5 orchestrator.py (핵심)

**책임**: 5단계 파이프라인 실행 + 결과 취합.

#### 실행 흐름

```
run(parsed_input) → dict
  │
  ├── Step 1+2: Layer 1 + Layer 2a 병렬 (ThreadPoolExecutor)
  │     ├── _call_layer1(image_payload) → layer1_result
  │     └── _call_layer2(image_payload) → layer2_result
  │     (+ Layer 2b 병렬 추가 가능)
  │
  ├── Step 3: _build_layer3_payload() → Layer 3 호출
  │     - Layer 1 measurements 평탄화
  │     - Layer 2a probabilities 키 변환 (공백→언더스코어)
  │
  ├── Step 4: Layer 5 RAG 호출 (include_rag 옵션 확인)
  │     - Layer 3의 result 객체를 clinical_logic으로 전달
  │
  ├── Step 5: _build_layer6_payload() → Layer 6 호출
  │     - 전체 Layer 결과 + RAG evidence 조합
  │
  └── 결과 취합: _build_summary() + _extract_next_actions() + _extract_report()
```

#### Layer 1 → Layer 3 데이터 변환 (평탄화)

Layer 1 응답의 중첩 구조를 Layer 3가 기대하는 평탄 구조로 변환:

```python
def _flatten_layer1_for_layer3(self, layer1: dict) -> dict:
    """
    Layer 1 measurements 중첩 구조 → Layer 3 anatomy 평탄 구조
    """
    m = layer1.get("measurements", {})

    anatomy = {
        # 직접 매핑 (이미 평탄)
        "ctr": m.get("ctr"),
        "ctr_status": m.get("ctr_status"),
        "heart_width_px": m.get("heart_width_px"),
        "thorax_width_px": m.get("thorax_width_px"),
        "right_lung_area_px2": m.get("right_lung_area_px"),    # 주의: Layer1은 _px, Layer3은 _px2
        "left_lung_area_px2": m.get("left_lung_area_px"),
        "heart_area_px2": m.get("heart_area_px"),
        "lung_area_ratio": m.get("lung_area_ratio"),
        "total_lung_area_px2": m.get("total_lung_area_px"),

        # 중첩 → 평탄 (mediastinum)
        "mediastinum_status": m.get("mediastinum", {}).get("status"),
        "mediastinum_width_px": m.get("mediastinum", {}).get("width_px"),

        # 중첩 → 평탄 (trachea)
        "trachea_midline": m.get("trachea", {}).get("midline"),
        "trachea_deviation_direction": m.get("trachea", {}).get("deviation_direction"),
        "trachea_deviation_ratio": m.get("trachea", {}).get("deviation_ratio"),

        # 중첩 → 평탄 (cp_angle)
        "right_cp_status": m.get("cp_angle", {}).get("right", {}).get("status"),
        "right_cp_angle_degrees": m.get("cp_angle", {}).get("right", {}).get("angle_degrees"),
        "left_cp_status": m.get("cp_angle", {}).get("left", {}).get("status"),
        "left_cp_angle_degrees": m.get("cp_angle", {}).get("left", {}).get("angle_degrees"),

        # 중첩 → 평탄 (diaphragm)
        "diaphragm_status": m.get("diaphragm", {}).get("status"),

        # 메타 (Layer 1 최상위 필드)
        "view": layer1.get("view"),
        "predicted_age": layer1.get("age_pred"),
        "predicted_sex": layer1.get("sex_pred"),
    }
    return anatomy
```

#### Layer 2a → Layer 3 데이터 변환 (키 정규화)

```python
def _normalize_layer2_for_layer3(self, layer2: dict) -> dict:
    """
    Layer 2a probabilities 키 변환: "Pleural Effusion" → "Pleural_Effusion"
    Layer 3은 언더스코어 구분자를 사용함
    """
    densenet = {}
    for disease, prob in layer2.get("probabilities", {}).items():
        key = disease.replace(" ", "_")
        densenet[key] = prob
    return densenet
```

#### Layer 3 payload 조립

```python
def _build_layer3_payload(self, layer1: dict, layer2: dict,
                          patient_info: dict, prior_results: list) -> dict:
    return {
        "action": "custom",
        "anatomy": self._flatten_layer1_for_layer3(layer1),
        "densenet": self._normalize_layer2_for_layer3(layer2),
        "patient_info": patient_info,
        "prior_results": prior_results,
    }
```

#### Layer 6 payload 조립

```python
def _build_layer6_payload(self, layer_results: dict, patient_info: dict,
                          prior_results: list, options: dict) -> dict:
    """
    Layer 6 generate 액션에 필요한 필드:
    - action: "generate"
    - report_language: "ko"/"en"
    - patient_info: {...}
    - anatomy_measurements: Layer 1 measurements (중첩 구조 그대로 가능)
    - densenet_predictions: Layer 2a probabilities
    - yolo_detections: Layer 2b detections (없으면 빈 리스트)
    - clinical_logic: Layer 3 result 전체
    - cross_validation_summary: Layer 3 result.cross_validation
    - prior_results: [...]
    - rag_evidence: Layer 5 결과의 results/rag_evidence 배열
    """
    layer3 = layer_results.get("layer3", {})
    layer3_result = layer3.get("result", {})
    layer5 = layer_results.get("layer5", {})

    # Layer 5 결과에서 rag_evidence 추출 (live모드: results, mock모드: rag_evidence)
    rag_evidence = layer5.get("results", layer5.get("rag_evidence", []))

    return {
        "action": "generate",
        "report_language": options.get("report_language", "ko"),
        "patient_info": patient_info,
        "anatomy_measurements": layer_results.get("layer1", {}).get("measurements", {}),
        "densenet_predictions": layer_results.get("layer2", {}).get("probabilities", {}),
        "yolo_detections": layer_results.get("layer2b", {}).get("detections", []),
        "clinical_logic": layer3_result,
        "cross_validation_summary": layer3_result.get("cross_validation", {}),
        "prior_results": prior_results,
        "rag_evidence": rag_evidence,
    }
```

#### 결과 취합

```python
def _build_summary(self, result: dict) -> dict:
    """Layer 3 결과에서 요약 생성"""
    layer3 = result["layer_results"].get("layer3", {})
    r = layer3.get("result", {})

    detected = []
    for name, finding in r.get("findings", {}).items():
        if finding.get("detected") and name != "No_Finding":
            detected.append(name)

    diff = r.get("differential_diagnosis", [])
    primary = diff[0]["diagnosis"] if diff else None

    return {
        "risk_level": r.get("risk_level", "UNKNOWN"),
        "detected_diseases": detected,
        "detected_count": len(detected),
        "primary_diagnosis": primary,
        "one_line": f"{', '.join(detected)} -> {primary}. {r.get('risk_level', '')}."
                    if detected else "No significant findings.",
        "alert_flags": r.get("alert_flags", []),
    }

def _extract_report(self, result: dict) -> dict:
    """Layer 6 결과에서 소견서 추출"""
    layer6 = result["layer_results"].get("layer6", {})
    return layer6.get("report", {}).get("report", {})

def _extract_next_actions(self, result: dict) -> list:
    """Layer 6 결과에서 권고 조치 추출"""
    layer6 = result["layer_results"].get("layer6", {})
    return layer6.get("report", {}).get("suggested_next_actions", [])
```

#### 에러 처리 전략

| 실패 레이어 | 영향 | 동작 |
|------------|------|------|
| Layer 1 실패 | Layer 3 이하 실행 불가 (anatomy 데이터 없음) | Layer 3, 5, 6 스킵, summary에 "partial" 표시 |
| Layer 2a 실패 | Layer 3 이하 실행 불가 (densenet 데이터 없음) | Layer 3, 5, 6 스킵 |
| Layer 2b 실패 | Layer 3에 YOLO 정보 누락 | Layer 3 이하 정상 진행 (YOLO 데이터만 빈 리스트) |
| Layer 3 실패 | Layer 5, 6 실행 불가 | Layer 5, 6 스킵 |
| Layer 5 실패 | Layer 6에 RAG 데이터 누락 | Layer 6 정상 진행 (RAG 없이 소견서 생성) |
| Layer 6 실패 | 소견서 미생성 | report 필드 비움, summary는 Layer 3 기반으로 제공 |

---

### 2.6 test_cases.py

5개 테스트 케이스, 각각 S3 샘플 이미지 + 환자 정보 + prior_results 포함.

```python
TEST_CASES = {
    "chf": {
        "name": "심부전 (CHF)",
        "description": "72세 남성, 호흡곤란 2주, 하지 부종",
        "s3_key": "web/test-integrated/samples/chf_sample.jpg",
        "patient_info": {
            "patient_id": "TC001", "age": 72, "sex": "M",
            "chief_complaint": "호흡곤란, 하지 부종",
            "vitals": {"temperature": 36.8, "heart_rate": 98,
                       "blood_pressure": "150/90", "spo2": 92, "respiratory_rate": 24}
        },
        "prior_results": [
            {"modal": "ecg", "summary": "동성빈맥, 좌심실비대 소견"}
        ],
        "expected_risk": "URGENT",
    },
    "pneumonia": {
        "name": "폐렴 (Pneumonia)",
        "description": "67세 남성, 발열 38.5C, 기침, 농성 객담",
        "s3_key": "web/test-integrated/samples/pneumonia_sample.jpg",
        "patient_info": {
            "patient_id": "TC002", "age": 67, "sex": "M",
            "chief_complaint": "발열, 기침, 농성 객담 3일",
            "vitals": {"temperature": 38.5, "heart_rate": 105,
                       "blood_pressure": "120/70", "spo2": 94, "respiratory_rate": 22}
        },
        "prior_results": [
            {"modal": "lab", "summary": "WBC 15000, CRP 12.5, PCT 0.8"}
        ],
        "expected_risk": "URGENT",
    },
    "tension_pneumothorax": {
        "name": "긴장성 기흉",
        "description": "25세 남성, 교통사고 후 호흡곤란, 좌측 흉통",
        "s3_key": "web/test-integrated/samples/ptx_sample.jpg",
        "patient_info": {
            "patient_id": "TC003", "age": 25, "sex": "M",
            "chief_complaint": "교통사고 후 좌측 흉통, 호흡곤란",
            "vitals": {"temperature": 36.5, "heart_rate": 130,
                       "blood_pressure": "80/50", "spo2": 82, "respiratory_rate": 36}
        },
        "prior_results": [],
        "expected_risk": "CRITICAL",
    },
    "normal": {
        "name": "정상 (Normal)",
        "description": "35세 여성, 건강검진 흉부 촬영",
        "s3_key": "web/test-integrated/samples/normal_sample.jpg",
        "patient_info": {
            "patient_id": "TC004", "age": 35, "sex": "F",
            "chief_complaint": "건강검진",
            "vitals": {"temperature": 36.5, "heart_rate": 72,
                       "blood_pressure": "120/80", "spo2": 99, "respiratory_rate": 16}
        },
        "prior_results": [],
        "expected_risk": "ROUTINE",
    },
    "multi_finding": {
        "name": "다중 소견 (Multi-finding)",
        "description": "80세 여성, 낙상 후 흉통, 호흡곤란, 기존 COPD",
        "s3_key": "web/test-integrated/samples/multi_sample.jpg",
        "patient_info": {
            "patient_id": "TC005", "age": 80, "sex": "F",
            "chief_complaint": "낙상 후 흉통, 만성 호흡곤란 악화",
            "vitals": {"temperature": 37.2, "heart_rate": 115,
                       "blood_pressure": "100/60", "spo2": 87, "respiratory_rate": 30}
        },
        "prior_results": [
            {"modal": "ecg", "summary": "심방세동, 빈맥"},
            {"modal": "lab", "summary": "WBC 18000, D-dimer 2.5, BNP 850"}
        ],
        "expected_risk": "URGENT",
    },
}
```

**샘플 이미지**: 기존 Layer 테스트에서 사용하던 CXR 이미지 5장을 `s3://work-bucket/web/test-integrated/samples/`에 복사.

---

### 2.7 lambda_function.py

```python
"""
통합 오케스트레이터 Lambda 핸들러

GET  → 테스트 페이지 (index.html)
POST → 통합 파이프라인 API

POST actions:
  - "run"             → 전체 파이프라인 실행 (기본)
  - "list_test_cases" → 5개 테스트 케이스 목록 반환
  - "test_case"       → 특정 테스트 케이스로 파이프라인 실행
"""
```

**API 설계**:

| 메서드 | 액션 | 설명 |
|--------|------|------|
| GET | - | 테스트 페이지 HTML 반환 |
| POST | `run` | 이미지+환자정보 → 전체 파이프라인 실행 → JSON 결과 |
| POST | `list_test_cases` | 5개 테스트 케이스 이름/설명 반환 |
| POST | `test_case` | 지정 테스트 케이스로 파이프라인 실행 (S3에서 이미지 로드) |

**test_case 액션**: S3에서 샘플 이미지를 base64로 다운로드 → `run`과 동일하게 파이프라인 실행.

---

### 2.8 index.html — 통합 테스트 페이지

**방식**: 방법 B (JS 직접 순차 호출) — 각 Layer를 브라우저에서 직접 호출하여 실시간 진행 표시.

#### UI 섹션 구조

```
[Header]      → 제목 + 부제
[Test Cases]  → 5개 시나리오 카드 + 이미지 업로드 영역
[Main Area]   → 좌: CXR 미리보기 / 우: 파이프라인 진행 상태
[Summary]     → Risk 배지 + 감별진단 + 발견 질환 목록
[Report]      → 구조화 소견서 8섹션 렌더링
[Layer Details] → 접기/펼치기 아코디언 (Layer별 원본 결과)
[RAW JSON]    → 접기/펼치기 (디버깅용 요청/응답 전문)
```

#### JS 파이프라인 로직

```javascript
async function runPipeline(imageBase64, patientInfo, priorResults, options) {
    resetProgress();

    // Step 1+2: Layer 1 + Layer 2 병렬
    updateProgress("layer1", "running");
    updateProgress("layer2", "running");
    const [layer1, layer2] = await Promise.allSettled([
        callLayer("layer1", LAYER1_URL, {image_base64: imageBase64}),
        callLayer("layer2", LAYER2_URL, {image_base64: imageBase64}),
    ]);
    updateProgress("layer1", layer1.status === "fulfilled" ? "done" : "error");
    updateProgress("layer2", layer2.status === "fulfilled" ? "done" : "error");

    if (layer1.status === "rejected" || layer2.status === "rejected") {
        showError("Layer 1 또는 2 실패 — Layer 3 이하 스킵");
        return;
    }

    // Step 3: Layer 3
    updateProgress("layer3", "running");
    const layer3Payload = buildLayer3Payload(layer1.value, layer2.value, patientInfo, priorResults);
    const layer3 = await callLayer("layer3", LAYER3_URL, layer3Payload);
    updateProgress("layer3", "done");

    // Step 4: Layer 5 RAG
    updateProgress("layer5", "running");
    const layer5Payload = {action:"custom", clinical_logic: layer3.result, top_k: options.top_k || 3};
    const layer5 = await callLayer("layer5", LAYER5_URL, layer5Payload);
    updateProgress("layer5", "done");

    // Step 5: Layer 6 Bedrock
    updateProgress("layer6", "running");
    const layer6Payload = buildLayer6Payload(layer1.value, layer2.value, layer3, layer5, patientInfo, priorResults, options);
    const layer6 = await callLayer("layer6", LAYER6_URL, layer6Payload);
    updateProgress("layer6", "done");

    renderResults(layer1.value, layer2.value, layer3, layer5, layer6);
}
```

#### JS에서 Layer 1 → Layer 3 변환 함수

```javascript
function buildLayer3Payload(layer1, layer2, patientInfo, priorResults) {
    const m = layer1.measurements || {};
    return {
        action: "custom",
        anatomy: {
            ctr: m.ctr,
            ctr_status: m.ctr_status,
            heart_width_px: m.heart_width_px,
            thorax_width_px: m.thorax_width_px,
            right_lung_area_px2: m.right_lung_area_px,
            left_lung_area_px2: m.left_lung_area_px,
            heart_area_px2: m.heart_area_px,
            lung_area_ratio: m.lung_area_ratio,
            total_lung_area_px2: m.total_lung_area_px,
            mediastinum_status: (m.mediastinum || {}).status,
            mediastinum_width_px: (m.mediastinum || {}).width_px,
            trachea_midline: (m.trachea || {}).midline,
            trachea_deviation_direction: (m.trachea || {}).deviation_direction,
            trachea_deviation_ratio: (m.trachea || {}).deviation_ratio,
            right_cp_status: ((m.cp_angle || {}).right || {}).status,
            right_cp_angle_degrees: ((m.cp_angle || {}).right || {}).angle_degrees,
            left_cp_status: ((m.cp_angle || {}).left || {}).status,
            left_cp_angle_degrees: ((m.cp_angle || {}).left || {}).angle_degrees,
            diaphragm_status: (m.diaphragm || {}).status,
            view: layer1.view,
            predicted_age: layer1.age_pred,
            predicted_sex: layer1.sex_pred,
        },
        densenet: Object.fromEntries(
            Object.entries(layer2.probabilities || {}).map(([k, v]) => [k.replace(/ /g, "_"), v])
        ),
        patient_info: patientInfo || {},
        prior_results: priorResults || [],
    };
}
```

#### JS에서 Layer 6 payload 조립 함수

```javascript
function buildLayer6Payload(layer1, layer2, layer3, layer5, patientInfo, priorResults, options) {
    const ragEvidence = layer5.results || layer5.rag_evidence || [];
    return {
        action: "generate",
        report_language: options.report_language || "ko",
        patient_info: patientInfo || {},
        anatomy_measurements: layer1.measurements || {},
        densenet_predictions: layer2.probabilities || {},
        yolo_detections: [],
        clinical_logic: layer3.result || {},
        cross_validation_summary: (layer3.result || {}).cross_validation || {},
        prior_results: priorResults || [],
        rag_evidence: ragEvidence,
    };
}
```

#### 디자인 시스템

기존 `PROMPT_UI_Redesign_All_Layers.md` 디자인 시스템 그대로 적용:
- CSS 변수: `--bg-primary: #0a0e17`, `--accent: #4A9EFF`
- 폰트: `"JetBrains Mono", "Fira Code", monospace`
- border-radius: max 6px
- gradient/glow/emoji 금지
- PACS/EMR 스타일 다크 테마

#### 위험도 배지 스타일

```css
.risk-routine  { background: #2a2a3a; color: #8b8b9a; }
.risk-urgent   { background: #3d2800; color: #ff9500; border: 1px solid #ff9500; }
.risk-critical { background: #3d0000; color: #ff3b30; border: 1px solid #ff3b30;
                 animation: blink 1s infinite; }
```

---

### 2.9 Dockerfile + requirements.txt

**Dockerfile**:
```dockerfile
FROM public.ecr.aws/lambda/python:3.12
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && rm -rf /root/.cache /tmp/*
COPY *.py ./
COPY index.html ./
CMD ["lambda_function.handler"]
```

**requirements.txt**:
```
requests
```

예상 이미지: ~760MB (베이스 748MB + requests ~12MB)

---

### 2.10 deploy_integrated.py

기존 `deploy_layer*.py`와 동일한 패턴:

```python
"""
통합 오케스트레이터 배포 스크립트
1. ECR 리포지토리 생성 (chest-modal-integrated)
2. Docker 이미지 빌드
3. ECR 로그인 + 푸시
4. Lambda 함수 생성/업데이트 (512MB, 300s timeout)
5. Function URL 생성 + 테스트
"""
```

Lambda 설정:
| 항목 | 값 |
|------|-----|
| FunctionName | `chest-modal-integrated` |
| MemorySize | 512 |
| Timeout | 300 |
| EphemeralStorage | 512 |
| Role | `say-2-lambda-bedrock-role` |
| PackageType | Image |
| Architectures | x86_64 |

---

## 3. API 스펙

### 3.1 POST /run — 전체 파이프라인 실행

**Request**:
```json
{
    "action": "run",
    "image_base64": "data:image/jpeg;base64,...",
    "patient_info": { "age": 72, "sex": "M", ... },
    "prior_results": [...],
    "options": { "report_language": "ko", "include_rag": true, "top_k": 3 }
}
```

**Response**: Plan 문서 섹션 4.2 출력 구조 참조.

### 3.2 POST /list_test_cases

**Request**: `{"action": "list_test_cases"}`

**Response**:
```json
{
    "test_cases": {
        "chf": {"name": "심부전 (CHF)", "description": "72세 남성, ..."},
        "pneumonia": {...},
        "tension_pneumothorax": {...},
        "normal": {...},
        "multi_finding": {...}
    }
}
```

### 3.3 POST /test_case — 테스트 케이스 실행

**Request**:
```json
{
    "action": "test_case",
    "test_case": "chf",
    "options": { "report_language": "ko" }
}
```

**Response**: run과 동일 구조 (S3에서 이미지 로드 후 파이프라인 실행).

---

## 4. 구현 체크리스트

| # | 파일 | 핵심 검증 포인트 |
|---|------|-----------------|
| 1 | config.py | 6개 엔드포인트 URL 정확, 타임아웃 값 적절 |
| 2 | input_parser.py | 다양한 필드명 수용, 빈 입력 시 기본값, ValueError on no image |
| 3 | output_formatter.py | 3가지 포맷 출력 정상 |
| 4 | layer_client.py | 각 Layer 호출 성공, 타임아웃 동작, processing_time 측정 |
| 5 | orchestrator.py | 병렬 실행, 평탄화 변환 정확, 에러 시 부분 계속 |
| 6 | test_cases.py | 5개 케이스 데이터 완전, S3 키 유효 |
| 7 | lambda_function.py | GET→HTML, POST→3개 액션 분기, CORS 헤더 |
| 8 | index.html | 실시간 진행 표시, 소견서 렌더링, 디자인 시스템 준수 |
| 9 | Dockerfile | 빌드 성공, ~760MB |
| 10 | deploy_integrated.py | ECR+Lambda 배포 완료, Function URL 동작 |
| 11 | E2E 테스트 | 5개 시나리오 정상 완료, 기대 Risk Level 일치 |
