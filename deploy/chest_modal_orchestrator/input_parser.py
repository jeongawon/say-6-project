"""유연한 입력 파싱 — 어떤 형태의 입력이든 정규화"""
from config import DEFAULT_OPTIONS


def parse_input(body: dict) -> dict:
    """
    다양한 필드명 수용, 없으면 기본값, 원본 보관.

    Returns:
        {"image_base64", "s3_key", "patient_info", "prior_results", "options", "raw_input"}

    Raises:
        ValueError: 이미지가 전혀 없을 때
    """
    # 이미지 — 필수 (다양한 필드명 수용)
    image = body.get("image_base64") or body.get("image") or body.get("cxr_image")
    s3_key = body.get("s3_key") or body.get("s3_path") or body.get("image_s3_path")

    if not image and not s3_key:
        raise ValueError("이미지가 필요합니다 (image_base64 또는 s3_key)")

    # 환자 정보 — 있으면 가져옴, 없으면 빈 dict
    patient_info = dict(body.get("patient_info", {}))

    # 루트 레벨 필드 매핑
    if "age" in body and "age" not in patient_info:
        patient_info["age"] = body["age"]
    if "sex" in body and "sex" not in patient_info:
        patient_info["sex"] = body["sex"]
    if "gender" in body and "sex" not in patient_info:
        patient_info["sex"] = body["gender"]

    # 이전 모달 결과 (list 또는 단일 dict 수용)
    prior_results = body.get("prior_results", [])
    if isinstance(prior_results, dict):
        prior_results = [prior_results]

    # 옵션 — DEFAULT_OPTIONS에 사용자 옵션 머지
    user_options = body.get("options", {})
    options = {**DEFAULT_OPTIONS, **user_options}

    return {
        "image_base64": image,
        "s3_key": s3_key,
        "patient_info": patient_info,
        "prior_results": prior_results,
        "options": options,
        "raw_input": body,
    }
