"""Bedrock-based clinical report generator."""
import json
import logging
import boto3
from .prompt_templates import build_report_prompt

logger = logging.getLogger()
logger.setLevel(logging.INFO)

bedrock = boto3.client('bedrock-runtime')
MODEL_ID = 'anthropic.claude-3-5-sonnet-20241022-v2:0'


class ReportGenerator:
    """Generate clinical reports using Bedrock Claude."""
    
    def __init__(self, model_id=None):
        self.model_id = model_id or MODEL_ID
    
    def generate(self, case_id, patient, inference_results, reasoning, fusion, rag_context, workflow_history):
        """
        Generate comprehensive clinical report.
        
        Args:
            case_id: Case identifier
            patient: Patient information
            inference_results: List of modal inference results
            reasoning: Clinical reasoning from Bedrock
            fusion: Fusion decision information
            rag_context: Retrieved clinical notes from RAG
            workflow_history: Workflow execution history
        
        Returns:
            Formatted clinical report string
        """
        # Build prompt
        prompt = build_report_prompt(
            case_id=case_id,
            patient=patient,
            inference_results=inference_results,
            reasoning=reasoning,
            fusion=fusion,
            rag_context=rag_context,
            workflow_history=workflow_history
        )
        
        # Call Bedrock
        try:
            response = bedrock.invoke_model(
                modelId=self.model_id,
                contentType='application/json',
                accept='application/json',
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 2000,
                    "temperature": 0.3,
                    "messages": [{"role": "user", "content": prompt}]
                })
            )
            
            result = json.loads(response['body'].read())
            report = result['content'][0]['text']
            
            logger.info(f"Report generated successfully for case {case_id}")
            return report
            
        except Exception as e:
            logger.error(f"Bedrock report generation failed: {e}")
            raise
