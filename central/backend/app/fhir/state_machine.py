"""
§4 상태 기계 — ServiceRequest / DiagnosticReport 라이프사이클.

[이 파일이 하는 일]
FHIR 리소스의 상태(status)가 올바른 순서로만 바뀌게 검증.
잘못된 전이를 시도하면 에러 발생.

[ServiceRequest 상태 전이]
draft(AI 제안) → active(의사 승인) → completed(모달 완료)
draft → revoked(의사 기각)
active → revoked(모달 실패)
completed, revoked → 더 이상 변경 불가

[DiagnosticReport 상태 전이]
preliminary(AI 생성) → final(의사 서명)
final → amended(서명 후 수정)
"""
from __future__ import annotations

from app.fhir import client as fhir_client


class InvalidTransitionError(Exception):
    pass


# ── 4.1 ServiceRequest ───────────────────────────────────
SR_TRANSITIONS: dict[str, set[str]] = {
    "draft":     {"active", "revoked"},
    "active":    {"completed", "revoked"},
    "completed": set(),
    "revoked":   set(),
}


async def transition_service_request(sr_id: str, new_status: str) -> dict:
    """Validate and apply ServiceRequest status transition."""
    current = await fhir_client.read("ServiceRequest", sr_id)
    cur_status = current["status"]

    if new_status not in SR_TRANSITIONS.get(cur_status, set()):
        raise InvalidTransitionError(
            f"ServiceRequest/{sr_id}: {cur_status} → {new_status} 불가"
        )

    return await fhir_client.patch(
        "ServiceRequest", sr_id, {"status": new_status}
    )


# ── 4.2 DiagnosticReport ────────────────────────────────
DR_TRANSITIONS: dict[str, set[str]] = {
    "preliminary": {"final"},
    "final":       {"amended"},
    "amended":     set(),
}


async def transition_diagnostic_report(dr_id: str, new_status: str) -> dict:
    """Validate and apply DiagnosticReport status transition."""
    current = await fhir_client.read("DiagnosticReport", dr_id)
    cur_status = current["status"]

    if new_status not in DR_TRANSITIONS.get(cur_status, set()):
        raise InvalidTransitionError(
            f"DiagnosticReport/{dr_id}: {cur_status} → {new_status} 불가"
        )

    return await fhir_client.patch(
        "DiagnosticReport", dr_id, {"status": new_status}
    )
