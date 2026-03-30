"""
모달별 쿼리 빌더 — RAG 검색용 자연어 쿼리 생성.
v2 query_builder.py에서 마이그레이션.

[역할]
- 모달(chest/ecg/blood)에 따라 검색 쿼리를 최적화
- 빈 쿼리일 경우 모달별 기본 쿼리(정상 소견) 반환
- build_query_from_findings(): v2 호환 — findings dict에서 쿼리 자동 생성

[팀원E 수정 포인트]
- _build_chest_query(): 흉부 X선 쿼리 템플릿/전처리 수정
- _build_ecg_query(): ECG 쿼리 템플릿 수정
- _build_blood_query(): 혈액검사 쿼리 템플릿 수정
- build_query_from_findings(): findings → 쿼리 변환 로직 커스텀
"""


def build_query(query: str, modal: str) -> str:
    """
    모달 유형에 따라 검색 쿼리를 최적화.

    Args:
        query: 원본 검색 쿼리 (소견 텍스트 또는 자연어)
        modal: 모달 유형 (chest, ecg, blood)

    Returns:
        최적화된 검색 쿼리 문자열

    각 모달별 전용 빌더 함수로 분기합니다.
    알 수 없는 모달이면 원본 쿼리를 그대로 반환합니다.
    """
    if modal == "chest":
        return _build_chest_query(query)
    elif modal == "ecg":
        return _build_ecg_query(query)
    elif modal == "blood":
        return _build_blood_query(query)
    else:
        # 알 수 없는 모달 — 원본 쿼리 그대로 반환
        return query


def _build_chest_query(query: str) -> str:
    """
    흉부 X선 모달 — IMPRESSION 검색용 영어 쿼리.

    FAISS 인덱스가 MIMIC-IV radiology.csv의 IMPRESSION을 임베딩한 것이므로,
    쿼리도 영어 의학 용어로 구성하는 것이 검색 정확도에 유리합니다.
    """
    # 빈 쿼리이면 정상 소견 기본 쿼리 반환
    if not query.strip():
        return "Normal chest radiograph. No acute cardiopulmonary process."
    # 쿼리가 이미 잘 구성되어 있으면 그대로 사용
    return query


def _build_ecg_query(query: str) -> str:
    """
    ECG 모달 — 심전도 소견 검색용 쿼리.

    "ECG findings:" 접두어를 붙여서 심전도 관련 검색 정확도를 높입니다.
    """
    # 빈 쿼리이면 정상 심전도 기본 쿼리 반환
    if not query.strip():
        return "Normal sinus rhythm. No ST-segment changes."
    return f"ECG findings: {query}"


def _build_blood_query(query: str) -> str:
    """
    혈액검사 모달 — 검사수치 기반 쿼리.

    "Lab results:" 접두어를 붙여서 검사수치 관련 검색 정확도를 높입니다.
    """
    # 빈 쿼리이면 정상 검사수치 기본 쿼리 반환
    if not query.strip():
        return "Laboratory values within normal limits."
    return f"Lab results: {query}"


def build_query_from_findings(findings: dict) -> str:
    """
    v2 호환: clinical_logic findings dict에서 검색 쿼리 생성.

    chest-svc의 분석 결과(findings)를 받아서 IMPRESSION 검색용 영어 쿼리로 변환.
    detected=True인 질환만 추출하여 "severity + disease_name + location" 형태로 조합.

    Args:
        findings: {"disease_name": {"detected": bool, "severity": str, "location": str}, ...}
                  예: {"Cardiomegaly": {"detected": True, "severity": "moderate", "location": ""}}

    Returns:
        IMPRESSION 검색용 영어 쿼리
        예: "moderate cardiomegaly, bilateral pleural effusion."
    """
    detected = []

    for disease, result in findings.items():
        # dict가 아니거나 detected가 False이면 건너뜀
        if not isinstance(result, dict) or not result.get("detected"):
            continue
        # No_Finding은 검색 쿼리에서 제외
        if disease == "No_Finding":
            continue

        severity = result.get("severity", "")    # 예: "moderate", "severe"
        location = result.get("location", "")     # 예: "bilateral", "left lower lobe"
        name = disease.replace("_", " ").lower()  # 예: "Pleural_Effusion" → "pleural effusion"
        # 빈 문자열 제거 후 조합: "moderate pleural effusion bilateral"
        parts = [p for p in [severity, name, location] if p]
        detected.append(" ".join(parts))

    # 검출된 질환이 없으면 정상 소견 기본 쿼리 반환
    if not detected:
        return "Normal chest radiograph. No acute cardiopulmonary process."

    # 콤마로 연결: "moderate cardiomegaly, bilateral pleural effusion."
    return f"{', '.join(detected)}."
