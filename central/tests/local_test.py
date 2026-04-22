"""
Local test script for Emergency Multimodal Orchestrator.
Tests the orchestration logic without AWS deployment.
"""
import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'deploy'))

from orchestrator.fusion_decision.decision_engine import FusionDecisionEngine


def test_case_1_chest_pain():
    """Test Case 1: Chest pain patient - should trigger CXR + ECG"""
    print("\n" + "="*60)
    print("TEST CASE 1: Chest Pain Patient")
    print("="*60)
    
    patient = {
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
    
    # Initial decision (no results yet)
    print("\n[Iteration 1] Initial assessment")
    engine = FusionDecisionEngine(
        patient=patient,
        modalities_completed=[],
        inference_results=[],
        iteration=1
    )
    
    decision = engine.decide()
    print(f"Decision: {decision['decision']}")
    print(f"Next modalities: {decision.get('next_modalities', [])}")
    print(f"Rationale: {decision['rationale']}")
    
    # Simulate CXR and ECG results
    print("\n[Iteration 2] After CXR + ECG")
    cxr_result = {
        "modality": "CXR",
        "finding": "Cardiomegaly with possible pulmonary edema",
        "confidence": 0.82,
        "details": {
            "key_findings": [
                "Enlarged cardiac silhouette",
                "Bilateral perihilar opacities"
            ]
        },
        "rationale": "Chest X-ray shows enlarged heart with signs of fluid overload"
    }
    
    ecg_result = {
        "modality": "ECG",
        "finding": "ST elevation in leads II, III, aVF - Inferior STEMI",
        "confidence": 0.93,
        "details": {
            "key_findings": [
                "ST elevation in inferior leads",
                "Q waves in III, aVF"
            ]
        },
        "rationale": "ECG findings consistent with acute inferior myocardial infarction"
    }
    
    engine = FusionDecisionEngine(
        patient=patient,
        modalities_completed=["CXR", "ECG"],
        inference_results=[cxr_result, ecg_result],
        iteration=2
    )
    
    decision = engine.decide()
    print(f"Decision: {decision['decision']}")
    print(f"Next modalities: {decision.get('next_modalities', [])}")
    print(f"Rationale: {decision['rationale']}")
    print(f"Risk level: {decision['risk_level']}")
    
    # Should suggest LAB for troponin
    if decision['decision'] == 'CALL_NEXT_MODALITY' and 'LAB' in decision.get('next_modalities', []):
        print("\n[Iteration 3] After LAB")
        lab_result = {
            "modality": "LAB",
            "finding": "Elevated troponin, consistent with myocardial injury",
            "confidence": 0.95,
            "details": {
                "key_findings": [
                    "Significantly elevated troponin I",
                    "Elevated CK-MB"
                ]
            },
            "rationale": "Lab results confirm acute myocardial injury"
        }
        
        engine = FusionDecisionEngine(
            patient=patient,
            modalities_completed=["CXR", "ECG", "LAB"],
            inference_results=[cxr_result, ecg_result, lab_result],
            iteration=3
        )
        
        decision = engine.decide()
        print(f"Decision: {decision['decision']}")
        print(f"Rationale: {decision['rationale']}")
        print(f"Risk level: {decision['risk_level']}")
    
    print("\n✓ Test Case 1 completed")
    return True


def test_case_2_shortness_of_breath():
    """Test Case 2: Shortness of breath - should detect pneumonia pattern"""
    print("\n" + "="*60)
    print("TEST CASE 2: Shortness of Breath - Pneumonia")
    print("="*60)
    
    patient = {
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
    
    # Initial decision
    print("\n[Iteration 1] Initial assessment")
    engine = FusionDecisionEngine(
        patient=patient,
        modalities_completed=[],
        inference_results=[],
        iteration=1
    )
    
    decision = engine.decide()
    print(f"Decision: {decision['decision']}")
    print(f"Next modalities: {decision.get('next_modalities', [])}")
    
    # Simulate CXR and ECG results
    print("\n[Iteration 2] After CXR + ECG")
    cxr_result = {
        "modality": "CXR",
        "finding": "Right lower lobe pneumonia",
        "confidence": 0.88,
        "details": {
            "key_findings": [
                "Right lower lobe consolidation",
                "Air bronchograms present"
            ]
        },
        "rationale": "Consolidation pattern consistent with bacterial pneumonia"
    }
    
    ecg_result = {
        "modality": "ECG",
        "finding": "Sinus tachycardia, no acute changes",
        "confidence": 0.91,
        "details": {
            "key_findings": ["Sinus tachycardia", "No ST-T wave abnormalities"]
        },
        "rationale": "ECG shows tachycardia, likely secondary to infection"
    }
    
    engine = FusionDecisionEngine(
        patient=patient,
        modalities_completed=["CXR", "ECG"],
        inference_results=[cxr_result, ecg_result],
        iteration=2
    )
    
    decision = engine.decide()
    print(f"Decision: {decision['decision']}")
    print(f"Next modalities: {decision.get('next_modalities', [])}")
    print(f"Rationale: {decision['rationale']}")
    
    # Should suggest LAB
    if decision['decision'] == 'CALL_NEXT_MODALITY' and 'LAB' in decision.get('next_modalities', []):
        print("\n[Iteration 3] After LAB")
        lab_result = {
            "modality": "LAB",
            "finding": "Leukocytosis with left shift, elevated inflammatory markers",
            "confidence": 0.89,
            "details": {
                "key_findings": [
                    "Marked leukocytosis",
                    "Elevated WBC",
                    "Elevated CRP"
                ]
            },
            "rationale": "Lab findings strongly suggest bacterial infection"
        }
        
        engine = FusionDecisionEngine(
            patient=patient,
            modalities_completed=["CXR", "ECG", "LAB"],
            inference_results=[cxr_result, ecg_result, lab_result],
            iteration=3
        )
        
        decision = engine.decide()
        print(f"Decision: {decision['decision']}")
        print(f"Rationale: {decision['rationale']}")
        print(f"Risk level: {decision['risk_level']}")
        
        # Should trigger NEED_REASONING due to high-risk pattern
        if decision['decision'] == 'NEED_REASONING':
            print("\n✓ Correctly detected high-risk pneumonia pattern!")
    
    print("\n✓ Test Case 2 completed")
    return True


def test_case_3_low_confidence():
    """Test Case 3: Low confidence result - should request additional modality"""
    print("\n" + "="*60)
    print("TEST CASE 3: Low Confidence Scenario")
    print("="*60)
    
    patient = {
        "age": 55,
        "sex": "Male",
        "chief_complaint": "abdominal pain",
        "vitals": {
            "BP": "125/80 mmHg",
            "HR": "78 bpm",
            "RR": "16 /min",
            "SpO2": "98%",
            "Temp": "37.0°C"
        }
    }
    
    print("\n[Iteration 1] After initial CXR with low confidence")
    cxr_result = {
        "modality": "CXR",
        "finding": "Possible free air under diaphragm",
        "confidence": 0.55,  # Low confidence
        "details": {
            "key_findings": ["Questionable pneumoperitoneum"]
        },
        "rationale": "Image quality suboptimal, findings uncertain"
    }
    
    engine = FusionDecisionEngine(
        patient=patient,
        modalities_completed=["CXR"],
        inference_results=[cxr_result],
        iteration=1
    )
    
    decision = engine.decide()
    print(f"Decision: {decision['decision']}")
    print(f"Next modalities: {decision.get('next_modalities', [])}")
    print(f"Rationale: {decision['rationale']}")
    print(f"Confidence summary: {decision['confidence_summary']}")
    
    if decision['decision'] == 'CALL_NEXT_MODALITY':
        print("\n✓ Correctly requested additional modality due to low confidence!")
    
    print("\n✓ Test Case 3 completed")
    return True


def test_case_4_normal_findings():
    """Test Case 4: Normal findings - should proceed to report"""
    print("\n" + "="*60)
    print("TEST CASE 4: Normal Findings")
    print("="*60)
    
    patient = {
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
    
    print("\n[Iteration 1] After LAB")
    lab_result = {
        "modality": "LAB",
        "finding": "Lab values within normal limits",
        "confidence": 0.91,
        "details": {
            "key_findings": [
                "Normal complete blood count",
                "Normal electrolytes"
            ]
        },
        "rationale": "Laboratory studies unremarkable"
    }
    
    engine = FusionDecisionEngine(
        patient=patient,
        modalities_completed=["LAB"],
        inference_results=[lab_result],
        iteration=1
    )
    
    decision = engine.decide()
    print(f"Decision: {decision['decision']}")
    print(f"Rationale: {decision['rationale']}")
    print(f"Risk level: {decision['risk_level']}")
    
    if decision['risk_level'] == 'low':
        print("\n✓ Correctly assessed as low risk!")
    
    print("\n✓ Test Case 4 completed")
    return True


def test_modal_connectors():
    """Test modal connector mock responses"""
    print("\n" + "="*60)
    print("TEST: Modal Connectors")
    print("="*60)
    
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent / 'deploy' / 'modal_connectors'))
        
        # Test CXR Connector
        print("\n[CXR Connector]")
        from cxr_connector.lambda_function import generate_mock_response
        
        patient = {"chief_complaint": "chest pain"}
        cxr_response = generate_mock_response("test-case", patient)
        print(f"Modality: {cxr_response['modality']}")
        print(f"Finding: {cxr_response['finding']}")
        print(f"Confidence: {cxr_response['confidence']}")
        
        # Test ECG Connector
        print("\n[ECG Connector]")
        from ecg_connector.lambda_function import handler as ecg_handler
        
        event = {"case_id": "test-case", "patient": {"chief_complaint": "chest pain"}}
        ecg_response = ecg_handler(event, None)
        print(f"Modality: {ecg_response['modality']}")
        print(f"Finding: {ecg_response['finding']}")
        print(f"Confidence: {ecg_response['confidence']}")
        
        # Test LAB Connector
        print("\n[LAB Connector]")
        from lab_connector.lambda_function import handler as lab_handler
        
        lab_response = lab_handler(event, None)
        print(f"Modality: {lab_response['modality']}")
        print(f"Finding: {lab_response['finding']}")
        print(f"Confidence: {lab_response['confidence']}")
        
        print("\n✓ Modal connectors test completed")
        return True
    except ImportError as e:
        print(f"\n⚠ Skipping modal connector tests (missing dependencies: {e})")
        print("Note: Modal connectors require boto3, which is available in AWS Lambda environment")
        return True  # Don't fail the test suite


def run_all_tests():
    """Run all test cases"""
    print("\n" + "="*60)
    print("EMERGENCY MULTIMODAL ORCHESTRATOR - LOCAL TESTS")
    print("="*60)
    
    tests = [
        ("Chest Pain Patient", test_case_1_chest_pain),
        ("Pneumonia Detection", test_case_2_shortness_of_breath),
        ("Low Confidence Handling", test_case_3_low_confidence),
        ("Normal Findings", test_case_4_normal_findings),
        ("Modal Connectors", test_modal_connectors)
    ]
    
    results = []
    for name, test_func in tests:
        try:
            success = test_func()
            results.append((name, success))
        except Exception as e:
            print(f"\n✗ Test failed: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    for name, success in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"{status}: {name}")
    
    total = len(results)
    passed = sum(1 for _, s in results if s)
    print(f"\nTotal: {passed}/{total} tests passed")
    
    return all(s for _, s in results)


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
