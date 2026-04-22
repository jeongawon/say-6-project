"""
Full workflow simulation - simulates the entire Step Functions orchestration locally.
"""
import json
import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'deploy'))

from orchestrator.fusion_decision.decision_engine import FusionDecisionEngine


class MockModalConnector:
    """Mock modal connector that simulates API calls"""
    
    @staticmethod
    def call_cxr(patient):
        chief_complaint = patient.get('chief_complaint', '').lower()
        
        if 'chest pain' in chief_complaint or 'cardiac' in chief_complaint:
            return {
                "modality": "CXR",
                "finding": "Cardiomegaly with possible pulmonary edema",
                "confidence": 0.82,
                "details": {
                    "diseases": ["Cardiomegaly", "Pulmonary Edema"],
                    "key_findings": [
                        "Enlarged cardiac silhouette",
                        "Bilateral perihilar opacities"
                    ]
                },
                "rationale": "Chest X-ray shows enlarged heart with signs of fluid overload"
            }
        elif 'shortness of breath' in chief_complaint or 'dyspnea' in chief_complaint:
            return {
                "modality": "CXR",
                "finding": "Right lower lobe pneumonia",
                "confidence": 0.88,
                "details": {
                    "diseases": ["Pneumonia"],
                    "key_findings": [
                        "Right lower lobe consolidation",
                        "Air bronchograms present"
                    ]
                },
                "rationale": "Consolidation pattern consistent with bacterial pneumonia"
            }
        else:
            return {
                "modality": "CXR",
                "finding": "No acute cardiopulmonary abnormality",
                "confidence": 0.89,
                "details": {"key_findings": ["Clear lung fields"]},
                "rationale": "Chest X-ray within normal limits"
            }
    
    @staticmethod
    def call_ecg(patient):
        chief_complaint = patient.get('chief_complaint', '').lower()
        
        if 'chest pain' in chief_complaint or 'cardiac' in chief_complaint:
            return {
                "modality": "ECG",
                "finding": "ST elevation in leads II, III, aVF - Inferior STEMI",
                "confidence": 0.93,
                "details": {
                    "rhythm": "Sinus rhythm",
                    "rate": 88,
                    "key_findings": [
                        "ST elevation in inferior leads",
                        "Q waves in III, aVF"
                    ]
                },
                "rationale": "ECG findings consistent with acute inferior myocardial infarction"
            }
        elif 'syncope' in chief_complaint or 'palpitation' in chief_complaint:
            return {
                "modality": "ECG",
                "finding": "Atrial fibrillation with rapid ventricular response",
                "confidence": 0.91,
                "details": {
                    "rhythm": "Atrial fibrillation",
                    "rate": 142,
                    "key_findings": ["Irregularly irregular rhythm", "Absent P waves"]
                },
                "rationale": "ECG shows atrial fibrillation requiring rate control"
            }
        else:
            return {
                "modality": "ECG",
                "finding": "Normal sinus rhythm, no acute changes",
                "confidence": 0.92,
                "details": {
                    "rhythm": "Normal sinus rhythm",
                    "rate": 78,
                    "key_findings": ["Normal sinus rhythm", "No ST-T wave abnormalities"]
                },
                "rationale": "ECG within normal limits"
            }
    
    @staticmethod
    def call_lab(patient):
        chief_complaint = patient.get('chief_complaint', '').lower()
        
        if 'chest pain' in chief_complaint or 'cardiac' in chief_complaint:
            return {
                "modality": "LAB",
                "finding": "Elevated troponin, consistent with myocardial injury",
                "confidence": 0.95,
                "details": {
                    "cardiac_markers": {
                        "troponin_I": {"value": 2.8, "status": "HIGH"}
                    },
                    "key_findings": [
                        "Significantly elevated troponin I",
                        "Elevated CK-MB"
                    ]
                },
                "rationale": "Lab results confirm acute myocardial injury"
            }
        elif 'fever' in chief_complaint or 'infection' in chief_complaint or 'shortness of breath' in chief_complaint:
            return {
                "modality": "LAB",
                "finding": "Leukocytosis with left shift, elevated inflammatory markers",
                "confidence": 0.89,
                "details": {
                    "cbc": {"WBC": {"value": 18.5, "status": "HIGH"}},
                    "key_findings": [
                        "Marked leukocytosis",
                        "Elevated WBC",
                        "Elevated CRP"
                    ]
                },
                "rationale": "Lab findings strongly suggest bacterial infection"
            }
        else:
            return {
                "modality": "LAB",
                "finding": "Lab values within normal limits",
                "confidence": 0.91,
                "details": {
                    "key_findings": ["Normal complete blood count", "Normal electrolytes"]
                },
                "rationale": "Laboratory studies unremarkable"
            }


class WorkflowSimulator:
    """Simulates the Step Functions workflow"""
    
    def __init__(self, case_id, patient):
        self.case_id = case_id
        self.patient = patient
        self.modalities_completed = []
        self.inference_results = []
        self.iteration = 1
        self.workflow_history = []
        self.reasoning = None
        self.connector = MockModalConnector()
    
    def run(self):
        """Run the complete workflow simulation"""
        print(f"\n{'='*70}")
        print(f"WORKFLOW SIMULATION - Case ID: {self.case_id}")
        print(f"{'='*70}")
        print(f"\nPatient: {self.patient['age']}yo {self.patient['sex']}")
        print(f"Chief Complaint: {self.patient['chief_complaint']}")
        print(f"Vitals: {json.dumps(self.patient.get('vitals', {}), indent=2)}")
        
        max_iterations = 5
        
        while self.iteration <= max_iterations:
            print(f"\n{'-'*70}")
            print(f"ITERATION {self.iteration}")
            print(f"{'-'*70}")
            
            # Fusion Decision
            decision = self._fusion_decision()
            
            # Store in history
            self.workflow_history.append(decision)
            
            # Handle decision
            if decision['decision'] == 'CALL_NEXT_MODALITY':
                self._call_modalities(decision['next_modalities'])
                self.iteration += 1
                
            elif decision['decision'] == 'NEED_REASONING':
                self._bedrock_reasoning(decision)
                # After reasoning, generate report
                break
                
            elif decision['decision'] == 'GENERATE_REPORT':
                break
            
            else:
                print(f"Unknown decision: {decision['decision']}")
                break
        
        # Generate final report
        report = self._generate_report()
        
        return {
            "case_id": self.case_id,
            "status": "completed",
            "patient": self.patient,
            "modalities_used": self.modalities_completed,
            "inference_results": self.inference_results,
            "reasoning": self.reasoning,
            "workflow_history": self.workflow_history,
            "report": report,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    def _fusion_decision(self):
        """Execute fusion decision logic"""
        print("\n[Fusion Decision]")
        
        engine = FusionDecisionEngine(
            patient=self.patient,
            modalities_completed=self.modalities_completed,
            inference_results=self.inference_results,
            iteration=self.iteration
        )
        
        decision = engine.decide()
        
        print(f"Decision: {decision['decision']}")
        if decision.get('next_modalities'):
            print(f"Next modalities: {decision['next_modalities']}")
        print(f"Rationale: {decision['rationale']}")
        print(f"Risk level: {decision.get('risk_level', 'unknown')}")
        
        return decision
    
    def _call_modalities(self, modalities):
        """Call specified modalities"""
        print(f"\n[Calling Modalities: {', '.join(modalities)}]")
        
        for modality in modalities:
            if modality in self.modalities_completed:
                print(f"  ⚠ {modality} already completed, skipping")
                continue
            
            print(f"\n  Calling {modality}...")
            
            if modality == 'CXR':
                result = self.connector.call_cxr(self.patient)
            elif modality == 'ECG':
                result = self.connector.call_ecg(self.patient)
            elif modality == 'LAB':
                result = self.connector.call_lab(self.patient)
            else:
                print(f"  ✗ Unknown modality: {modality}")
                continue
            
            print(f"  ✓ {modality} Result:")
            print(f"    Finding: {result['finding']}")
            print(f"    Confidence: {result['confidence']:.2f}")
            
            self.modalities_completed.append(modality)
            self.inference_results.append(result)
    
    def _bedrock_reasoning(self, fusion_decision):
        """Simulate Bedrock reasoning"""
        print("\n[Bedrock Clinical Reasoning]")
        
        # Simulate reasoning based on findings
        findings_summary = []
        for result in self.inference_results:
            findings_summary.append(f"{result['modality']}: {result['finding']}")
        
        reasoning_text = f"""Clinical Reasoning:

Patient presents with {self.patient['chief_complaint']}. Multimodal analysis reveals:
{chr(10).join('- ' + f for f in findings_summary)}

Risk assessment indicates {fusion_decision['risk_level']} risk level. The combination of findings suggests a need for comprehensive evaluation and timely intervention.

Based on the emergency context and multimodal findings, immediate management and close monitoring are recommended."""
        
        self.reasoning = {
            "reasoning": reasoning_text,
            "reasoning_source": "simulated"
        }
        
        print(reasoning_text)
    
    def _generate_report(self):
        """Generate final clinical report"""
        print(f"\n{'='*70}")
        print("GENERATING FINAL REPORT")
        print(f"{'='*70}")
        
        # Build report sections
        findings_section = []
        for result in self.inference_results:
            findings_section.append(f"""
{result['modality']} FINDINGS:
- Finding: {result['finding']}
- Confidence: {result['confidence']:.2f}
- Key Details: {', '.join(result['details'].get('key_findings', []))}
""")
        
        report = f"""EMERGENCY DEPARTMENT CLINICAL REPORT

CASE ID: {self.case_id}
DATE: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}

PATIENT INFORMATION:
- Age: {self.patient['age']}
- Sex: {self.patient['sex']}
- Chief Complaint: {self.patient['chief_complaint']}

MULTIMODAL DIAGNOSTIC FINDINGS:
{''.join(findings_section)}

CLINICAL SYNTHESIS:
{self.reasoning['reasoning'] if self.reasoning else 'Standard evaluation completed.'}

WORKFLOW SUMMARY:
- Total iterations: {len(self.workflow_history)}
- Modalities used: {', '.join(self.modalities_completed)}
- Decision path: {' → '.join([w['decision'] for w in self.workflow_history])}

IMPRESSION:
Multimodal diagnostic evaluation completed. Please review all findings in clinical context and correlate with patient presentation.

RECOMMENDATIONS:
- Correlate with clinical presentation
- Consider additional workup as indicated
- Follow institutional protocols for management
"""
        
        print(report)
        return report


def simulate_case(case_name, patient_data):
    """Simulate a single case"""
    case_id = f"sim-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    
    print(f"\n\n{'#'*70}")
    print(f"# {case_name}")
    print(f"{'#'*70}")
    
    simulator = WorkflowSimulator(case_id, patient_data)
    result = simulator.run()
    
    print(f"\n{'='*70}")
    print("SIMULATION COMPLETE")
    print(f"{'='*70}")
    print(f"Case ID: {result['case_id']}")
    print(f"Status: {result['status']}")
    print(f"Modalities used: {', '.join(result['modalities_used'])}")
    print(f"Total iterations: {len(result['workflow_history'])}")
    
    return result


def main():
    """Run multiple case simulations"""
    
    # Case 1: STEMI
    case1 = simulate_case(
        "Case 1: Acute Inferior STEMI",
        {
            "age": 65,
            "sex": "Male",
            "chief_complaint": "chest pain",
            "vitals": {
                "BP": "145/92 mmHg",
                "HR": "88 bpm",
                "RR": "18 /min",
                "SpO2": "96%",
                "Temp": "37.2°C"
            }
        }
    )
    
    # Case 2: Pneumonia
    case2 = simulate_case(
        "Case 2: Community-Acquired Pneumonia",
        {
            "age": 72,
            "sex": "Female",
            "chief_complaint": "shortness of breath",
            "vitals": {
                "BP": "130/85 mmHg",
                "HR": "102 bpm",
                "RR": "24 /min",
                "SpO2": "92%",
                "Temp": "38.5°C"
            }
        }
    )
    
    # Case 3: Normal findings
    case3 = simulate_case(
        "Case 3: Headache - Normal Workup",
        {
            "age": 45,
            "sex": "Female",
            "chief_complaint": "headache",
            "vitals": {
                "BP": "120/75 mmHg",
                "HR": "72 bpm",
                "RR": "14 /min",
                "SpO2": "99%",
                "Temp": "36.8°C"
            }
        }
    )
    
    # Summary
    print(f"\n\n{'#'*70}")
    print("# SIMULATION SUMMARY")
    print(f"{'#'*70}")
    
    cases = [
        ("Case 1: STEMI", case1),
        ("Case 2: Pneumonia", case2),
        ("Case 3: Normal", case3)
    ]
    
    for name, result in cases:
        print(f"\n{name}:")
        print(f"  Modalities: {', '.join(result['modalities_used'])}")
        print(f"  Iterations: {len(result['workflow_history'])}")
        print(f"  Final decision: {result['workflow_history'][-1]['decision']}")
        print(f"  Risk level: {result['workflow_history'][-1].get('risk_level', 'unknown')}")


if __name__ == "__main__":
    main()
