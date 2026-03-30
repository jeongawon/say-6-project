"""
ecg-svc report generator — Calls AWS Bedrock to produce a clinical ECG report.

Fallback: if Bedrock is unavailable, generates a structured template report
from the findings list so the pipeline never breaks.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import sys
sys.path.insert(0, "/app/shared")
from schemas import Finding, PatientInfo

logger = logging.getLogger("ecg-svc.report")


# ── Bedrock client (lazy init) ───────────────────────────────────────
_bedrock_client = None


def _get_bedrock_client(region: str):
    global _bedrock_client
    if _bedrock_client is None:
        try:
            import boto3
            _bedrock_client = boto3.client(
                "bedrock-runtime", region_name=region
            )
        except Exception as exc:
            logger.warning("Failed to create Bedrock client: %s", exc)
    return _bedrock_client


# ── Public API ───────────────────────────────────────────────────────
async def generate_ecg_report(
    patient_info: PatientInfo,
    findings: list[Finding],
    bedrock_region: str,
    bedrock_model_id: str,
    context: dict | None = None,
) -> str:
    """Generate an ECG interpretation report using Bedrock, with fallback."""
    try:
        return _call_bedrock(patient_info, findings, bedrock_region, bedrock_model_id, context)
    except Exception as exc:
        logger.warning("Bedrock call failed, using template fallback: %s", exc)
        return _template_report(patient_info, findings, context)


# ── Bedrock call ─────────────────────────────────────────────────────
def _call_bedrock(
    patient_info: PatientInfo,
    findings: list[Finding],
    region: str,
    model_id: str,
    context: dict | None,
) -> str:
    client = _get_bedrock_client(region)
    if client is None:
        raise RuntimeError("Bedrock client not available")

    findings_text = "\n".join(
        f"- {f.name}: detected={f.detected}, confidence={f.confidence}, detail={f.detail}"
        for f in findings
    )
    context_text = json.dumps(context, ensure_ascii=False) if context else "None"

    prompt = f"""You are a cardiologist writing a formal 12-lead ECG interpretation report.

Patient: {patient_info.age}y {patient_info.sex}, Chief complaint: {patient_info.chief_complaint}
History: {', '.join(patient_info.history) if patient_info.history else 'None'}

ECG Analysis Findings:
{findings_text}

Previous modality context:
{context_text}

Write a concise, structured ECG report in Korean with the following sections:
1. Rate & Rhythm
2. Axis
3. Intervals (PR, QRS, QTc)
4. ST-T Changes
5. Chamber Hypertrophy
6. Conduction Abnormalities
7. Impression
8. Clinical Correlation (considering prior modality results if available)

Be precise and use standard cardiology terminology."""

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}],
    })

    response = client.invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=body,
    )
    result = json.loads(response["body"].read())
    return result["content"][0]["text"]


# ── Template fallback ────────────────────────────────────────────────
def _template_report(
    patient_info: PatientInfo,
    findings: list[Finding],
    context: dict | None,
) -> str:
    """Produce a structured report without LLM."""
    detected = [f for f in findings if f.detected]
    normal = [f for f in findings if not f.detected]

    lines = [
        "[ECG 판독 소견서]",
        f"환자: {patient_info.age}세 {patient_info.sex}",
        f"주소: {patient_info.chief_complaint}",
        "",
    ]

    if detected:
        lines.append("== 주요 소견 ==")
        for f in detected:
            label = f.name.replace("_", " ").title()
            lines.append(f"  - {label} (confidence {f.confidence:.0%}): {f.detail}")
        lines.append("")

    if normal:
        lines.append("== 정상 소견 ==")
        for f in normal:
            label = f.name.replace("_", " ").title()
            lines.append(f"  - {label}: {f.detail}")
        lines.append("")

    if context:
        lines.append("== 이전 검사 참조 ==")
        for modal, info in context.items():
            summary = info.get("summary", "") if isinstance(info, dict) else str(info)
            lines.append(f"  - {modal}: {summary}")
        lines.append("")

    lines.append("== Impression ==")
    if detected:
        names = ", ".join(f.name.replace("_", " ") for f in detected)
        lines.append(f"  {names} 소견이 관찰됩니다. 임상 소견과 종합 판단이 필요합니다.")
    else:
        lines.append("  특이 소견 없는 정상 ECG입니다.")

    return "\n".join(lines)
