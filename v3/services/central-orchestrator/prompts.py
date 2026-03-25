"""
central-orchestrator — Bedrock prompt 템플릿.

LLM에게 다음 검사를 결정하도록 요청하는 프롬프트 구성.
구조화된 JSON 응답을 강제하여 파싱 안정성 확보.

이 파일은 오케스트레이터에서 가장 중요한 튜닝 포인트입니다.
프롬프트 문구, temperature, 검사 우선순위 등을 수정하여
LLM의 검사 결정 품질을 개선할 수 있습니다.
"""

import json
import logging
from typing import Any

import boto3
from botocore.config import Config as BotoConfig

from config import settings

logger = logging.getLogger("orchestrator.prompts")

# ── Bedrock 클라이언트 (Lazy 초기화) ─────────────────────────────────
# 모듈 레벨에서 한 번만 생성하여 재사용 (커넥션 오버헤드 절감)
_bedrock_client = None


def _get_bedrock_client():
    """
    Bedrock Runtime 클라이언트를 지연 초기화하여 반환.

    첫 호출 시에만 boto3 클라이언트를 생성하고, 이후에는 캐시된 인스턴스를 재사용합니다.
    adaptive 재시도 모드로 일시적 오류에 대한 복원력을 확보합니다.
    """
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = boto3.client(
            "bedrock-runtime",
            region_name=settings.bedrock_region,
            config=BotoConfig(
                retries={"max_attempts": 3, "mode": "adaptive"},  # 적응형 재시도
                read_timeout=60,      # 읽기 타임아웃 (LLM 응답 대기)
                connect_timeout=10,   # 연결 타임아웃
            ),
        )
    return _bedrock_client


# ╔══════════════════════════════════════════════════════════╗
# ║  TODO: [팀원D] 프롬프트 수정 포인트                       ║
# ║  LLM의 검사 결정 품질을 여기서 조정합니다.                 ║
# ║  temperature, 프롬프트 문구, 검사 우선순위 등              ║
# ║                                                          ║
# ║  수정 가이드:                                             ║
# ║  1. NEXT_EXAM_SYSTEM_PROMPT: LLM의 역할과 규칙 정의       ║
# ║     - Available examinations 섹션에 새 검사 추가 가능      ║
# ║     - Rules 섹션에서 검사 결정 기준 변경 가능              ║
# ║  2. NEXT_EXAM_USER_TEMPLATE: 환자 정보 전달 형식          ║
# ║     - 프롬프트 구조나 질문 방식 변경 가능                  ║
# ║  3. ask_bedrock_next_exam(): temperature 등 LLM 파라미터  ║
# ╚══════════════════════════════════════════════════════════╝

# ── 시스템 프롬프트 ──────────────────────────────────────────────────
# LLM에게 부여하는 역할과 규칙을 정의합니다.
# "senior clinical decision support AI"로 역할을 설정하여
# 임상적 판단 능력을 최대한 이끌어냅니다.

NEXT_EXAM_SYSTEM_PROMPT = """\
You are a senior clinical decision support AI for a medical examination workflow.

Available examinations:
- "chest": Chest X-Ray analysis (detects cardiomegaly, pneumonia, effusion, pneumothorax, atelectasis, etc.)
- "ecg": ECG/EKG analysis (detects arrhythmias, LVH, ischemia, conduction abnormalities, etc.)
- "blood": Blood test analysis (CBC, metabolic panel, cardiac markers, etc.)

Rules:
1. Based on the patient info and accumulated exam results so far, decide the NEXT most clinically relevant exam.
2. Do NOT repeat an exam that has already been performed.
3. If you have enough information to make a clinical assessment, return "DONE".
4. Always provide clinical reasoning for your decision.
5. Respond ONLY with valid JSON — no markdown, no explanation outside the JSON.

Response format:
{
    "next_exam": "chest" | "ecg" | "blood" | "DONE",
    "reasoning": "Brief clinical reasoning for this decision"
}
"""

# ── 유저 메시지 템플릿 ───────────────────────────────────────────────
# 환자 정보와 지금까지의 검사 결과를 구조화하여 LLM에 전달합니다.
# {변수명} 형태의 플레이스홀더는 ask_bedrock_next_exam()에서 채워집니다.

NEXT_EXAM_USER_TEMPLATE = """\
## Patient Information
- Age: {age}
- Sex: {sex}
- Chief Complaint: {chief_complaint}
- History: {history}

## Examinations Completed So Far
{completed_exams}

## Already Performed Exams
{performed_list}

Based on the patient's presentation and results so far, which examination should be performed next?
Respond with JSON only.
"""


def _format_completed_exams(accumulated_results: list[dict]) -> str:
    """
    누적된 모달 검사 결과를 프롬프트용 텍스트로 포맷.

    각 검사 결과를 마크다운 형태로 변환하여 LLM이 읽기 쉽게 합니다.
    findings의 detected/confidence/detail을 구조화하여 표시합니다.
    """
    if not accumulated_results:
        return "None yet — this is the first examination."

    sections = []
    for i, result in enumerate(accumulated_results, 1):
        modal = result.get("modal", "unknown")
        summary = result.get("summary", "No summary")
        findings = result.get("findings", [])
        # 각 finding을 "검출됨/미검출" 형태로 변환
        findings_text = "\n".join(
            f"  - {f.get('name', '?')}: {'Detected' if f.get('detected') else 'Not detected'} "
            f"(confidence: {f.get('confidence', 0):.2f}) {f.get('detail', '')}"
            for f in findings
        ) or "  (no findings)"
        sections.append(f"### {i}. {modal.upper()}\nSummary: {summary}\nFindings:\n{findings_text}")

    return "\n\n".join(sections)


def _get_performed_list(accumulated_results: list[dict]) -> str:
    """이미 수행된 검사 이름을 쉼표로 구분된 문자열로 반환."""
    performed = [r.get("modal", "unknown") for r in accumulated_results]
    return ", ".join(performed) if performed else "None"


async def ask_bedrock_next_exam(
    patient_info: dict[str, Any],
    accumulated_results: list[dict],
) -> dict[str, str]:
    """
    Bedrock LLM을 호출하여 다음 검사를 결정.

    처리 흐름:
    1. 유저 메시지 구성 (환자 정보 + 누적 결과)
    2. Bedrock API 호출 (Claude Messages API 형식)
    3. JSON 응답 파싱 및 유효성 검증
    4. 유효하지 않은 검사명이면 DONE으로 안전하게 폴백

    Returns:
        {"next_exam": "chest"|"ecg"|"blood"|"DONE", "reasoning": "임상적 근거"}
    """
    # 유저 메시지 구성: 환자 정보와 누적 결과를 템플릿에 채움
    user_message = NEXT_EXAM_USER_TEMPLATE.format(
        age=patient_info.get("age", "unknown"),
        sex=patient_info.get("sex", "unknown"),
        chief_complaint=patient_info.get("chief_complaint", "unknown"),
        history=", ".join(patient_info.get("history", [])) or "None",
        completed_exams=_format_completed_exams(accumulated_results),
        performed_list=_get_performed_list(accumulated_results),
    )

    # ╔══════════════════════════════════════════════════════════╗
    # ║  TODO: [팀원D] LLM 파라미터 튜닝 포인트                   ║
    # ║  - temperature: 낮을수록 결정적, 높을수록 창의적           ║
    # ║    (현재 0.1 — 매우 결정적이고 일관된 검사 결정)           ║
    # ║  - max_tokens: 응답 최대 길이 (JSON이므로 512면 충분)      ║
    # ╚══════════════════════════════════════════════════════════╝
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,          # JSON 응답이므로 512 토큰이면 충분
        "temperature": 0.1,         # 낮은 temperature = 일관된 검사 결정
        "system": NEXT_EXAM_SYSTEM_PROMPT,
        "messages": [
            {"role": "user", "content": user_message},
        ],
    })

    logger.info("Calling Bedrock for next exam decision (model=%s)", settings.bedrock_model_id)

    try:
        client = _get_bedrock_client()
        # Bedrock invoke_model API 호출 (동기 — boto3는 비동기 미지원)
        response = client.invoke_model(
            modelId=settings.bedrock_model_id,
            contentType="application/json",
            accept="application/json",
            body=body,
        )

        # 응답 파싱: Bedrock → response body → content[0].text → JSON
        response_body = json.loads(response["body"].read())
        content_text = response_body.get("content", [{}])[0].get("text", "")
        logger.debug("Bedrock raw response: %s", content_text)

        # JSON 파싱: LLM 응답에서 next_exam과 reasoning 추출
        parsed = json.loads(content_text.strip())
        next_exam = parsed.get("next_exam", "DONE")
        reasoning = parsed.get("reasoning", "")

        # 유효성 검증: 허용된 검사명이 아니면 안전하게 DONE으로 폴백
        valid_exams = {"chest", "ecg", "blood", "DONE"}
        if next_exam not in valid_exams:
            logger.warning("Invalid next_exam '%s' from Bedrock, defaulting to DONE", next_exam)
            next_exam = "DONE"
            reasoning = f"Invalid exam '{next_exam}' returned; stopping."

        logger.info("Bedrock decision: next_exam=%s, reasoning=%s", next_exam, reasoning)
        return {"next_exam": next_exam, "reasoning": reasoning}

    except json.JSONDecodeError as e:
        # LLM이 유효하지 않은 JSON을 반환한 경우 → DONE으로 안전하게 종료
        logger.error("Failed to parse Bedrock JSON response: %s", e)
        return {"next_exam": "DONE", "reasoning": f"JSON parse error: {e}"}
    except Exception as e:
        # Bedrock API 호출 자체가 실패한 경우 → 예외를 상위로 전파
        logger.error("Bedrock invocation failed: %s", e)
        raise
