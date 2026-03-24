"""
Layer 3 Clinical Logic 결과를 자연어 검색 쿼리로 변환.
판독문이 영어이므로 쿼리도 영어로 생성.
"""


def build_query(clinical_logic_result: dict) -> str:
    """
    Layer 3 결과에서 detected 소견을 추출하여 IMPRESSION 검색용 영어 쿼리 생성.

    예: "severe cardiomegaly bilateral, moderate pleural effusion bilateral,
         severe edema bilateral. Consistent with CHF."
    """
    detected = []
    findings = clinical_logic_result.get("findings", {})

    for disease, result in findings.items():
        if not result.get("detected"):
            continue
        # No_Finding은 정상 표시이므로 쿼리에서 제외
        if disease == "No_Finding":
            continue

        severity = result.get("severity", "")
        location = result.get("location", "")
        name = disease.replace("_", " ").lower()
        parts = [p for p in [severity, name, location] if p]
        detected.append(" ".join(parts))

    if not detected:
        return "Normal chest radiograph. No acute cardiopulmonary process."

    # 감별 진단 추가
    diff = clinical_logic_result.get("differential_diagnosis", [])
    if diff:
        primary = diff[0].get("diagnosis", "")
        query = f"{', '.join(detected)}. Consistent with {primary}."
    else:
        query = f"{', '.join(detected)}."

    return query
