"""Fusion Decision Lambda - Combines multimodal results and decides next action."""
import json
import logging
from decision_engine import FusionDecisionEngine

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    """
    Analyze multimodal inference results and decide next action.
    
    Returns:
        - decision: CALL_NEXT_MODALITY | NEED_REASONING | GENERATE_REPORT
        - next_modalities: List of modalities to call (if CALL_NEXT_MODALITY)
        - rationale: Explanation of decision
    """
    case_id = event.get('case_id', 'unknown')
    patient = event.get('patient', {})
    modalities_completed = event.get('modalities_completed', [])
    inference_results = event.get('inference_results', [])
    iteration = event.get('iteration', 1)
    
    logger.info(f"Fusion decision for case {case_id}, iteration {iteration}")
    logger.info(f"Completed modalities: {modalities_completed}")
    logger.info(f"Results count: {len(inference_results)}")
    
    # Initialize decision engine
    engine = FusionDecisionEngine(
        patient=patient,
        modalities_completed=modalities_completed,
        inference_results=inference_results,
        iteration=iteration
    )
    
    # Make decision
    decision_result = engine.decide()
    
    logger.info(f"Decision: {decision_result['decision']} - {decision_result['rationale']}")
    
    return {
        "case_id": case_id,
        "decision": decision_result['decision'],
        "next_modalities": decision_result.get('next_modalities', []),
        "rationale": decision_result['rationale'],
        "confidence_summary": decision_result.get('confidence_summary', {}),
        "risk_level": decision_result.get('risk_level', 'unknown'),
        "iteration": iteration
    }
