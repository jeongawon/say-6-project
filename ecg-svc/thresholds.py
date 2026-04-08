"""
질환별 분류 임계값

Tier 1 (사망률 ≥10%): val set PR curve 기반 최적값 (recall ≥ 0.90 목표)
Tier 2 (사망률 5~10%): 경험값 0.40
Tier 3 (사망률 2~5%):  경험값 0.45
"""

THRESHOLDS: dict[str, float] = {
    # Tier 1 — val set 기반 (recall ≥ 0.90)
    'cardiac_arrest':         0.001,
    'acute_mi':               0.010,
    'pulmonary_embolism':     0.005,
    'paroxysmal_tachycardia': 0.008,
    'hyperkalemia':           0.012,
    'respiratory_failure':    0.014,
    'sepsis':                 0.011,
    'pericardial_disease':    0.002,
    'av_block_lbbb':          0.021,
    'calcium_disorder':       0.004,
    'acute_kidney_failure':   0.057,

    # Tier 2 — 경험값
    'afib_flutter':           0.40,
    'heart_failure':          0.40,
    'afib_detail':            0.40,
    'hf_detail':              0.40,
    'copd':                   0.40,
    'hypokalemia':            0.40,
    'chronic_kidney':         0.40,
    'chronic_ihd':            0.40,
    'hypothyroidism':         0.40,
    'other_conduction':       0.40,

    # Tier 3 — 경험값
    'dm2':                    0.45,
    'hypertension':           0.45,
    'angina':                 0.45,
}

TIER_MAP: dict[str, int] = {
    'cardiac_arrest':         1,
    'acute_mi':               1,
    'pulmonary_embolism':     1,
    'paroxysmal_tachycardia': 1,
    'hyperkalemia':           1,
    'respiratory_failure':    1,
    'sepsis':                 1,
    'pericardial_disease':    1,
    'av_block_lbbb':          1,
    'calcium_disorder':       1,
    'acute_kidney_failure':   1,
    'afib_flutter':           2,
    'heart_failure':          2,
    'afib_detail':            2,
    'hf_detail':              2,
    'copd':                   2,
    'hypokalemia':            2,
    'chronic_kidney':         2,
    'chronic_ihd':            2,
    'hypothyroidism':         2,
    'other_conduction':       2,
    'dm2':                    3,
    'hypertension':           3,
    'angina':                 3,
}

DEFAULT_THRESHOLD = 0.40


def get_threshold(label: str) -> float:
    return THRESHOLDS.get(label, DEFAULT_THRESHOLD)
