"""Report Generator Lambda - RAG-based clinical report generation."""
import json
import logging
import os
import boto3
from datetime import datetime
from rag.rag_service import RAGService
from bedrock_report.report_generator import ReportGenerator

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client('s3')
CASE_BUCKET = os.environ['CASE_BUCKET']
RAG_BUCKET = os.environ.get('RAG_BUCKET', '')

# Initialize services (lazy loading)
rag_service = None
report_generator = None


def handler(event, context):
    """
    Generate final clinical report using RAG and Bedrock.
    
    Steps:
    1. Retrieve relevant clinical notes from RAG (MIMIC-NOTE, MIMIC-CXR)
    2. Use Bedrock to generate comprehensive report
    3. Store report in S3
    4. Return final response
    """
    global rag_service, report_generator
    
    case_id = event.get('case_id', 'unknown')
    patient = event.get('patient', {})
    inference_results = event.get('inference_results', [])
    reasoning = event.get('reasoning', {})
    fusion = event.get('fusion', {})
    workflow_history = event.get('workflow_history', [])
    
    logger.info(f"Generating report for case {case_id}")
    
    # Initialize services if needed
    if rag_service is None and RAG_BUCKET:
        try:
            rag_service = RAGService(RAG_BUCKET)
            logger.info("RAG service initialized")
        except Exception as e:
            logger.warning(f"RAG service initialization failed: {e}, continuing without RAG")
    
    if report_generator is None:
        report_generator = ReportGenerator()
    
    # Retrieve relevant clinical notes via RAG
    rag_context = []
    if rag_service:
        try:
            query = build_rag_query(patient, inference_results)
            rag_context = rag_service.search(query, top_k=5)
            logger.info(f"Retrieved {len(rag_context)} relevant clinical notes")
        except Exception as e:
            logger.error(f"RAG search failed: {e}")
    
    # Generate report using Bedrock
    try:
        report = report_generator.generate(
            case_id=case_id,
            patient=patient,
            inference_results=inference_results,
            reasoning=reasoning.get('body', {}) if reasoning else {},
            fusion=fusion,
            rag_context=rag_context,
            workflow_history=workflow_history
        )
        
        logger.info(f"Report generated successfully for case {case_id}")
        
    except Exception as e:
        logger.error(f"Report generation failed: {e}")
        report = generate_fallback_report(
            case_id, patient, inference_results, reasoning, fusion
        )
    
    # Store report in S3
    try:
        output_data = {
            "case_id": case_id,
            "patient": patient,
            "inference_results": inference_results,
            "reasoning": reasoning.get('body', {}) if reasoning else {},
            "fusion": fusion,
            "report": report,
            "workflow_history": workflow_history,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        s3.put_object(
            Bucket=CASE_BUCKET,
            Key=f"cases/{case_id}/output.json",
            Body=json.dumps(output_data, indent=2),
            ContentType='application/json'
        )
        
        logger.info(f"Report stored in S3 for case {case_id}")
        
    except Exception as e:
        logger.error(f"Failed to store report in S3: {e}")
    
    # Return final response
    return {
        "case_id": case_id,
        "status": "completed",
        "report": report,
        "modalities_used": [r.get('modality') for r in inference_results],
        "risk_level": fusion.get('risk_level', 'unknown'),
        "timestamp": datetime.utcnow().isoformat()
    }


def build_rag_query(patient, inference_results):
    """Build search query for RAG system."""
    chief_complaint = patient.get('chief_complaint', '')
    
    findings = []
    for result in inference_results:
        modality = result.get('modality', '')
        finding = result.get('finding', '')
        findings.append(f"{modality}: {finding}")
    
    query = f"{chief_complaint}. {' '.join(findings)}"
    return query


def generate_fallback_report(case_id, patient, inference_results, reasoning, fusion):
    """Generate fallback report if Bedrock fails."""
    
    chief_complaint = patient.get('chief_complaint', 'Not specified')
    age = patient.get('age', 'Unknown')
    sex = patient.get('sex', 'Unknown')
    
    findings_text = []
    for result in inference_results:
        modality = result.get('modality', 'Unknown')
        finding = result.get('finding', 'No finding')
        findings_text.append(f"- {modality}: {finding}")
    
    findings_combined = '\n'.join(findings_text)
    
    reasoning_text = reasoning.get('body', {}).get('reasoning', 'Not available') if reasoning else 'Not available'
    
    report = f"""EMERGENCY DEPARTMENT CLINICAL REPORT (Fallback)

CASE ID: {case_id}
DATE: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}

PATIENT INFORMATION:
- Age: {age}
- Sex: {sex}
- Chief Complaint: {chief_complaint}

MULTIMODAL FINDINGS:
{findings_combined}

CLINICAL REASONING:
{reasoning_text}

IMPRESSION:
Multimodal diagnostic evaluation completed. Please review all findings in clinical context.

RECOMMENDATIONS:
- Correlate with clinical presentation
- Consider additional workup as indicated
- Follow institutional protocols for management

Note: This is an automated fallback report. Please review all source data."""

    return report
