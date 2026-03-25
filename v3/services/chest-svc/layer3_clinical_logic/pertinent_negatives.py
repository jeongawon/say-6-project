"""
Pertinent Negatives — 주소(chief complaint) 기반 감별 진단 필수 확인 소견.

"주어진 주소에서 반드시 확인해야 하는 음성 소견"을 생성한다.
예: 호흡곤란 환자에서 기흉/흉수 음성이면 → "기흉 및 흉수 없음" 명시.

이는 영상의학과 판독문의 'pertinent negative' 관행을 구현한 것으로,
임상의가 감별 진단에서 빠진 소견을 놓치지 않도록 돕는다.
"""

from typing import List, Optional, Dict

# 주소(chief complaint) 키워드 → 반드시 확인해야 할 질환 목록
# 해당 질환이 음성이면 pertinent negative로 보고한다.
PERTINENT_NEGATIVE_MAP: Dict[str, List[str]] = {
    # 호흡곤란: 흉수, 기흉, 폐부종, 무기폐, 심비대 감별 필수
    "호흡곤란": [
        "Pleural_Effusion",
        "Pneumothorax",
        "Edema",
        "Atelectasis",
        "Cardiomegaly",
    ],
    # 흉통: 기흉, 골절, 심비대, 종격동 확대 감별 필수
    "흉통": [
        "Pneumothorax",
        "Fracture",
        "Cardiomegaly",
        "Enlarged_Cardiomediastinum",
        "Pleural_Effusion",
    ],
    # 발열: 폐렴, 경화, 흉수 감별 필수
    "발열": [
        "Pneumonia",
        "Consolidation",
        "Pleural_Effusion",
        "Lung_Opacity",
    ],
    # 기침: 폐렴, 경화, 폐부종, 무기폐 감별 필수
    "기침": [
        "Pneumonia",
        "Consolidation",
        "Edema",
        "Atelectasis",
        "Lung_Opacity",
    ],
    # 외상: 골절, 기흉, 흉수 감별 필수
    "외상": [
        "Fracture",
        "Pneumothorax",
        "Pleural_Effusion",
    ],
    # 기본값: 주소가 없거나 매칭 안 될 때 → 주요 위험 질환만 확인
    "default": [
        "Pneumothorax",
        "Pleural_Effusion",
        "Cardiomegaly",
    ],
}

# 질환명 → 한국어 음성 보고 문구
_NEGATIVE_PHRASES: Dict[str, str] = {
    "Pleural_Effusion": "흉수 없음",
    "Pneumothorax": "기흉 없음",
    "Edema": "폐부종 소견 없음",
    "Atelectasis": "무기폐 없음",
    "Cardiomegaly": "심비대 없음",
    "Enlarged_Cardiomediastinum": "종격동 확대 없음",
    "Pneumonia": "폐렴 소견 없음",
    "Consolidation": "경화 소견 없음",
    "Fracture": "골절 없음",
    "Lung_Opacity": "폐 음영 증가 없음",
    "Lung_Lesion": "폐 병변 없음",
    "Support_Devices": "의료 기구 없음",
    "Pleural_Other": "기타 흉막 이상 없음",
}


def get_pertinent_negatives(
    chief_complaint: Optional[str],
    findings: dict,
) -> List[str]:
    """
    주소(chief complaint)에 따라 pertinent negative 목록을 생성한다.

    Args:
        chief_complaint: 환자 주소 문자열 (예: "호흡곤란, 흉통").
                         None이면 default 목록 사용.
        findings: engine.run_clinical_logic()의 results dict.
                  {질환명: {"detected": bool, ...}, ...}

    Returns:
        List[str]: 한국어 pertinent negative 문구 목록.
                   예: ["기흉 없음", "흉수 없음"]
    """
    # 주소에서 매칭되는 키워드 수집
    matched_diseases: set = set()

    if chief_complaint:
        for keyword, diseases in PERTINENT_NEGATIVE_MAP.items():
            if keyword == "default":
                continue
            if keyword in chief_complaint:
                matched_diseases.update(diseases)

    # 매칭된 키워드가 없으면 default 사용
    if not matched_diseases:
        matched_diseases = set(PERTINENT_NEGATIVE_MAP["default"])

    # 해당 질환 중 음성(detected=False)인 것만 pertinent negative로 보고
    negatives: List[str] = []
    for disease in sorted(matched_diseases):
        result = findings.get(disease, {})
        if not result.get("detected", False):
            phrase = _NEGATIVE_PHRASES.get(disease, f"{disease} 없음")
            negatives.append(phrase)

    return negatives
