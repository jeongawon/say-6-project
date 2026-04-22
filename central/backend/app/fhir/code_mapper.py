"""§6.3 텍스트 → ICD-10 코드 매핑 알고리즘."""
from __future__ import annotations

import json
import logging
from typing import Optional

from app.fhir.codes import ICD10_MAP

logger = logging.getLogger(__name__)

# 한글 → ICD-10 정적 사전 (codes.py 에서 가져옴)
KOREAN_TO_ICD10 = ICD10_MAP


def map_text_to_icd10(text: str) -> Optional[dict]:
    """
    1단계: 정적 사전 룩업
    2단계: Claude Haiku 폴백
    3단계: 실패 시 None → Condition.code.text 만 채우고 coding 비움
    """
    # 1단계: 정적 사전
    if text in KOREAN_TO_ICD10:
        entry = KOREAN_TO_ICD10[text]
        return {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": entry["code"],
            "display": entry["display"],
        }

    # 부분 매칭 시도
    for key, entry in KOREAN_TO_ICD10.items():
        if key in text or text in key:
            return {
                "system": "http://hl7.org/fhir/sid/icd-10-cm",
                "code": entry["code"],
                "display": entry["display"],
            }

    # 2단계: Claude Haiku 폴백 (비용 주의)
    try:
        from app.agent.bedrock_client import invoke

        prompt = (
            f"다음 한글 증상을 ICD-10-CM 코드로 매핑하라: '{text}'. "
            'JSON만 출력: {"code": "...", "display": "..."}'
        )
        raw = invoke(prompt, max_tokens=100, temperature=0.0)

        import json as _json
        parsed = _json.loads(raw)
        if "code" in parsed and "display" in parsed:
            return {
                "system": "http://hl7.org/fhir/sid/icd-10-cm",
                "code": parsed["code"],
                "display": parsed["display"],
            }
    except Exception as e:
        logger.warning(f"Claude Haiku 폴백 실패: {e}")

    # 3단계: 매핑 실패 → Condition.code.text 만 채우고 coding 비움
    logger.warning(f"ICD-10 매핑 실패: '{text}'")
    return None
