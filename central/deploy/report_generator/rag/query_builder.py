"""Query builder for RAG system."""


def build_query(patient, inference_results, focus='comprehensive'):
    """
    Build optimized query for RAG retrieval.
    
    Args:
        patient: Patient information dict
        inference_results: List of modal inference results
        focus: 'comprehensive' | 'diagnosis' | 'treatment'
    
    Returns:
        Optimized query string
    """
    chief_complaint = patient.get('chief_complaint', '')
    age = patient.get('age', '')
    sex = patient.get('sex', '')
    
    # Extract key findings
    findings = []
    for result in inference_results:
        modality = result.get('modality', '')
        finding = result.get('finding', '')
        
        # Extract key terms from finding
        key_terms = extract_key_terms(finding)
        if key_terms:
            findings.extend(key_terms)
    
    # Build query based on focus
    if focus == 'diagnosis':
        query = f"{chief_complaint} {' '.join(findings[:3])}"
    elif focus == 'treatment':
        query = f"management treatment {chief_complaint} {' '.join(findings[:2])}"
    else:  # comprehensive
        demographics = f"{age} year old {sex}" if age and sex else ""
        query = f"{demographics} {chief_complaint} {' '.join(findings[:5])}"
    
    return query.strip()


def extract_key_terms(text):
    """Extract key medical terms from text."""
    # Simple keyword extraction (can be enhanced with NLP)
    keywords = []
    
    # Common medical terms to extract
    important_terms = [
        'pneumonia', 'cardiomegaly', 'edema', 'infiltrate', 'consolidation',
        'stemi', 'st elevation', 'arrhythmia', 'fibrillation',
        'elevated', 'troponin', 'leukocytosis', 'wbc',
        'fracture', 'pneumothorax', 'effusion'
    ]
    
    text_lower = text.lower()
    for term in important_terms:
        if term in text_lower:
            keywords.append(term)
    
    return keywords
