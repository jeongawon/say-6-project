"""
central-orchestrator — Modal 서비스 HTTP 클라이언트.

chest-svc, ecg-svc, blood-svc 및 report-svc 호출.
공통 PredictRequest/PredictResponse 스키마 사용.

새로운 모달 서비스를 추가하려면:
1. config.py에 새 URL 환경 변수 추가
2. 아래의 MODAL_URLS에 매핑 추가
3. prompts.py의 시스템 프롬프트에도 새 검사 항목 추가
"""

import logging
from typing import Any

import httpx

from config import settings

logger = logging.getLogger("orchestrator.modal_client")

# ╔══════════════════════════════════════════════════════════╗
# ║  TODO: [팀원D] 새 모달 서비스 추가 시 수정 포인트         ║
# ║  새로운 검사 서비스 (예: "ultrasound", "mri")를            ║
# ║  추가하려면 아래 딕셔너리에 매핑을 추가하세요.             ║
# ║  config.py에도 해당 URL 환경 변수를 추가해야 합니다.       ║
# ╚══════════════════════════════════════════════════════════╝

# ── 모달 서비스 URL 매핑 ──────────────────────────────────────────────
# 키: 모달 이름 (Bedrock이 결정하는 값과 동일해야 함)
# 값: 해당 서비스의 /predict 엔드포인트 URL
MODAL_URLS: dict[str, str] = {
    "chest": settings.chest_url,   # 흉부 X-Ray 분석 서비스
    "ecg": settings.ecg_url,       # ECG 분석 서비스
    "blood": settings.blood_url,   # 혈액 검사 분석 서비스
}

# HTTP 클라이언트 타임아웃 설정
DEFAULT_TIMEOUT = httpx.Timeout(
    connect=10.0,     # 연결 타임아웃
    read=120.0,       # 읽기 타임아웃 (모델 추론은 시간이 걸릴 수 있음)
    write=10.0,       # 쓰기 타임아웃
    pool=10.0,        # 커넥션 풀 타임아웃
)


async def predict(
    modal: str,
    patient_id: str,
    patient_info: dict[str, Any],
    data: dict[str, Any],
    accumulated_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    모달 예측 서비스 호출.

    이전 검사 결과를 context로 포함하여 전달하므로,
    각 모달 서비스는 다른 검사 결과를 참고하여 분석할 수 있습니다.

    Args:
        modal: 서비스 식별자 ("chest", "ecg", "blood")
        patient_id: 환자 고유 ID
        patient_info: 환자 인구통계 및 병력
        data: 모달별 입력 데이터 (예: 이미지 경로, ECG 신호값)
        accumulated_results: 이전 검사 결과들 (context 구성용)

    Returns:
        모달 예측 응답 dict (PredictResponse 호환)
    """
    # URL 매핑에서 해당 모달의 엔드포인트 조회
    url = MODAL_URLS.get(modal)
    if not url:
        logger.error("Unknown modal service: %s", modal)
        return {
            "status": "error",
            "modal": modal,
            "findings": [],
            "summary": f"Unknown modal service: {modal}",
        }

    # 이전 검사 결과로 context 구성
    # 각 모달 서비스가 다른 검사 결과를 참고할 수 있도록 함
    context = {}
    for result in accumulated_results:
        prev_modal = result.get("modal", "unknown")
        context[prev_modal] = {
            "findings": result.get("findings", []),
            "summary": result.get("summary", ""),
        }

    # PredictRequest 페이로드 구성 (공통 스키마)
    payload = {
        "patient_id": patient_id,
        "patient_info": patient_info,
        "data": data.get(modal, {}),    # 해당 모달의 입력 데이터만 추출
        "context": context,              # 이전 검사 결과 컨텍스트
    }

    logger.info("Calling modal service: %s at %s", modal, url)

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()

        result = response.json()
        result["modal"] = modal  # 응답에 모달 식별자 보장
        logger.info(
            "Modal %s responded: status=%s, findings=%d",
            modal,
            result.get("status", "unknown"),
            len(result.get("findings", [])),
        )
        return result

    # ── 에러 처리: 각 에러 유형별로 안전한 응답 반환 ──
    # 모달 서비스 에러가 전체 오케스트레이션을 중단하지 않도록 함
    except httpx.TimeoutException:
        logger.error("Timeout calling modal service %s at %s", modal, url)
        return {
            "status": "error",
            "modal": modal,
            "findings": [],
            "summary": f"Timeout calling {modal} service",
        }
    except httpx.HTTPStatusError as e:
        logger.error("HTTP error from %s: %s %s", modal, e.response.status_code, e.response.text[:200])
        return {
            "status": "error",
            "modal": modal,
            "findings": [],
            "summary": f"HTTP {e.response.status_code} from {modal} service",
        }
    except httpx.ConnectError:
        logger.error("Connection refused: %s at %s", modal, url)
        return {
            "status": "error",
            "modal": modal,
            "findings": [],
            "summary": f"Cannot connect to {modal} service at {url}",
        }
    except Exception as e:
        logger.error("Unexpected error calling %s: %s", modal, e)
        return {
            "status": "error",
            "modal": modal,
            "findings": [],
            "summary": f"Unexpected error: {e}",
        }


async def call_report_service(
    patient_id: str,
    patient_info: dict[str, Any],
    accumulated_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    종합 소견서 생성 서비스 (report-svc) 호출.

    모든 모달 검사 결과를 전달하여 최종 종합 소견서와 진단을 생성합니다.

    Args:
        patient_id: 환자 고유 ID
        patient_info: 환자 인구통계 정보
        accumulated_results: 전체 모달 검사 결과 리스트

    Returns:
        {"status": "success", "report": "종합 소견서", "diagnosis": "최종 진단"}
    """
    # ReportRequest 페이로드 구성 (공통 스키마)
    payload = {
        "patient_id": patient_id,
        "patient_info": patient_info,
        "modal_reports": accumulated_results,    # 전체 검사 결과
    }

    logger.info("Calling report service at %s", settings.report_url)

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.post(settings.report_url, json=payload)
            response.raise_for_status()

        result = response.json()
        logger.info("Report service responded: status=%s", result.get("status", "unknown"))
        return result

    # ── 에러 처리: 소견서 생성 실패 시 안전한 기본 응답 반환 ──
    except httpx.TimeoutException:
        logger.error("Timeout calling report service")
        return {
            "status": "error",
            "report": "Report generation timed out.",
            "diagnosis": "Unable to generate diagnosis — report service timeout.",
        }
    except httpx.HTTPStatusError as e:
        logger.error("HTTP error from report service: %s", e.response.status_code)
        return {
            "status": "error",
            "report": f"Report service HTTP {e.response.status_code}.",
            "diagnosis": "Unable to generate diagnosis — report service error.",
        }
    except Exception as e:
        logger.error("Unexpected error calling report service: %s", e)
        return {
            "status": "error",
            "report": f"Unexpected error: {e}",
            "diagnosis": "Unable to generate diagnosis.",
        }
