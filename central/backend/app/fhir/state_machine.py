"""§4 상태 기계 — ServiceRequest / DiagnosticReport 라이프사이클."""
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
