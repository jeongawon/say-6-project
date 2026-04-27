import pickle
import numpy as np
import pandas as pd
from pathlib import Path

# Docker 컨테이너 내 경로: /app/final_models.pkl
MODEL_PATH = Path(__file__).parent.parent / 'final_models.pkl'

FEATURE_COLS = [
    'creatinine_0h', 'glucose_0h', 'hemoglobin_0h', 'lactate_0h',
    'platelet_0h', 'potassium_0h', 'sodium_0h', 'wbc_0h',
    'troponin_t_0h', 'bnp_0h',
    'has_lactate_0h', 'has_troponin_t_0h', 'has_bnp_0h'
]

LABEL_MAP = {
    'label_hb_down_6h':          'hemoglobin_down',
    'label_creatinine_up_6h':    'creatinine_up',
    'label_potassium_worse_6h':  'potassium_worse',
    'label_lactate_up_6h':       'lactate_up',
    'label_troponin_up_6h':      'troponin_up',
}

LABEL_KOR = {
    'hemoglobin_down':  'Hemoglobin 감소',
    'creatinine_up':    'Creatinine 증가',
    'potassium_worse':  'Potassium 악화',
    'lactate_up':       'Lactate 증가',
    'troponin_up':      'Troponin T 상승',
}


def load_models():
    with open(MODEL_PATH, 'rb') as f:
        return pickle.load(f)


def build_features(input_values: dict) -> pd.DataFrame:
    row = dict(input_values)
    row['has_lactate_0h']    = 1 if row.get('lactate_0h')    is not None else 0
    row['has_troponin_t_0h'] = 1 if row.get('troponin_t_0h') is not None else 0
    row['has_bnp_0h']        = 1 if row.get('bnp_0h')        is not None else 0
    for k in row:
        if row[k] is None:
            row[k] = np.nan
    return pd.DataFrame([row])[FEATURE_COLS]


def predict(models: dict, input_values: dict) -> dict:
    X = build_features(input_values)
    result = {}
    warnings = []
    troponin_note = None

    for label, res in models.items():
        prob      = float(res['model'].predict_proba(X)[0][1])
        short_key = LABEL_MAP[label]
        result[short_key] = round(prob, 4)
        if prob >= 0.5:
            warnings.append(LABEL_KOR[short_key])

    if input_values.get('troponin_t_0h') is None:
        troponin_note = "Troponin T가 미측정되었습니다. 임상 판단이 필요합니다."

    result['warnings']      = warnings
    result['troponin_note'] = troponin_note
    return result
