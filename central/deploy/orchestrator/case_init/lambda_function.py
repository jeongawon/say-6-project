"""Case Initialization Lambda - API Gateway entry point."""
import json
import uuid
import os
import logging
import boto3
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client('s3')
sfn = boto3.client('stepfunctions')

BUCKET = os.environ['CASE_BUCKET']
STATE_MACHINE_ARN = os.environ['STATE_MACHINE_ARN']


def handler(event, context):
    """
    Handle incoming case requests from API Gateway.
    
    POST /case: Create new case
    GET /case/{case_id}: Get case status/result
    """
    http_method = event.get('httpMethod', 'POST')
    
    if http_method == 'GET':
        return handle_get_case(event)
    else:
        return handle_create_case(event)


def handle_create_case(event):
    """Create new emergency case and start orchestration."""
    logger.info("Case Init invoked")

    # Parse body from API Gateway
    body = event.get('body')
    if isinstance(body, str):
        body = json.loads(body)
    elif body is None:
        body = event

    # Generate case ID
    case_id = str(uuid.uuid4())[:8]
    
    # Extract patient information
    patient = body.get('patient', {})
    chief_complaint = patient.get('chief_complaint', '')
    vitals = patient.get('vitals', {})
    
    # Validate required fields
    if not chief_complaint:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "error": "chief_complaint is required"
            })
        }

    case_data = {
        "case_id": case_id,
        "patient": patient,
        "status": "initiated",
        "timestamp": datetime.utcnow().isoformat(),
        "modalities_completed": [],
        "workflow_history": []
    }

    # Store input in S3
    try:
        s3.put_object(
            Bucket=BUCKET,
            Key=f"cases/{case_id}/input.json",
            Body=json.dumps(case_data, indent=2),
            ContentType='application/json'
        )
        logger.info(f"Case {case_id} stored in S3")
    except Exception as e:
        logger.error(f"S3 error: {e}")
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Failed to store case data"})
        }

    # Start Step Functions execution
    try:
        sfn_response = sfn.start_execution(
            stateMachineArn=STATE_MACHINE_ARN,
            name=f"case-{case_id}-{int(datetime.utcnow().timestamp())}",
            input=json.dumps(case_data)
        )
        execution_arn = sfn_response['executionArn']
        logger.info(f"Step Functions execution started: {execution_arn}")
    except Exception as e:
        logger.error(f"Step Functions error: {e}")
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Failed to start orchestration"})
        }

    # Return immediate response (async processing)
    return {
        "statusCode": 202,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "case_id": case_id,
            "status": "processing",
            "execution_arn": execution_arn,
            "message": "Case initiated. Use GET /case/{case_id} to check status."
        })
    }


def handle_get_case(event):
    """Get case status and results."""
    path_params = event.get('pathParameters', {})
    case_id = path_params.get('case_id')
    
    if not case_id:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "case_id is required"})
        }
    
    # Try to get output from S3
    try:
        response = s3.get_object(
            Bucket=BUCKET,
            Key=f"cases/{case_id}/output.json"
        )
        output_data = json.loads(response['Body'].read())
        
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "case_id": case_id,
                "status": "completed",
                "result": output_data
            })
        }
    except s3.exceptions.NoSuchKey:
        # Output not ready yet, check if input exists
        try:
            s3.head_object(Bucket=BUCKET, Key=f"cases/{case_id}/input.json")
            return {
                "statusCode": 202,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({
                    "case_id": case_id,
                    "status": "processing",
                    "message": "Case is still being processed"
                })
            }
        except:
            return {
                "statusCode": 404,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({
                    "error": "Case not found"
                })
            }
    except Exception as e:
        logger.error(f"Error retrieving case: {e}")
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Failed to retrieve case"})
        }
