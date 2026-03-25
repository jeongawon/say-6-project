"""
감별 진단 엔진 (Differential Diagnosis).
여러 질환이 동시에 탐지될 때, 동반 소견 조합으로 최종 감별.
"""

from .models import ClinicalLogicInput


# 감별 패턴 정의
DIFFERENTIAL_PATTERNS = [
    {
        "name": "감염성 폐렴",
        "required": ["Consolidation"],
        "clinical": ["fever", "cough"],
        "optional_clinical": ["ecg_normal"],
        "diagnosis": "감염성 폐렴",
        "probability": "high",
        "alert": False,
    },
    {
        "name": "심인성 폐부종",
        "required": ["Consolidation"],
        "flags": ["ctr_elevated", "bilateral_symmetric"],
        "diagnosis": "심인성 폐부종 (폐렴 아님)",
        "probability": "high",
        "alert": False,
    },
    {
        "name": "외상성 기흉",
        "required": ["Fracture", "Pneumothorax"],
        "diagnosis": "외상성 기흉",
        "probability": "high",
        "alert": False,
    },
    {
        "name": "무기폐",
        "required": ["Lung_Opacity"],
        "flags": ["lung_area_decreased", "ipsilateral_shift"],
        "diagnosis": "무기폐 (폐렴 아님)",
        "probability": "high",
        "alert": False,
    },
    {
        "name": "울혈성 심부전 (CHF)",
        "required": ["Cardiomegaly", "Pleural_Effusion", "Edema"],
        "diagnosis": "울혈성 심부전 (CHF)",
        "probability": "high",
        "alert": False,
    },
    {
        "name": "긴장성 기흉",
        "required": ["Pneumothorax"],
        "flags": ["trachea_contralateral_shift"],
        "diagnosis": "긴장성 기흉 (TENSION)",
        "probability": "critical",
        "alert": True,
    },
]


def analyze(results: dict, input: ClinicalLogicInput) -> list:
    """
    감별 진단 수행.

    Args:
        results: 14개 질환별 Rule 결과 dict {finding_name: result_dict}
        input: ClinicalLogicInput (환자 정보, 해부학 측정값)

    Returns:
        list of matched differential diagnosis dicts
    """
    matched = []

    detected_set = {name for name, r in results.items() if r.get("detected")}
    clinical_flags = _extract_clinical_flags(input, results)

    for pattern in DIFFERENTIAL_PATTERNS:
        required = pattern.get("required", [])
        if not all(f in detected_set for f in required):
            continue

        clinical_req = pattern.get("clinical", [])
        if clinical_req:
            clinical_met = sum(1 for c in clinical_req if clinical_flags.get(c))
            if clinical_met < len(clinical_req) * 0.5:
                continue

        flags_req = pattern.get("flags", [])
        if flags_req:
            flags_met = sum(1 for f in flags_req if clinical_flags.get(f))
            if flags_met < len(flags_req) * 0.5:
                continue

        matched.append({
            "diagnosis": pattern["diagnosis"],
            "probability": pattern["probability"],
            "matched_findings": [f for f in required if f in detected_set],
            "matched_flags": [f for f in (clinical_req + flags_req) if clinical_flags.get(f)],
            "alert": pattern.get("alert", False),
        })

    return matched


# ================================================================
# 감별진단 중복 제거용 그룹 정의
# 같은 그룹에 속하는 진단명은 첫 번째만 유지하여 리포트 중복 방지
# ================================================================
DIAGNOSIS_GROUPS = {
    "CHF": ["울혈성 심부전", "심인성 폐부종", "CHF", "Congestive Heart Failure", "심부전", "Heart Failure"],
    "Pneumonia": ["감염성 폐렴", "세균성 폐렴", "바이러스성 폐렴", "폐렴"],
    "Malignancy": ["폐암", "종격동 종양", "전이성 폐병변"],
}


def deduplicate_differentials(differentials: list) -> list:
    """같은 그룹의 감별진단은 첫 번째만 유지."""
    seen_groups = set()
    result = []
    for diff in differentials:
        diagnosis = diff.get("diagnosis", "")
        matched_group = None
        for group_name, keywords in DIAGNOSIS_GROUPS.items():
            if any(kw in diagnosis for kw in keywords):
                matched_group = group_name
                break
        if matched_group:
            if matched_group not in seen_groups:
                seen_groups.add(matched_group)
                result.append(diff)
            # 같은 그룹이면 skip (중복 제거)
        else:
            result.append(diff)
    return result


def _extract_clinical_flags(input: ClinicalLogicInput, results: dict) -> dict:
    """환자 정보 + 결과에서 감별용 플래그 추출."""
    flags = {}
    a = input.anatomy
    pi = input.patient_info

    # 해부학 플래그
    flags["ctr_elevated"] = a.ctr > 0.50
    flags["lung_area_decreased"] = a.lung_area_ratio < 0.80 or a.lung_area_ratio > 1.25

    # 종격동 이동
    if a.trachea_midline is not None and not a.trachea_midline:
        ptx = results.get("Pneumothorax", {})
        ptx_side = ptx.get("quantitative", {}).get("side")
        if ptx_side and a.trachea_deviation_direction:
            flags["trachea_contralateral_shift"] = (ptx_side != a.trachea_deviation_direction)
        flags["ipsilateral_shift"] = True
    else:
        flags["trachea_contralateral_shift"] = False
        flags["ipsilateral_shift"] = False

    # 양측 대칭
    edema_r = results.get("Edema", {})
    flags["bilateral_symmetric"] = edema_r.get("quantitative", {}).get("bilateral_symmetric", False)

    # 환자 정보 플래그
    if pi:
        flags["fever"] = pi.temperature > 38.0 if pi.temperature else False
        if pi.chief_complaint:
            cc = pi.chief_complaint.lower()
            flags["cough"] = "기침" in cc or "cough" in cc
        else:
            flags["cough"] = False
    else:
        flags["fever"] = False
        flags["cough"] = False

    # ECG 정상 여부
    flags["ecg_normal"] = False
    for pr in input.prior_results:
        if pr.modal == "ecg":
            s = pr.summary.lower()
            flags["ecg_normal"] = ("정상" in s or "normal" in s or "nsr" in s)

    return flags
