"""POST /orders/{id}/approve | reject — ServiceRequest 상태 전이."""
from __future__ import annotations

import asyncio
import logging
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional

from app.fhir import client as fhir
from app.fhir.state_machine import (
    transition_service_request,
    InvalidTransitionError,
)
from app.fhir.resources import (
    build_diagnostic_report,
    convert_ecg_to_observations,
    convert_cxr_to_observations,
)
from app.api.ws import broadcast
from app.clients.sagemaker_invoke import invoke_endpoint
from app.config import SAGEMAKER_CXR_ENDPOINT, SAGEMAKER_ECG_ENDPOINT

logger = logging.getLogger(__name__)
router = APIRouter()

# 모달 → SageMaker endpoint 매핑
MODALITY_ENDPOINTS = {
    "CXR": SAGEMAKER_CXR_ENDPOINT,
    "ECG": SAGEMAKER_ECG_ENDPOINT,
}


class RejectBody(BaseModel):
    reason: Optional[str] = None


# ── 모달 실행 백그라운드 태스크 ───────────────────────────
async def _execute_modal_and_complete(sr_id: str, sr: dict):
    """
    승인된 ServiceRequest의 모달을 실행하고,
    결과 Observation 저장 → SR completed → WS 푸시.
    """
    encounter_ref = sr.get("encounter", {}).get("reference", "")
    patient_ref = sr.get("subject", {}).get("reference", "")
    encounter_id = encounter_ref.replace("Encounter/", "")
    patient_id = patient_ref.replace("Patient/", "")

    # SR의 code에서 모달 종류 추출
    code_coding = sr.get("code", {}).get("coding", [{}])[0]
    modality = _detect_modality(code_coding)

    try:
        # SageMaker / 외부 서비스 호출 (endpoint 없으면 mock)
        endpoint = MODALITY_ENDPOINTS.get(modality, "")
        if endpoint:
            modal_result = invoke_endpoint(endpoint, {
                "patient_id": patient_id,
                "encounter_id": encounter_id,
            })
        else:
            modal_result = _mock_modal_result(modality)

        # 모달별 변환 함수로 FHIR Observation 리스트 생성
        if modality == "ECG":
            obs_list = convert_ecg_to_observations(
                patient_id, encounter_id, modal_result
            )
        elif modality == "CXR":
            obs_list = convert_cxr_to_observations(
                patient_id, encounter_id, modal_result
            )
        else:
            obs_list = [{
                "resourceType": "Observation",
                "status": "preliminary",
                "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                           "code": "laboratory"}]}],
                "code": {"coding": [code_coding]},
                "subject": {"reference": patient_ref},
                "encounter": {"reference": encounter_ref},
                "valueString": modal_result.get("summary", str(modal_result)),
            }]

        # FHIR 서버에 Observation 저장
        saved_obs_ids = []
        for obs in obs_list:
            obs_res = await fhir.create("Observation", obs)
            saved_obs_ids.append(obs_res["id"])

        # SR: active → completed
        await transition_service_request(sr_id, "completed")

        # WebSocket 푸시
        await broadcast(encounter_id, {
            "event": "modal_completed",
            "service_request_id": sr_id,
            "modality": modality,
            "observation_ids": saved_obs_ids,
            "summary": modal_result.get("summary", ""),
            "risk_level": modal_result.get("risk_level", "routine"),
        })

    except Exception as e:
        logger.exception(f"Modal execution failed for SR/{sr_id}")
        # 실패 시 SR: active → revoked, note에 에러 기록
        try:
            await fhir.patch("ServiceRequest", sr_id, {
                "status": "revoked",
                "note": [{"text": f"모달 실행 실패: {str(e)}"}],
            })
            await broadcast(encounter_id, {
                "event": "modal_failed",
                "service_request_id": sr_id,
                "error": str(e),
            })
        except Exception:
            logger.exception("Failed to update SR after modal error")


def _detect_modality(code_coding: dict) -> str:
    """LOINC 코드에서 모달 종류 추출."""
    code = code_coding.get("code", "")
    display = code_coding.get("display", "").lower()
    if code == "36643-5" or "cxr" in display or "chest" in display:
        return "CXR"
    if code == "11524-6" or "ecg" in display or "ekg" in display:
        return "ECG"
    if "lab" in display:
        return "LAB"
    return "UNKNOWN"


def _mock_modal_result(modality: str) -> dict:
    """개발/데모용 mock — 실제 서비스 아웃풋 포맷과 동일."""
    if modality == "ECG":
        return {
            "status": "ok",
            "modal": "ecg",
            "findings": [
                {
                    "name": "stemi",
                    "confidence": 0.92,
                    "detail": "ST분절 상승 심근경색 (신뢰도 92.0%)",
                    "severity": "critical",
                    "recommendation": "즉시 심도자실 활성화",
                }
            ],
            "summary": "[위험] ST분절 상승 심근경색 이상 소견 감지",
            "risk_level": "critical",
            "ecg_vitals": {
                "heart_rate": 88.0,
                "bradycardia": False,
                "tachycardia": False,
                "irregular_rhythm": False,
            },
            "all_probs": {"stemi": 0.92, "normal_ecg": 0.05},
        }
    elif modality == "CXR":
        return {
            "status": "success",
            "modal": "chest",
            "findings": [
                {
                    "name": "Cardiomegaly",
                    "detected": True,
                    "confidence": 0.82,
                    "detail": "심비대 소견",
                    "severity": "moderate",
                    "location": "bilateral",
                    "recommendation": "심초음파 추가 검사 권고",
                    "evidence": ["Enlarged cardiac silhouette", "CTR > 0.5"],
                    "impression_text": "Cardiomegaly with possible pulmonary edema",
                }
            ],
            "summary": "Cardiomegaly with possible pulmonary edema",
            "risk_level": "urgent",
            "findings_text": "The cardiac silhouette is enlarged.",
            "impression": "1. Cardiomegaly",
            "measurements": {"ctr": 0.58},
        }
    else:
        return {
            "status": "success",
            "modal": "lab",
            "findings": [],
            "summary": f"{modality} analysis completed (mock)",
            "risk_level": "routine",
        }


# ── Agent 재호출 백그라운드 태스크 ────────────────────────
async def _agent_reconsider(sr_id: str, sr: dict, reason: str):
    """
    기각된 SR을 바탕으로 Agent에게 대안을 요청하고,
    새 ServiceRequest(draft)를 생성 → WS 푸시.
    """
    encounter_ref = sr.get("encounter", {}).get("reference", "")
    patient_ref = sr.get("subject", {}).get("reference", "")
    encounter_id = encounter_ref.replace("Encounter/", "")
    patient_id = patient_ref.replace("Patient/", "")

    try:
        from app.agent.tools import propose_order, get_encounter_context

        # 현재 encounter 상태 수집
        context = await get_encounter_context(encounter_id)

        # 기각된 모달 정보
        rejected_code = sr.get("code", {}).get("coding", [{}])[0]
        rejected_modality = _detect_modality(rejected_code)

        # 간단한 대안 로직: 기각된 모달 제외하고 다른 모달 제안
        all_modalities = {"CXR", "ECG", "LAB"}
        completed = {_detect_modality(s.get("code", {}).get("coding", [{}])[0])
                     for s in context.get("service_requests", [])
                     if s.get("status") in ("completed", "active")}
        remaining = all_modalities - completed - {rejected_modality}

        if remaining:
            from app.fhir.codes import LOINC_MODALITY
            next_mod = remaining.pop()
            mod_info = LOINC_MODALITY.get(next_mod.lower(), {"code": "unknown", "display": next_mod})
            new_sr = await propose_order(
                patient_id=patient_id,
                encounter_id=encounter_id,
                modality=next_mod,
                reason_text=f"의사가 {rejected_modality}를 기각 (사유: {reason}). 대안으로 {next_mod} 제안.",
                priority="routine",
            )
            await broadcast(encounter_id, {
                "event": "new_proposal",
                "service_request_id": new_sr["id"],
                "modality": next_mod,
                "reason": f"{rejected_modality} 기각 후 대안 제안",
            })
        else:
            # 남은 모달 없음 → 리포트 생성 단계로
            await broadcast(encounter_id, {
                "event": "ready_for_report",
                "message": "모든 모달 완료/기각. 리포트 생성 가능.",
            })

    except Exception as e:
        logger.exception(f"Agent reconsider failed for SR/{sr_id}")
        await broadcast(encounter_id, {
            "event": "agent_error",
            "error": str(e),
        })


# ── API 엔드포인트 ───────────────────────────────────────
@router.post("/{sr_id}/approve")
async def approve_order(sr_id: str, background_tasks: BackgroundTasks):
    """의사 승인: draft → active → 모달 실행 → completed."""
    try:
        await transition_service_request(sr_id, "active")
        sr = await fhir.read("ServiceRequest", sr_id)

        # 모달 실행을 백그라운드로
        background_tasks.add_task(_execute_modal_and_complete, sr_id, sr)

        return {"service_request_id": sr_id, "status": "active"}
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.exception("Order approve failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{sr_id}/reject")
async def reject_order(
    sr_id: str,
    body: RejectBody = RejectBody(),
    background_tasks: BackgroundTasks = None,
):
    """의사 기각: draft → revoked → Agent 대안 제안."""
    try:
        sr = await fhir.read("ServiceRequest", sr_id)

        # 기각 사유를 note에 추가
        notes = sr.get("note", [])
        if body.reason:
            notes.append({"text": f"기각 사유: {body.reason}"})

        await fhir.patch("ServiceRequest", sr_id, {
            "status": "revoked",
            "note": notes,
        })

        # Agent 재호출을 백그라운드로
        if background_tasks:
            background_tasks.add_task(
                _agent_reconsider, sr_id, sr, body.reason or ""
            )

        return {"service_request_id": sr_id, "status": "revoked"}
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.exception("Order reject failed")
        raise HTTPException(status_code=500, detail=str(e))
