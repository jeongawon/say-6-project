"""
상태 조회 Lambda — 프론트엔드가 폴링하는 엔드포인트

프론트엔드가 2초마다 호출하여 파이프라인 진행 상태를 확인.
DynamoDB에서 request_id로 현재 상태를 조회하여 반환.

호출: GET /status?request_id=req_001
응답: {"request_id": "req_001", "progress": 40, "status": "detection_done", ...}
"""

import json
import os
import boto3
from decimal import Decimal

dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-2')
TABLE_NAME = os.environ.get('STATUS_TABLE', 'chest-xray-modal-status')


class DecimalEncoder(json.JSONEncoder):
    """DynamoDB Decimal → float 변환"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def lambda_handler(event, context):
    """
    상태 조회 핸들러

    event (API Gateway):
        queryStringParameters: {"request_id": "req_001"}

    event (직접 호출):
        {"request_id": "req_001"}
    """
    # request_id 추출
    if 'queryStringParameters' in event and event['queryStringParameters']:
        request_id = event['queryStringParameters'].get('request_id')
    else:
        request_id = event.get('request_id')

    if not request_id:
        return {
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'request_id 필수'})
        }

    # DynamoDB 조회
    table = dynamodb.Table(TABLE_NAME)
    response = table.get_item(Key={'request_id': request_id})

    if 'Item' not in response:
        return {
            'statusCode': 404,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': f'요청 {request_id} 없음'})
        }

    item = response['Item']

    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
        'body': json.dumps(item, cls=DecimalEncoder, ensure_ascii=False)
    }
