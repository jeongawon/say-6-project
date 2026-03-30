"""
blood-svc report generator — Calls AWS Bedrock to produce a clinical blood test report.

Fallback: structured template report if Bedrock is unavailable.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import sys
sys.path.insert(0, "/app/shared")
from schemas import Finding, PatientInfo

logger = logging.getLogger("blood-svc.report")


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
async def generate_blood_report(
    patient_info: PatientInfo,
    findings: list[Finding],
    bedrock_region: str,
    bedrock_model_id: str,
    context: dict | None = None,
) -> str:
    """Generate a blood test interpretation report using Bedrock, with fallback."""
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

    prompt = f"""You are a clinical pathologist writing a formal laboratory test interpretation report.

Patient: {patient_info.age}y {patient_info.sex}, Chief complaint: {patient_info.chief_complaint}
History: {', '.join(patient_info.history) if patient_info.history else 'None'}

Laboratory Analysis Findings:
{findings_text}

Previous modality context (CXR, ECG results if available):
{context_text}

Write a concise, structured lab report in Korean with the following sections:
1. CBC Analysis
2. Metabolic Panel (BMP)
3. Cardiac Markers
4. Liver Function
5. Inflammatory Markers (if available)
6. Composite Risk Assessment
7. Impression
8. Clinical Correlation (integrate with imaging/ECG findings if available)

Flag critical values prominently. Provide clinical significance for each abnormality.
Use standard laboratory medicine terminology."""

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
    abnormal = [f for f in findings if f.detected]
    normal = [f for f in findings if not f.detected]

    # Separate composite assessments from individual tests
    composite_names = {
        "heart_failure_indicator",
        "myocardial_injury_indicator",
        "renal_impairment",
        "anemia",
        "infection_inflammation_indicator",
    }
    composites = [f for f in abnormal if f.name in composite_names]
    individual_abnormal = [f for f in abnormal if f.name not in composite_names]

    lines = [
        "[혈액검사 판독 소견서]",
        f"환자: {patient_info.age}세 {patient_info.sex}",
        f"주소: {patient_info.chief_complaint}",
        "",
    ]

    # Critical values first
    critical = [f for f in individual_abnormal if "CRITICAL" in (f.detail or "")]
    if critical:
        lines.append("** 위급 수치 (Critical Values) **")
        for f in critical:
            label = f.name.replace("_abnormal", "").replace("_", " ").upper()
            lines.append(f"  !! {label}: {f.detail}")
        lines.append("")

    # Abnormal values
    if individual_abnormal:
        lines.append("== 비정상 수치 ==")
        for f in individual_abnormal:
            if f in critical:
                continue
            label = f.name.replace("_abnormal", "").replace("_", " ").title()
            lines.append(f"  - {label}: {f.detail}")
        lines.append("")

    # Composite assessments
    if composites:
        lines.append("== 종합 평가 ==")
        for f in composites:
            label = f.name.replace("_", " ").title()
            lines.append(f"  - {label} (confidence {f.confidence:.0%}): {f.detail}")
        lines.append("")

    # Normal values (brief)
    if normal:
        lines.append("== 정상 수치 ==")
        normal_names = [
            f.name.replace("_normal", "").replace("_", " ").title()
            for f in normal
        ]
        lines.append(f"  {', '.join(normal_names)}")
        lines.append("")

    # Previous modality context
    if context:
        lines.append("== 이전 검사 참조 ==")
        for modal, info in context.items():
            summary = info.get("summary", "") if isinstance(info, dict) else str(info)
            lines.append(f"  - {modal}: {summary}")
        lines.append("")

    # Impression
    lines.append("== Impression ==")
    if composites or individual_abnormal:
        names = []
        for f in composites:
            names.append(f.name.replace("_", " "))
        for f in individual_abnormal[:5]:
            names.append(f.name.replace("_abnormal", "").replace("_", " "))
        lines.append(f"  {', '.join(names)} 소견이 관찰됩니다.")
        lines.append("  임상 소견과 종합하여 추가 검사 및 치료 계획을 수립하시기 바랍니다.")
    else:
        lines.append("  주요 혈액검사 수치 정상 범위입니다.")

    return "\n".join(lines)
