"""
Layer 6 Bedrock Report Lambda - 개별 엔드포인트
GPU 불필요. Bedrock API 호출만.

입력 모드:
  1) "scenario"  -> 내장 mock 시나리오 (chf/pneumonia/tension_pneumo/normal)
  2) "generate"  -> 사용자가 Layer 1~5 결과를 직접 전달하여 소견서 생성
  3) "list_scenarios" -> 사용 가능한 시나리오 목록

출력: 구조화된 소견서 + 서술형 판독문 + 요약 + 권고 조치

GET  -> 테스트 페이지 (index.html)
POST -> Bedrock Report API
"""
import os
import json
import time
import traceback

from layer6_bedrock_report.config import Config
from layer6_bedrock_report.report_generator import BedrockReportGenerator
from layer6_bedrock_report.mock_data import SCENARIOS

# 글로벌 싱글턴
config = Config()
generator = BedrockReportGenerator(config)


# ================================================================
# Lambda 핸들러
# ================================================================
def serve_html():
    """테스트 페이지 HTML 반환"""
    html_path = os.path.join(os.path.dirname(__file__), 'index.html')
    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()
    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'text/html; charset=utf-8'},
        'body': html,
    }


def handler(event, context):
    """Lambda 핸들러 - GET: 테스트 페이지, POST: Report Generation API"""
    method = event.get('requestContext', {}).get('http', {}).get('method', 'POST')

    if method == 'GET':
        return serve_html()

    try:
        body = event
        if isinstance(event.get('body'), str):
            body = json.loads(event['body'])
        elif isinstance(event.get('body'), dict):
            body = event['body']

        action = body.get('action', 'scenario')
        start = time.time()

        # ---- 시나리오 목록 ----
        if action == 'list_scenarios':
            scenarios = {
                k: {"name": v["name"], "description": v["description"]}
                for k, v in SCENARIOS.items()
            }
            return _ok({'scenarios': scenarios})

        # ---- 시나리오 실행 ----
        if action == 'scenario':
            scenario_id = body.get('scenario', 'chf')
            if scenario_id not in SCENARIOS:
                return _error(400, f'Unknown scenario: {scenario_id}',
                              available=list(SCENARIOS.keys()))

            event_data = SCENARIOS[scenario_id]["input"]
            # 언어/포맷 오버라이드
            if body.get("report_language"):
                event_data = dict(event_data)
                event_data["report_language"] = body["report_language"]

            report = generator.generate_report(event_data)
            elapsed = round(time.time() - start, 3)

            return _ok({
                'mode': f'scenario:{scenario_id}',
                'scenario_name': SCENARIOS[scenario_id]["name"],
                'report': report,
                'processing_time_sec': elapsed,
            })

        # ---- 직접 입력으로 소견서 생성 ----
        if action == 'generate':
            report = generator.generate_report(body)
            elapsed = round(time.time() - start, 3)

            return _ok({
                'mode': 'generate',
                'report': report,
                'processing_time_sec': elapsed,
            })

        return _error(400, f'Unknown action: {action}',
                      available=['list_scenarios', 'scenario', 'generate'])

    except Exception as e:
        print(traceback.format_exc())
        return _error(500, str(e))


def _ok(data):
    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'application/json'},
        'body': json.dumps(data, ensure_ascii=False, default=str),
    }


def _error(code, message, **kwargs):
    body = {'error': message}
    body.update(kwargs)
    return {
        'statusCode': code,
        'headers': {'Content-Type': 'application/json'},
        'body': json.dumps(body, ensure_ascii=False),
    }
