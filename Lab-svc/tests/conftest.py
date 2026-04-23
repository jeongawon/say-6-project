"""공통 fixture 및 hypothesis 전략 정의."""

import sys
from pathlib import Path

from hypothesis import strategies as st

# Lab-svc 루트를 sys.path에 추가하여 모듈 임포트 지원
_lab_svc_root = str(Path(__file__).resolve().parent.parent)
if _lab_svc_root not in sys.path:
    sys.path.insert(0, _lab_svc_root)

from shared.schemas import LabValues, LabData, PatientInfo, PredictRequest  # noqa: E402

# ── 유효한 LabValues 생성 전략 ─────────────────────────────────────
lab_values_strategy = st.builds(
    LabValues,
    wbc=st.one_of(st.none(), st.floats(min_value=0.1, max_value=500, allow_nan=False)),
    hemoglobin=st.one_of(st.none(), st.floats(min_value=1.0, max_value=25.0, allow_nan=False)),
    platelet=st.one_of(st.none(), st.floats(min_value=1, max_value=2000, allow_nan=False)),
    creatinine=st.one_of(st.none(), st.floats(min_value=0.1, max_value=30.0, allow_nan=False)),
    bun=st.one_of(st.none(), st.floats(min_value=1, max_value=300, allow_nan=False)),
    sodium=st.one_of(st.none(), st.floats(min_value=100, max_value=200, allow_nan=False)),
    potassium=st.one_of(st.none(), st.floats(min_value=1.0, max_value=12.0, allow_nan=False)),
    glucose=st.one_of(st.none(), st.floats(min_value=10, max_value=2000, allow_nan=False)),
    ast=st.one_of(st.none(), st.floats(min_value=0, max_value=10000, allow_nan=False)),
    albumin=st.one_of(st.none(), st.floats(min_value=0.5, max_value=7.0, allow_nan=False)),
    lactate=st.one_of(st.none(), st.floats(min_value=0.1, max_value=30.0, allow_nan=False)),
    calcium=st.one_of(st.none(), st.floats(min_value=3.0, max_value=18.0, allow_nan=False)),
)

# ── 유효한 Complaint Profile 생성 전략 ────────────────────────────
profile_strategy = st.sampled_from([
    "CARDIAC", "SEPSIS", "GI", "RENAL",
    "RESPIRATORY", "NEUROLOGICAL", "GENERAL",
])

# ── 유효한 PredictRequest 생성 전략 (변경 #2: patient_info + data 래핑) ──
predict_request_strategy = st.builds(
    PredictRequest,
    patient_id=st.text(min_size=1, max_size=50),
    patient_info=st.builds(
        PatientInfo,
        chief_complaint=st.text(max_size=200),
    ),
    data=st.builds(LabData, lab_values=lab_values_strategy),
    context=st.just({}),
)
