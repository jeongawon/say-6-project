"""Fusion Decision Engine - Hard-coded clinical decision logic."""
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


class FusionDecisionEngine:
    """
    Hard-coded decision logic for multimodal fusion.
    
    Decision flow:
    1. Check if initial modalities are sufficient
    2. Analyze findings for high-risk patterns
    3. Determine if additional modalities needed
    4. Decide if LLM reasoning required
    5. Determine if ready for report generation
    """
    
    # Chief complaint to initial modality mapping
    CHIEF_COMPLAINT_MODALITY_MAP = {
        'chest pain': ['CXR', 'ECG'],
        'shortness of breath': ['CXR', 'ECG'],
        'dyspnea': ['CXR', 'ECG'],
        'abdominal pain': ['LAB', 'CXR'],
        'fever': ['LAB', 'CXR'],
        'trauma': ['CXR', 'LAB'],
        'altered mental status': ['LAB', 'ECG'],
        'syncope': ['ECG', 'LAB'],
        'headache': ['LAB'],
        'weakness': ['LAB', 'ECG']
    }
    
    # High-risk finding combinations requiring reasoning
    HIGH_RISK_PATTERNS = [
        {'CXR': ['pneumonia', 'infiltrate', 'consolidation'], 'LAB': ['elevated wbc', 'leukocytosis']},
        {'CXR': ['cardiomegaly', 'pulmonary edema'], 'ECG': ['st elevation', 'st depression']},
        {'ECG': ['st elevation', 'stemi'], 'LAB': ['elevated troponin']},
        {'CXR': ['pneumothorax'], 'ECG': ['arrhythmia']},
    ]
    
    # Confidence thresholds
    HIGH_CONFIDENCE = 0.85
    LOW_CONFIDENCE = 0.60
    MAX_ITERATIONS = 3
    
    def __init__(self, patient, modalities_completed, inference_results, iteration=1):
        self.patient = patient
        self.modalities_completed = modalities_completed
        self.inference_results = inference_results
        self.iteration = iteration
        self.chief_complaint = patient.get('chief_complaint', '').lower()
        
        # Index results by modality
        self.results_by_modality = {}
        for result in inference_results:
            modality = result.get('modality', '')
            self.results_by_modality[modality] = result
    
    def decide(self):
        """Main decision logic."""
        
        # Step 1: Check if we have any results yet
        if not self.inference_results:
            return self._initial_modality_selection()
        
        # Step 2: Check for high-risk patterns requiring reasoning
        if self._has_high_risk_pattern():
            return {
                'decision': 'NEED_REASONING',
                'rationale': 'High-risk pattern detected requiring clinical reasoning',
                'risk_level': 'high',
                'confidence_summary': self._get_confidence_summary()
            }
        
        # Step 3: Check if low confidence requires additional modalities
        if self._has_low_confidence() and self.iteration < self.MAX_ITERATIONS:
            next_modalities = self._suggest_next_modalities()
            if next_modalities:
                return {
                    'decision': 'CALL_NEXT_MODALITY',
                    'next_modalities': next_modalities,
                    'rationale': f'Low confidence detected, requesting additional modalities: {", ".join(next_modalities)}',
                    'risk_level': self._assess_risk_level(),
                    'confidence_summary': self._get_confidence_summary()
                }
        
        # Step 4: Check if findings suggest additional tests
        if self.iteration < self.MAX_ITERATIONS:
            suggested = self._suggest_based_on_findings()
            if suggested:
                return {
                    'decision': 'CALL_NEXT_MODALITY',
                    'next_modalities': suggested,
                    'rationale': f'Findings suggest additional tests needed: {", ".join(suggested)}',
                    'risk_level': self._assess_risk_level(),
                    'confidence_summary': self._get_confidence_summary()
                }
        
        # Step 5: Check if we need reasoning for complex cases
        if self._is_complex_case():
            return {
                'decision': 'NEED_REASONING',
                'rationale': 'Complex case requiring clinical reasoning synthesis',
                'risk_level': self._assess_risk_level(),
                'confidence_summary': self._get_confidence_summary()
            }
        
        # Step 6: Ready for report generation
        return {
            'decision': 'GENERATE_REPORT',
            'rationale': 'Sufficient information gathered for report generation',
            'risk_level': self._assess_risk_level(),
            'confidence_summary': self._get_confidence_summary()
        }
    
    def _initial_modality_selection(self):
        """Select initial modalities based on chief complaint."""
        modalities = []
        
        # Match chief complaint to modality map
        for key, mods in self.CHIEF_COMPLAINT_MODALITY_MAP.items():
            if key in self.chief_complaint:
                modalities = mods
                break
        
        # Default to CXR + LAB if no match
        if not modalities:
            modalities = ['CXR', 'LAB']
        
        return {
            'decision': 'CALL_NEXT_MODALITY',
            'next_modalities': modalities,
            'rationale': f'Initial modality selection based on chief complaint: {self.chief_complaint}',
            'risk_level': 'unknown',
            'confidence_summary': {}
        }
    
    def _has_high_risk_pattern(self):
        """Check if results match any high-risk patterns."""
        for pattern in self.HIGH_RISK_PATTERNS:
            matches = 0
            for modality, keywords in pattern.items():
                if modality in self.results_by_modality:
                    finding = self.results_by_modality[modality].get('finding', '').lower()
                    if any(kw in finding for kw in keywords):
                        matches += 1
            
            # If all modalities in pattern match
            if matches == len(pattern):
                logger.info(f"High-risk pattern detected: {pattern}")
                return True
        
        return False
    
    def _has_low_confidence(self):
        """Check if any result has low confidence."""
        for result in self.inference_results:
            confidence = result.get('confidence', 1.0)
            if confidence < self.LOW_CONFIDENCE:
                return True
        return False
    
    def _suggest_next_modalities(self):
        """Suggest next modalities based on what's missing."""
        all_modalities = ['CXR', 'ECG', 'LAB']
        remaining = [m for m in all_modalities if m not in self.modalities_completed]
        
        # Prioritize based on chief complaint
        if 'chest' in self.chief_complaint or 'cardiac' in self.chief_complaint:
            if 'ECG' in remaining:
                return ['ECG']
        
        if 'infection' in self.chief_complaint or 'fever' in self.chief_complaint:
            if 'LAB' in remaining:
                return ['LAB']
        
        # Return first remaining modality
        return remaining[:1] if remaining else []
    
    def _suggest_based_on_findings(self):
        """Suggest modalities based on current findings."""
        suggestions = []
        
        # Check CXR findings
        if 'CXR' in self.results_by_modality:
            cxr_finding = self.results_by_modality['CXR'].get('finding', '').lower()
            
            if any(kw in cxr_finding for kw in ['cardiac', 'cardiomegaly', 'heart']):
                if 'ECG' not in self.modalities_completed:
                    suggestions.append('ECG')
            
            if any(kw in cxr_finding for kw in ['infection', 'pneumonia', 'infiltrate']):
                if 'LAB' not in self.modalities_completed:
                    suggestions.append('LAB')
        
        # Check ECG findings
        if 'ECG' in self.results_by_modality:
            ecg_finding = self.results_by_modality['ECG'].get('finding', '').lower()
            
            if any(kw in ecg_finding for kw in ['ischemia', 'infarction', 'st elevation']):
                if 'LAB' not in self.modalities_completed:
                    suggestions.append('LAB')
                if 'CXR' not in self.modalities_completed:
                    suggestions.append('CXR')
        
        # Check LAB findings
        if 'LAB' in self.results_by_modality:
            lab_finding = self.results_by_modality['LAB'].get('finding', '').lower()
            
            if any(kw in lab_finding for kw in ['elevated troponin', 'cardiac markers']):
                if 'ECG' not in self.modalities_completed:
                    suggestions.append('ECG')
        
        return suggestions
    
    def _is_complex_case(self):
        """Determine if case is complex enough to need reasoning."""
        # Multiple modalities with mixed findings
        if len(self.inference_results) >= 2:
            findings = [r.get('finding', '').lower() for r in self.inference_results]
            
            # Check for conflicting or complex findings
            has_abnormal = any(
                any(kw in f for kw in ['abnormal', 'elevated', 'positive', 'detected'])
                for f in findings
            )
            
            if has_abnormal:
                return True
        
        return False
    
    def _assess_risk_level(self):
        """Assess overall risk level based on findings."""
        if not self.inference_results:
            return 'unknown'
        
        # Check for high-risk keywords
        high_risk_keywords = [
            'stemi', 'st elevation', 'pneumothorax', 'massive', 'severe',
            'critical', 'acute', 'emergency'
        ]
        
        medium_risk_keywords = [
            'pneumonia', 'infiltrate', 'cardiomegaly', 'arrhythmia',
            'elevated', 'abnormal'
        ]
        
        all_findings = ' '.join([r.get('finding', '').lower() for r in self.inference_results])
        
        if any(kw in all_findings for kw in high_risk_keywords):
            return 'high'
        elif any(kw in all_findings for kw in medium_risk_keywords):
            return 'medium'
        else:
            return 'low'
    
    def _get_confidence_summary(self):
        """Get confidence summary for all modalities."""
        summary = {}
        for result in self.inference_results:
            modality = result.get('modality', 'unknown')
            confidence = result.get('confidence', 0.0)
            summary[modality] = confidence
        return summary
