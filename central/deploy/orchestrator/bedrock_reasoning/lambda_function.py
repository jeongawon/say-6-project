"""Bedrock Clinical Reasoning Lambda - LLM-based clinical reasoning."""
import json
import logging
import boto3
import os

logger = logging.getLogger()
logger.setLevel(logging.INFO)

bedrock = boto3.client('bedrock-runtime')
MODEL_ID = 'anthropic.claude-3-5-sonnet-20241022-v2:0'


def handler(event, context):
    """
    Use Bedrock Claude to provide clinical reasoning based on multimodal findings.
    
    This is called when:
    - High-risk patterns are detected
    - Complex cases need synthesis
    - Additional clinical context is needed
    """
    case_id = event.get('case_id', 'unknown')
    patient = event.get('patient', {})
    inference_results = event.get('inference_results', [])
    fusion = event.get('fusion', {})
    
    logger.info(f"Bedrock reasoning for case {case_id}")
    
    # Build prompt
    prompt = build_reasoning_prompt(patient, inference_results, fusion)
    
    # Call Bedrock
    try:
        response = bedrock.invoke_model(
            modelId=MODEL_ID,
            contentType='application/json',
            accept='application/json',
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1000,
                "temperature": 0.3,
                "messages": [{"role": "user", "content": prompt}]
            })
        )
        
        result = json.loads(response['body'].read())
        reasoning = result['content'][0]['text']
        
        logger.info(f"Reasoning generated successfully for case {case_id}")
        
    except Exception as e:
        logger.error(f"Bedrock error: {e}")
        reasoning = generate_fallback_reasoning(patient, inference_results, fusion)
    
    return {
        "case_id": case_id,
        "reasoning": reasoning,
        "reasoning_source": "bedrock" if 'result' in locals() else "fallback"
    }


def build_reasoning_prompt(patient, inference_results, fusion):
    """Build clinical reasoning prompt for Bedrock."""
    
    # Patient context
    chief_complaint = patient.get('chief_complaint', 'Not specified')
    vitals = patient.get('vitals', {})
    age = patient.get('age', 'Unknown')
    sex = patient.get('sex', 'Unknown')
    
    vitals_text = ', '.join([f"{k}: {v}" for k, v in vitals.items()]) if vitals else 'Not provided'
    
    # Findings summary
    findings_text = []
    for result in inference_results:
        modality = result.get('modality', 'Unknown')
        finding = result.get('finding', 'No finding')
        confidence = result.get('confidence', 0.0)
        rationale = result.get('rationale', 'N/A')
        details = result.get('details', {})
        
        findings_text.append(f"""
{modality} Results:
- Finding: {finding}
- Confidence: {confidence:.2f}
- Rationale: {rationale}
- Details: {json.dumps(details, indent=2)}
""")
    
    findings_combined = '\n'.join(findings_text)
    
    # Fusion context
    fusion_rationale = fusion.get('rationale', 'N/A')
    risk_level = fusion.get('risk_level', 'unknown')
    
    prompt = f"""You are an emergency medicine clinical decision support AI. Analyze the following multimodal diagnostic findings and provide clinical reasoning.

PATIENT INFORMATION:
- Age: {age}
- Sex: {sex}
- Chief Complaint: {chief_complaint}
- Vitals: {vitals_text}

MULTIMODAL FINDINGS:
{findings_combined}

FUSION ANALYSIS:
- Risk Level: {risk_level}
- Rationale: {fusion_rationale}

TASK:
Provide a concise clinical reasoning summary (5-7 sentences) that:
1. Synthesizes the multimodal findings into a coherent clinical picture
2. Identifies the most likely diagnosis or differential diagnoses
3. Explains how the findings support or contradict each other
4. Highlights any critical findings requiring immediate attention
5. Suggests next steps in management or additional tests if needed

Focus on emergency medicine context and time-sensitive decision making. Be specific and actionable.

Respond in plain text only, no markdown formatting."""

    return prompt


def generate_fallback_reasoning(patient, inference_results, fusion):
    """Generate fallback reasoning if Bedrock fails."""
    
    chief_complaint = patient.get('chief_complaint', 'unknown complaint')
    risk_level = fusion.get('risk_level', 'unknown')
    
    findings_summary = []
    for result in inference_results:
        modality = result.get('modality', 'Unknown')
        finding = result.get('finding', 'No finding')
        findings_summary.append(f"{modality}: {finding}")
    
    findings_text = '; '.join(findings_summary)
    
    reasoning = f"""Clinical Reasoning (Fallback):

Patient presents with {chief_complaint}. Multimodal analysis reveals: {findings_text}.

Risk assessment indicates {risk_level} risk level. The combination of findings suggests a need for comprehensive evaluation. 

Recommend correlation with clinical presentation and consideration of additional diagnostic workup as indicated. Close monitoring and timely intervention are advised based on the emergency context.

Further clinical correlation and specialist consultation may be warranted depending on patient trajectory."""
    
    return reasoning
