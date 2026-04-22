"""Prompt templates for clinical report generation."""
import json
from datetime import datetime


def build_report_prompt(case_id, patient, inference_results, reasoning, fusion, rag_context, workflow_history):
    """Build comprehensive prompt for report generation."""
    
    # Patient section
    patient_section = format_patient_info(patient)
    
    # Multimodal findings section
    findings_section = format_findings(inference_results)
    
    # Clinical reasoning section
    reasoning_section = format_reasoning(reasoning)
    
    # RAG context section
    rag_section = format_rag_context(rag_context)
    
    # Workflow section
    workflow_section = format_workflow(workflow_history)
    
    # Risk assessment
    risk_level = fusion.get('risk_level', 'unknown')
    
    prompt = f"""You are an emergency medicine physician generating a clinical report based on multimodal diagnostic findings and AI-assisted analysis.

CASE ID: {case_id}
DATE: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}

{patient_section}

{findings_section}

{reasoning_section}

{rag_section}

RISK ASSESSMENT: {risk_level.upper()}

{workflow_section}

TASK:
Generate a comprehensive emergency department clinical report in the following format:

1. CHIEF COMPLAINT
   - Brief statement of presenting complaint

2. MULTIMODAL DIAGNOSTIC FINDINGS
   - Summarize key findings from each modality (CXR, ECG, LAB)
   - Highlight critical or time-sensitive findings

3. CLINICAL SYNTHESIS
   - Integrate findings into coherent clinical picture
   - Discuss how findings support or contradict each other
   - Identify most likely diagnosis or differential diagnoses

4. IMPRESSION
   - Primary diagnosis or working diagnosis
   - Differential diagnoses if applicable
   - Severity assessment

5. RECOMMENDATIONS
   - Immediate management steps
   - Additional diagnostic workup if needed
   - Consultation recommendations
   - Disposition (admit, observe, discharge with follow-up)

6. CRITICAL ACTIONS
   - Time-sensitive interventions required
   - Safety considerations

GUIDELINES:
- Write in clear, professional medical language
- Be specific and actionable
- Prioritize emergency medicine context
- Highlight time-sensitive findings
- Use standard medical terminology
- Keep report concise but comprehensive (aim for 400-600 words)
- Do NOT use markdown formatting, use plain text only

Generate the report now:"""

    return prompt


def format_patient_info(patient):
    """Format patient information section."""
    age = patient.get('age', 'Unknown')
    sex = patient.get('sex', 'Unknown')
    chief_complaint = patient.get('chief_complaint', 'Not specified')
    vitals = patient.get('vitals', {})
    
    vitals_text = []
    if vitals:
        for key, value in vitals.items():
            vitals_text.append(f"  - {key}: {value}")
    
    vitals_formatted = '\n'.join(vitals_text) if vitals_text else '  - Not provided'
    
    return f"""PATIENT INFORMATION:
- Age: {age}
- Sex: {sex}
- Chief Complaint: {chief_complaint}
- Vital Signs:
{vitals_formatted}"""


def format_findings(inference_results):
    """Format multimodal findings section."""
    if not inference_results:
        return "MULTIMODAL FINDINGS:\n- No findings available"
    
    findings_text = []
    for result in inference_results:
        modality = result.get('modality', 'Unknown')
        finding = result.get('finding', 'No finding')
        confidence = result.get('confidence', 0.0)
        rationale = result.get('rationale', 'N/A')
        details = result.get('details', {})
        
        findings_text.append(f"""
{modality} FINDINGS:
- Finding: {finding}
- Confidence: {confidence:.2f}
- Rationale: {rationale}
- Key Details: {json.dumps(details.get('key_findings', []), indent=2) if 'key_findings' in details else 'N/A'}
""")
    
    return "MULTIMODAL FINDINGS:\n" + '\n'.join(findings_text)


def format_reasoning(reasoning):
    """Format clinical reasoning section."""
    if not reasoning or not reasoning.get('reasoning'):
        return "CLINICAL REASONING:\n- Not available"
    
    reasoning_text = reasoning.get('reasoning', 'Not available')
    source = reasoning.get('reasoning_source', 'unknown')
    
    return f"""CLINICAL REASONING (Source: {source}):
{reasoning_text}"""


def format_rag_context(rag_context):
    """Format RAG retrieved context section."""
    if not rag_context:
        return "SIMILAR CLINICAL CASES:\n- No similar cases retrieved"
    
    context_text = []
    for i, doc in enumerate(rag_context[:3], 1):  # Top 3 only
        text = doc.get('text', '')[:200]  # Truncate
        source = doc.get('source', 'unknown')
        score = doc.get('score', 0.0)
        
        context_text.append(f"""
Case {i} (Source: {source}, Relevance: {score:.2f}):
{text}...
""")
    
    return "SIMILAR CLINICAL CASES (from MIMIC database):\n" + '\n'.join(context_text)


def format_workflow(workflow_history):
    """Format workflow execution history."""
    if not workflow_history:
        return "WORKFLOW SUMMARY:\n- Single-pass evaluation"
    
    iterations = len(workflow_history)
    decisions = [w.get('decision', 'unknown') for w in workflow_history]
    
    return f"""WORKFLOW SUMMARY:
- Total iterations: {iterations}
- Decision path: {' → '.join(decisions)}
- Modalities called dynamically based on findings"""
