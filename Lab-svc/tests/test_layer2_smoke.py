"""Layer 2 Rule Engine 스모크 테스트."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.schemas import ProcessedInput
from layer2_rule_engine.engine import RuleEngine
from layer2_rule_engine.stage_b_complaint import ComplaintFocusedStage
from layer2_rule_engine.stage_c_fullscan import ALL_VALUE_FEATURES


def test_critical_flags():
    engine = RuleEngine()
    pi = ProcessedInput(
        normalized_values={
            "wbc": 15.0, "hemoglobin": 6.0, "platelet": 200.0,
            "creatinine": 1.0, "bun": 15.0, "sodium": 140.0,
            "potassium": 7.0, "glucose": 90.0, "ast": 30.0,
            "albumin": 4.0, "lactate": 1.0, "calcium": 9.0,
        },
        indicators={"has_ast": 1, "has_albumin": 1, "has_lactate": 1, "has_calcium": 1,
                     "has_troponin_t": 0, "has_bnp": 0, "has_amylase": 0},
        complaint_profile="CARDIAC",
    )
    findings = engine.execute(pi)
    critical = [f for f in findings if f.category == "critical"]
    assert len(critical) >= 2  # K+ high + Hgb low
    names = {f.name for f in critical}
    assert "critical_potassium_high" in names
    assert "critical_hemoglobin_low" in names


def test_all_normal():
    engine = RuleEngine()
    pi = ProcessedInput(
        normalized_values={
            "wbc": 7.0, "hemoglobin": 14.0, "platelet": 250.0,
            "creatinine": 1.0, "bun": 15.0, "sodium": 140.0,
            "potassium": 4.0, "glucose": 90.0, "ast": 20.0,
            "albumin": 4.0, "lactate": 1.0, "calcium": 9.5,
        },
        indicators={"has_ast": 1, "has_albumin": 1, "has_lactate": 1, "has_calcium": 1,
                     "has_troponin_t": 0, "has_bnp": 0, "has_amylase": 0},
        complaint_profile="GENERAL",
    )
    findings = engine.execute(pi)
    # No critical or primary abnormal findings (only unmeasured warnings for Tier 3 if applicable)
    critical = [f for f in findings if f.category == "critical"]
    assert len(critical) == 0


def test_sepsis_findings():
    engine = RuleEngine()
    pi = ProcessedInput(
        normalized_values={
            "wbc": 25.0, "hemoglobin": 14.0, "platelet": 80.0,
            "creatinine": 3.0, "bun": 15.0, "sodium": 140.0,
            "potassium": 4.0, "glucose": 200.0, "ast": 20.0,
            "albumin": 4.0, "lactate": 5.0, "calcium": 9.5,
        },
        indicators={"has_ast": 1, "has_albumin": 1, "has_lactate": 1, "has_calcium": 1,
                     "has_troponin_t": 0, "has_bnp": 0, "has_amylase": 0},
        complaint_profile="SEPSIS",
    )
    findings = engine.execute(pi)
    # Should have critical lactate flag + sepsis primary findings
    critical = [f for f in findings if f.category == "critical"]
    primary = [f for f in findings if f.category == "primary"]
    assert len(critical) >= 1  # lactate > 4.0
    assert len(primary) >= 3  # wbc, platelet, creatinine, glucose, lactate


def test_feature_coverage():
    stage_b = ComplaintFocusedStage()
    for profile in ["CARDIAC", "SEPSIS", "GI", "RENAL", "RESPIRATORY", "NEUROLOGICAL", "GENERAL"]:
        checked = stage_b.get_checked_features(profile)
        remaining = ALL_VALUE_FEATURES - checked
        union = checked | remaining
        assert union == ALL_VALUE_FEATURES, f"{profile}: union != ALL_VALUE_FEATURES"
        assert len(checked & remaining) == 0, f"{profile}: overlap between B and C"


if __name__ == "__main__":
    test_critical_flags()
    print("test_critical_flags PASSED")
    test_all_normal()
    print("test_all_normal PASSED")
    test_sepsis_findings()
    print("test_sepsis_findings PASSED")
    test_feature_coverage()
    print("test_feature_coverage PASSED")
    print("All smoke tests passed!")
