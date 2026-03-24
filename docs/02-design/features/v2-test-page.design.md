# Design: v2 테스트 페이지 및 테스트 케이스 검증 시스템

> 작성일: 2026-03-24
> 레벨: Dynamic
> 상태: Design
> 아키텍처: 비동기 폴링 패턴 (Asynchronous Polling)
> Plan 참조: docs/01-plan/features/v2-test-page.plan.md

---

## Context Anchor

| 항목 | 내용 |
|------|------|
| **WHY** | v2 아키텍처(2 Lambda + Step Functions)가 실제로 동작하는지 E2E 검증이 필요하며, v1 대비 기능 손실이 없음을 증명해야 한다 |
| **WHO** | 프로젝트 6팀 (의료 AI 흉부 X-Ray 분석 시스템) |
| **RISK** | Step Functions Express 동기 호출 29초 타임아웃, CORS 설정 미비, 테스트 이미지 S3 접근 권한 |
| **SUCCESS** | 5개 테스트 케이스 모두 E2E 정상 완료, v1 대비 동일 결과 출력, Playwright 테스트 전체 통과 |
| **SCOPE** | `deploy/v2/test-page/`, `deploy/v2/api-gateway/`, `tests/e2e/` 하위에 신규 생성. 기존 v2 Lambda/Step Functions 코드는 수정하지 않음 |

---

## 1. Overview

### 1.1 설계 목표
REST API의 29초 타임아웃 한계를 극복하기 위해 **비동기 폴링 패턴(Asynchronous Polling)**을 적용한다.
API Gateway 2개 엔드포인트 + 테스트 페이지 + Playwright E2E 테스트를 구현한다.

### 1.2 선택된 아키텍처: 비동기 폴링 패턴

**선택 이유:**
- REST API의 타임아웃 한계를 정석으로 극복
- 서버 리소스 낭비 없음 (비동기 시작 → 폴링으로 확인)
- 새로고침해도 작업 ID만 있으면 결과 재확인 가능
- 포트폴리오에서 확장성 있는 아키텍처 설계 역량 어필

---

## 2. 아키텍처 상세

### 2.1 전체 흐름

```
[Browser Test Page]
        |
        | 1. POST /analyze  (이미지 + 환자정보)
        v
[API Gateway REST]
        |
        | 2. StartExecution (비동기)
        v
[Step Functions]  ──→  [Lambda A x3 parallel] ──→ [Lambda B]
        |
        | 3. 즉시 응답: { executionArn, status: "RUNNING" }
        v
[Browser]
        |
        | 4. GET /analyze/status?id={executionArn}  (3초 간격 폴링)
        v
[API Gateway REST]
        |
        | 5. DescribeExecution
        v
[Step Functions]
        |
        | 6-a. status: "RUNNING" → { status: "RUNNING" }
        | 6-b. status: "SUCCEEDED" → 결과 파싱 + S3 Claim-Check 로드
        v
[Status Lambda]
        |
        | 7. S3에서 중간 결과 로드 (seg/densenet/yolo)
        |    Presigned URL 생성 (테스트 이미지)
        v
[Browser] ← 전체 결과 수신 → 시각화
```

### 2.2 API 엔드포인트 설계

#### POST /analyze
- **역할**: Step Functions 비동기 실행 시작
- **Integration**: API Gateway → Step Functions StartExecution (AWS Service Integration)
- **요청 본문**:
```json
{
    "image_base64": "base64-encoded-image-string",
    "s3_key": "web/test-integrated/samples/chf_sample.jpg",
    "patient_info": {
        "patient_id": "TC001",
        "age": 72,
        "sex": "M",
        "chief_complaint": "호흡곤란",
        "vitals": { ... }
    }
}
```
- **응답** (즉시, ~100ms):
```json
{
    "executionArn": "arn:aws:states:ap-northeast-2:666803869796:execution:dr-ai-radiologist-pipeline-v2:abc-123",
    "startDate": "2026-03-24T10:00:00Z",
    "status": "RUNNING"
}
```

#### GET /analyze/status
- **역할**: 실행 상태 확인 + 완료 시 결과 반환
- **Integration**: API Gateway → Status Lambda (Lambda Proxy)
- **쿼리 파라미터**: `id={executionArn}`
- **응답 (실행 중)**:
```json
{
    "status": "RUNNING",
    "startDate": "2026-03-24T10:00:00Z"
}
```
- **응답 (완료)**:
```json
{
    "status": "SUCCEEDED",
    "executionArn": "...",
    "results": {
        "report": { ... },
        "seg": {
            "mask_base64": "...",
            "measurements": { ... }
        },
        "densenet": {
            "predictions": [ ... ]
        },
        "yolo": {
            "detections": [ ... ]
        },
        "clinical_logic": { ... },
        "rag_evidence": [ ... ]
    },
    "timing": {
        "totalSeconds": 45.2,
        "startDate": "...",
        "stopDate": "..."
    }
}
```
- **응답 (실패)**:
```json
{
    "status": "FAILED",
    "error": "Critical model failed: seg",
    "cause": "..."
}
```

### 2.3 API Gateway 설정

```
API Name: dr-ai-radiologist-v2-api
Stage: test
Region: ap-northeast-2

Resources:
  /analyze
    POST → Step Functions StartExecution (AWS Service)
    OPTIONS → Mock (CORS preflight)

  /analyze/status
    GET → Status Lambda (Lambda Proxy)
    OPTIONS → Mock (CORS preflight)

CORS:
  Access-Control-Allow-Origin: *
  Access-Control-Allow-Methods: GET, POST, OPTIONS
  Access-Control-Allow-Headers: Content-Type
```

### 2.4 동시 요청 격리 — run_id 기반 요청 분리

핵심은 **run_id(= Execution ID)로 요청을 격리**하는 것이다.
동시 요청이 들어와도 각 요청은 독립된 Execution으로 생성되어 절대 섞이지 않는다.

**동시 요청 시나리오:**
```
10:00:00  사용자 A 요청 → Execution-AAA 생성 → Lambda A × 3 (seg, densenet, yolo)
10:00:02  사용자 B 요청 → Execution-BBB 생성 → Lambda A × 3
10:00:03  사용자 C 요청 → Execution-CCC 생성 → Lambda A × 3

→ 동시에 Lambda A 인스턴스 9개 실행 (각 3개씩)
```

**S3 결과 저장 — 완전 격리:**
```
사용자 A → s3://bucket/runs/Execution-AAA/seg.json
           s3://bucket/runs/Execution-AAA/densenet.json
           s3://bucket/runs/Execution-AAA/yolo.json
           s3://bucket/runs/Execution-AAA/final_report.json

사용자 B → s3://bucket/runs/Execution-BBB/seg.json
           ...

사용자 C → s3://bucket/runs/Execution-CCC/seg.json
           ...
```

**격리 보장 원리:**

| 메커니즘 | 설명 |
|---------|------|
| Execution ID | `$$.Execution.Id` — Step Functions가 자동 생성하는 고유 UUID |
| Lambda 격리 | 각 Execution은 독립 컨텍스트 → Lambda 간 상태 공유 없음 |
| S3 네임스페이스 | `runs/{run_id}/` 경로로 분리 → 결과 충돌 불가 |
| Claim-Check | 패턴 자체가 run_id 기반 격리 내장 |
| 동기/비동기 무관 | 이 구조는 어떤 호출 방식이든 동일하게 적용 |

**Status Lambda에서의 격리:**
- 브라우저는 자신의 `executionArn`만 알고 있음
- `GET /analyze/status?id={executionArn}` → 해당 Execution 결과만 반환
- 다른 사용자의 결과에 접근 불가 (ARN이 다르므로)

---

## 3. 모듈 상세 설계

### 3.1 Status Lambda (`api-gateway/status-lambda/`)

Step Functions 실행 상태를 확인하고, 완료 시 S3 Claim-Check 결과를 수집하여 반환.

```python
# status_handler.py

import json
import boto3
import os

sfn = boto3.client('stepfunctions')
s3 = boto3.client('s3')

S3_BUCKET = os.environ.get('S3_BUCKET',
    'pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an')
RESULT_PREFIX = 'runs/'


def lambda_handler(event, context):
    """
    GET /analyze/status?id={executionArn}
    """
    # 쿼리 파라미터에서 executionArn 추출
    params = event.get('queryStringParameters', {}) or {}
    execution_arn = params.get('id')

    if not execution_arn:
        return response(400, {'error': 'Missing id parameter'})

    try:
        # Step Functions 실행 상태 확인
        result = sfn.describe_execution(executionArn=execution_arn)
        status = result['status']

        if status == 'RUNNING':
            return response(200, {
                'status': 'RUNNING',
                'startDate': result['startDate'].isoformat(),
            })

        elif status == 'SUCCEEDED':
            # Step Functions 출력 파싱
            output = json.loads(result['output'])
            run_id = extract_run_id(execution_arn)

            # S3 Claim-Check에서 중간 결과 로드
            enriched = enrich_with_intermediate_results(output, run_id)

            return response(200, {
                'status': 'SUCCEEDED',
                'executionArn': execution_arn,
                'results': enriched,
                'timing': {
                    'totalSeconds': (result['stopDate'] - result['startDate']).total_seconds(),
                    'startDate': result['startDate'].isoformat(),
                    'stopDate': result['stopDate'].isoformat(),
                },
            })

        else:  # FAILED, TIMED_OUT, ABORTED
            error = result.get('error', 'Unknown')
            cause = result.get('cause', '')
            return response(200, {
                'status': status,
                'error': error,
                'cause': cause,
            })

    except sfn.exceptions.ExecutionDoesNotExist:
        return response(404, {'error': 'Execution not found'})
    except Exception as e:
        return response(500, {'error': str(e)})


def extract_run_id(execution_arn):
    """
    Step Functions execution ID에서 run_id 추출.
    ARN 형식: arn:aws:states:region:account:execution:stateMachine:executionId
    """
    return execution_arn.split(':')[-1]


def enrich_with_intermediate_results(sfn_output, run_id):
    """
    Step Functions 최종 출력 + S3 Claim-Check 중간 결과를 병합.
    """
    results = {
        'report': sfn_output.get('report'),
    }

    # S3에서 중간 결과 로드 (각 stage별)
    for stage in ['seg', 'densenet', 'yolo']:
        try:
            key = f'{RESULT_PREFIX}{run_id}/{stage}.json'
            obj = s3.get_object(Bucket=S3_BUCKET, Key=key)
            data = json.loads(obj['Body'].read())
            results[stage] = data
        except s3.exceptions.NoSuchKey:
            results[stage] = None
        except Exception:
            results[stage] = None

    # final_report도 로드 (clinical_logic, rag_evidence 포함)
    try:
        key = f'{RESULT_PREFIX}{run_id}/final_report.json'
        obj = s3.get_object(Bucket=S3_BUCKET, Key=key)
        final = json.loads(obj['Body'].read())
        results['clinical_logic'] = final.get('clinical_logic')
        results['rag_evidence'] = final.get('rag_evidence')
    except Exception:
        pass

    return results


def response(status_code, body):
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type',
        },
        'body': json.dumps(body, ensure_ascii=False, default=str),
    }
```

**IAM 권한 필요:**
- `states:DescribeExecution` (Step Functions)
- `s3:GetObject` (S3 Claim-Check 결과 읽기)

### 3.2 테스트 페이지 (`test-page/index.html`)

단일 HTML 파일. v1 UI 구조를 계승하되, 비동기 폴링 패턴 적용.

#### 3.2.1 핵심 JavaScript 로직

```javascript
// ── Config ──
const API_BASE = ''; // deploy 시 실제 API Gateway URL로 교체
const POLL_INTERVAL = 3000; // 3초 간격

// ── 메인 파이프라인 실행 ──
async function runPipeline() {
    const payload = {
        image_base64: imageBase64,
        patient_info: patientInfo,
    };

    // Step 1: 비동기 실행 시작
    updatePipelineStatus('starting');
    const startResp = await fetch(`${API_BASE}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    const { executionArn } = await startResp.json();

    // Step 2: 폴링으로 상태 확인
    updatePipelineStatus('running');
    const result = await pollForCompletion(executionArn);

    // Step 3: 결과 시각화
    renderResults(result);
}

async function pollForCompletion(executionArn) {
    const startTime = Date.now();
    while (true) {
        const resp = await fetch(
            `${API_BASE}/analyze/status?id=${encodeURIComponent(executionArn)}`
        );
        const data = await resp.json();

        updatePollingUI(data.status, (Date.now() - startTime) / 1000);

        if (data.status === 'SUCCEEDED') return data;
        if (data.status === 'FAILED' || data.status === 'TIMED_OUT') {
            throw new Error(data.error || 'Pipeline failed');
        }

        await new Promise(r => setTimeout(r, POLL_INTERVAL));
    }
}
```

#### 3.2.2 UI 컴포넌트 구조

```
┌─────────────────────────────────────────────────────────┐
│ Dr. AI Radiologist v2 — Test Pipeline                    │
│ Async Polling Architecture • Step Functions Express       │
├─────────────────────────────────────────────────────────┤
│                                                          │
│ [CHF] [Pneumonia] [Tension PTX] [Normal] [Multi] [Upload]│
│                                                          │
│ ┌─── Image Viewer ──────┐ ┌─── Pipeline Status ─────┐   │
│ │                        │ │                          │   │
│ │  [원본 이미지]          │ │  ● POST /analyze   0.1s │   │
│ │  [마스크 오버레이]       │ │  ◉ Polling...      12s  │   │
│ │  [YOLO 바운딩박스]      │ │    ├ Preprocess          │   │
│ │                        │ │    ├ Seg ║ DenseNet ║ YOLO│   │
│ │  [Mask] [Measure] [YOLO]│ │    └ Analysis & Report   │   │
│ │                        │ │  ○ Results loaded   0.3s │   │
│ └────────────────────────┘ └──────────────────────────┘   │
│                                                          │
│ ┌─── Anatomy Measurements ──────────────────────────┐    │
│ │ CTR: 0.5234 [Normal]                               │    │
│ │ Heart: 245px  Thorax: 468px  R-Lung: 85K px²       │    │
│ └────────────────────────────────────────────────────┘    │
│                                                          │
│ ┌─── Clinical Summary ──────────────────────────────┐    │
│ │ Risk: [URGENT]  Diseases: [Cardiomegaly] [Edema]   │    │
│ └────────────────────────────────────────────────────┘    │
│                                                          │
│ ┌─── Bedrock Report ────────────────────────────────┐    │
│ │ 소견서 내용...                                      │    │
│ └────────────────────────────────────────────────────┘    │
│                                                          │
│ ▶ Layer Details (accordion)                              │
│ ▶ Raw JSON Response                                      │
│                                                          │
│ ┌─── Test Verification ─────────────────────────────┐    │
│ │ Expected: URGENT  Actual: URGENT  ✅ PASS          │    │
│ └────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

#### 3.2.3 파이프라인 상태 표시 (v1→v2 변환)

**v1**: 6개 레이어 개별 진행 표시
**v2**: 3단계 + 폴링 상태 표시

```
Pipeline Progress:
  ✅ POST /analyze          0.1s   (API 호출)
  ⏳ Step Functions 실행중   12.3s  (폴링 카운터)
     ├─ Preprocess
     ├─ Parallel: Seg ║ DenseNet ║ YOLO
     └─ Analysis & Report
  ⬜ Results 로드            --     (S3 결과 수집)
```

### 3.3 테스트 케이스 데이터 (`test-page/test-cases.json`)

v1 `test_cases.py`를 JSON으로 변환. 예상 결과 포함.

```json
{
    "chf": {
        "name": "심부전 (CHF)",
        "description": "72세 남성, 호흡곤란 2주, 하지 부종",
        "s3_key": "web/test-integrated/samples/chf_sample.jpg",
        "patient_info": {
            "patient_id": "TC001",
            "age": 72,
            "sex": "M",
            "chief_complaint": "호흡곤란, 하지 부종",
            "vitals": {
                "temperature": 36.8,
                "heart_rate": 98,
                "blood_pressure": "150/90",
                "spo2": 92,
                "respiratory_rate": 24
            }
        },
        "prior_results": [
            { "modal": "ecg", "summary": "동성빈맥, 좌심실비대 소견" }
        ],
        "expected": {
            "risk_level": "URGENT",
            "required_fields": ["report", "clinical_logic", "segmentation", "densenet"]
        }
    }
}
```

### 3.4 API Gateway 배포 스크립트 (`api-gateway/setup-api-gw.sh`)

```bash
#!/bin/bash
# API Gateway + Status Lambda 배포
set -euo pipefail

ACCOUNT_ID="666803869796"
REGION="ap-northeast-2"
PROJECT="dr-ai-radiologist"
API_NAME="${PROJECT}-v2-api"
STAGE="test"
STATE_MACHINE_ARN="arn:aws:states:${REGION}:${ACCOUNT_ID}:stateMachine:${PROJECT}-pipeline-v2"
STATUS_LAMBDA_NAME="${PROJECT}-status-handler"

# 1. Status Lambda 배포
# 2. REST API 생성
# 3. POST /analyze → Step Functions StartExecution (AWS Service Integration)
# 4. GET /analyze/status → Status Lambda (Lambda Proxy)
# 5. CORS 설정 (OPTIONS mock)
# 6. API 배포 (test stage)
# 7. API URL 출력
```

### 3.5 Playwright E2E 테스트 (`tests/e2e/`)

#### 3.5.1 테스트 구조

```
tests/e2e/
├── playwright.config.js       # Playwright 설정
├── test-cases.json            # 테스트 케이스 데이터 (심링크 또는 복사)
├── v2-pipeline.spec.js        # 메인 E2E 테스트
└── helpers/
    └── api-client.js          # API 호출 헬퍼
```

#### 3.5.2 테스트 시나리오

```javascript
// v2-pipeline.spec.js
const { test, expect } = require('@playwright/test');
const testCases = require('./test-cases.json');

const API_BASE = process.env.API_BASE_URL || 'https://xxx.execute-api.ap-northeast-2.amazonaws.com/test';

// ── TC-01: API 응답 구조 검증 ──
test.describe('API Response Structure', () => {
    for (const [key, tc] of Object.entries(testCases)) {
        test(`${tc.name} — 응답 구조 검증`, async ({ request }) => {
            // 1. POST /analyze
            const startResp = await request.post(`${API_BASE}/analyze`, {
                data: {
                    image_base64: await loadTestImage(tc.s3_key),
                    patient_info: tc.patient_info,
                },
            });
            expect(startResp.ok()).toBeTruthy();
            const { executionArn } = await startResp.json();
            expect(executionArn).toContain('arn:aws:states');

            // 2. Poll for completion
            const result = await pollUntilComplete(request, executionArn);
            expect(result.status).toBe('SUCCEEDED');

            // 3. 응답 구조 검증
            const r = result.results;
            expect(r).toHaveProperty('report');
            expect(r).toHaveProperty('clinical_logic');
            expect(r).toHaveProperty('seg');
            expect(r).toHaveProperty('densenet');
            expect(r).toHaveProperty('yolo');

            // 4. 세그멘테이션 결과 검증
            expect(r.seg).toHaveProperty('mask_base64');
            expect(r.seg).toHaveProperty('measurements');
            expect(r.seg.measurements).toHaveProperty('ctr');

            // 5. DenseNet 결과 검증
            expect(r.densenet).toHaveProperty('predictions');
            expect(Array.isArray(r.densenet.predictions)).toBeTruthy();
        });
    }
});

// ── TC-02: 위험도 매칭 검증 ──
test.describe('Risk Level Verification', () => {
    for (const [key, tc] of Object.entries(testCases)) {
        test(`${tc.name} — 예상 위험도: ${tc.expected.risk_level}`, async ({ request }) => {
            const result = await runFullPipeline(request, tc);
            const clinical = result.results.clinical_logic;

            // risk_level 또는 overall_risk 필드에서 위험도 확인
            const actualRisk = clinical.risk_level
                || clinical.overall_risk
                || clinical.risk_assessment?.level;

            expect(actualRisk?.toUpperCase()).toBe(tc.expected.risk_level);
        });
    }
});

// ── TC-03: UI 통합 테스트 ──
test.describe('UI Integration', () => {
    test('테스트 페이지 로드 및 케이스 선택', async ({ page }) => {
        await page.goto(TEST_PAGE_URL);

        // 테스트 케이스 버튼 존재 확인
        await expect(page.locator('[data-case="chf"]')).toBeVisible();
        await expect(page.locator('[data-case="pneumonia"]')).toBeVisible();
        await expect(page.locator('[data-case="normal"]')).toBeVisible();

        // CHF 케이스 선택
        await page.click('[data-case="chf"]');

        // Run 버튼 활성화 확인
        const runBtn = page.locator('#runBtn');
        await expect(runBtn).toBeEnabled();
    });

    test('CHF 케이스 — 전체 파이프라인 실행', async ({ page }) => {
        await page.goto(TEST_PAGE_URL);
        await page.click('[data-case="chf"]');
        await page.click('#runBtn');

        // 폴링 상태 표시 확인
        await expect(page.locator('#pipelineStatus')).toContainText('RUNNING');

        // 결과 대기 (최대 120초)
        await expect(page.locator('#pipelineStatus')).toContainText('SUCCEEDED', {
            timeout: 120000,
        });

        // 결과 시각화 확인
        await expect(page.locator('#imageContainer')).toBeVisible();
        await expect(page.locator('#measurementsPanel')).toBeVisible();
        await expect(page.locator('#summarySection')).toBeVisible();
        await expect(page.locator('#reportSection')).toBeVisible();

        // 위험도 배지 확인
        await expect(page.locator('#riskBadge')).toContainText('URGENT');

        // CTR 값 존재 확인
        const ctrValue = await page.locator('#ctrValue').textContent();
        expect(parseFloat(ctrValue)).toBeGreaterThan(0);
    });

    test('이미지 오버레이 토글', async ({ page }) => {
        // ... 파이프라인 실행 후
        // 마스크 오버레이 ON/OFF
        await page.click('#btnOverlay');
        await expect(page.locator('#maskOverlay')).toBeHidden();
        await page.click('#btnOverlay');
        await expect(page.locator('#maskOverlay')).toBeVisible();
    });
});

// ── TC-04: 타이밍 검증 ──
test.describe('Performance', () => {
    test('전체 파이프라인 120초 이내 완료', async ({ request }) => {
        const start = Date.now();
        const result = await runFullPipeline(request, testCases.normal);
        const elapsed = (Date.now() - start) / 1000;

        expect(result.status).toBe('SUCCEEDED');
        expect(elapsed).toBeLessThan(120);
    });
});
```

#### 3.5.3 Playwright 설정

```javascript
// playwright.config.js
module.exports = {
    testDir: '.',
    timeout: 180000,        // 3분 (ML 파이프라인 대기)
    retries: 1,
    use: {
        baseURL: process.env.API_BASE_URL,
        extraHTTPHeaders: {
            'Content-Type': 'application/json',
        },
    },
    projects: [
        { name: 'api-tests', testMatch: /.*\.spec\.js/ },
    ],
};
```

---

## 4. 디렉토리 구조

```
deploy/v2/
├─ api-gateway/
│   ├─ setup-api-gw.sh                  # API Gateway + CORS 배포 스크립트
│   └─ status-lambda/
│       ├─ status_handler.py             # Status Lambda 핸들러
│       └─ requirements.txt              # boto3
│
├─ test-page/
│   ├─ index.html                        # v2 테스트 페이지 (단일 파일, ~1200줄)
│   └─ test-cases.json                   # 5개 테스트 케이스 데이터
│
├─ lambda_a/                             # (기존, 수정 없음)
├─ lambda_b/                             # (기존, 수정 없음)
├─ step_functions/                       # (기존, 수정 없음)
├─ shared/                               # (기존, 수정 없음)
└─ scripts/
    └─ deploy.sh                         # (기존) + API Gateway 배포 단계 추가

tests/e2e/
├─ playwright.config.js                  # Playwright 설정
├─ v2-pipeline.spec.js                   # E2E 테스트 (API + UI)
├─ test-cases.json                       # 테스트 데이터 (deploy/v2/test-page/ 심링크)
└─ helpers/
    └─ api-client.js                     # 폴링 헬퍼 함수
```

---

## 5. 데이터 흐름 상세

### 5.1 POST /analyze 요청 → Step Functions 매핑

```
API Gateway Request Body:
{
    "image_base64": "...",
    "patient_info": { ... }
}

↓ API Gateway Request Mapping Template:

{
    "input": "{\"image_base64\": $input.json('$.image_base64'), \"patient_info\": $input.json('$.patient_info')}",
    "stateMachineArn": "arn:aws:states:...:stateMachine:dr-ai-radiologist-pipeline-v2"
}

↓ Step Functions StartExecution

↓ API Gateway Response Mapping:

{
    "executionArn": "$input.json('$.executionArn')",
    "startDate": "$input.json('$.startDate')",
    "status": "RUNNING"
}
```

### 5.2 S3 Claim-Check 결과 구조

Step Functions 실행 후 S3에 저장되는 결과:

```
s3://bucket/runs/{run_id}/
├─ input.png              # 전처리된 입력 이미지 (Lambda A preprocess)
├─ seg.json               # 세그멘테이션 결과
│   ├─ mask_base64        # PNG 마스크 base64
│   ├─ measurements       # CTR, heart_width, lung_area 등
│   ├─ view               # PA/AP
│   ├─ age_pred           # 예측 나이
│   └─ sex_pred           # 예측 성별
├─ densenet.json          # DenseNet 분류 결과
│   └─ predictions[]      # [{disease, probability}, ...]
├─ yolo.json              # YOLO 탐지 결과
│   ├─ detections[]       # [{bbox, class_name, confidence}, ...]
│   └─ image_size         # [width, height]
└─ final_report.json      # Lambda B 최종 결과
    ├─ clinical_logic     # 임상 로직 분석
    ├─ rag_evidence       # RAG 검색 결과
    └─ report             # Bedrock 소견서
```

### 5.3 테스트 페이지 결과 매핑

Status Lambda가 반환하는 결과에서 UI 컴포넌트로의 매핑:

| API 응답 필드 | UI 컴포넌트 | 렌더링 |
|--------------|------------|--------|
| `results.seg.mask_base64` | 이미지 오버레이 | `<img>` base64 src |
| `results.seg.measurements` | CTR + 측정값 패널 | 수치 표시 |
| `results.densenet.predictions` | 질환 확률 (Layer Details) | 막대 차트 |
| `results.yolo.detections` | YOLO 바운딩박스 | SVG rect/text |
| `results.clinical_logic` | 임상 요약 + 위험도 | 태그 + 배지 |
| `results.rag_evidence` | RAG 근거 (Layer Details) | 텍스트 목록 |
| `results.report` | Bedrock 소견서 | 마크다운/HTML |
| `timing.totalSeconds` | 파이프라인 타이머 | 초 표시 |

---

## 6. 보안 고려사항

| 항목 | 대응 |
|------|------|
| API 접근 제어 | 테스트 단계: CORS만 설정, API Key 미적용 |
| S3 직접 접근 | Status Lambda가 S3 읽기 → 브라우저는 S3 직접 접근 안 함 |
| Execution ARN 노출 | 테스트 환경 한정, 프로덕션에서는 UUID 매핑 필요 |
| CORS 범위 | `Access-Control-Allow-Origin: *` (테스트용) |

---

## 7. 에러 처리

| 시나리오 | 처리 |
|---------|------|
| POST /analyze 실패 | 에러 배너 표시, 재시도 버튼 |
| 폴링 중 네트워크 에러 | 3회 재시도 후 에러 표시 |
| Step Functions FAILED | 에러 원인 표시 (Lambda 오류 메시지) |
| Step Functions TIMED_OUT | 타임아웃 메시지 + 재시도 안내 |
| S3 중간 결과 없음 | 해당 섹션 "Data unavailable" 표시 |
| CORS 에러 | API Gateway URL 설정 확인 안내 |

---

## 8. v1 → v2 기능 패리티 체크리스트

| v1 기능 | v2 대응 | 비고 |
|---------|---------|------|
| 5개 테스트 케이스 | ✅ 동일 | JSON 데이터 |
| 커스텀 이미지 업로드 | ✅ base64 인코딩 | 동일 |
| 세그멘테이션 마스크 오버레이 | ✅ S3에서 로드 | Claim-Check |
| YOLO 바운딩박스 | ✅ S3에서 로드 | Claim-Check |
| CTR + 해부학 측정값 | ✅ S3에서 로드 | seg.json |
| 파이프라인 진행 표시 | ⚠️ 폴링 기반 | 개별 레이어→3단계 |
| 임상 요약 + 위험도 | ✅ clinical_logic | 동일 |
| Bedrock 소견서 | ✅ report | 동일 |
| Layer Details 아코디언 | ✅ 재구성 | v2 구조 |
| Raw JSON | ✅ 전체 응답 | 통합 JSON |
| presigned URL (테스트 이미지) | ⚠️ 별도 구현 필요 | Status Lambda에 추가 |

---

## 9. 의존성

| 구성 요소 | 의존성 | 상태 |
|----------|--------|------|
| API Gateway | Step Functions ARN | deploy.sh에서 배포 |
| Status Lambda | S3 bucket, Step Functions | 새로 배포 |
| 테스트 페이지 | API Gateway URL | 배포 후 설정 |
| Playwright 테스트 | Node.js, @playwright/test | npm install |
| 테스트 이미지 | S3 `web/test-integrated/samples/` | v1에서 이미 업로드됨 |

---

## 10. 기술 스택

| 영역 | 기술 |
|------|------|
| API | AWS API Gateway REST, Step Functions |
| Backend | Python 3.12 (Status Lambda) |
| Frontend | HTML/CSS/JS (단일 파일, 프레임워크 없음) |
| 테스트 | Playwright (Node.js) |
| 인프라 | AWS CLI (setup-api-gw.sh) |

---

## 11. Implementation Guide

### 11.1 구현 순서

```
1. Status Lambda (status_handler.py + requirements.txt)
2. API Gateway 배포 스크립트 (setup-api-gw.sh)
3. 테스트 페이지 HTML (index.html)
4. 테스트 케이스 데이터 (test-cases.json)
5. Playwright 테스트 (v2-pipeline.spec.js + config + helpers)
6. deploy.sh 확장 (API Gateway 단계 추가)
```

### 11.2 모듈 맵

| Module | 파일 | 예상 라인 | 의존성 |
|--------|------|----------|--------|
| module-1 | `api-gateway/status-lambda/status_handler.py` | ~120줄 | boto3 |
| module-2 | `api-gateway/setup-api-gw.sh` | ~200줄 | AWS CLI, module-1 |
| module-3 | `test-page/index.html` | ~1200줄 | module-2 (API URL) |
| module-4 | `test-page/test-cases.json` | ~150줄 | 없음 |
| module-5 | `tests/e2e/v2-pipeline.spec.js` + config + helpers | ~300줄 | Playwright, module-2 |
| module-6 | `scripts/deploy.sh` 수정 | +30줄 | module-1,2 |

### 11.3 Session Guide

**권장 세션 분할:**

| 세션 | 범위 | 예상 | 설명 |
|------|------|------|------|
| Session 1 | module-1, module-2 | 인프라 | Status Lambda + API Gateway 배포 |
| Session 2 | module-3, module-4 | 프론트엔드 | 테스트 페이지 + 테스트 케이스 |
| Session 3 | module-5, module-6 | 테스트 | Playwright E2E + deploy.sh 확장 |

**단일 세션 가능:** 전체 ~2000줄, 한 세션에서 구현 가능
