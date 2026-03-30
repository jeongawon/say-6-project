"""
Bedrock Claude 종합 소견서 생성기 — v2 report_generator.py에서 마이그레이션.
Lambda/S3 의존성 제거, K8s 마이크로서비스용.

[핵심 흐름]
1. generate()          → 프롬프트 조립 → Bedrock 호출 → 응답 파싱 → 보고서 반환
2. _build_system_prompt() → 시스템 프롬프트 + RAG 섹션 조립
3. _build_user_prompt()   → 환자 정보 + 모달별 결과를 유저 프롬프트로 조립
4. _invoke_bedrock()      → AWS Bedrock Claude API 호출
5. _parse_response()      → Claude 응답에서 JSON 구조 추출

[팀원E 수정 포인트]
- _invoke_bedrock(): Bedrock API 호출 파라미터 조정
- _parse_response(): 응답 파싱 로직 (JSON 포맷 변경 시)
- _compose_report_text(): 최종 보고서 텍스트 포맷
- _compose_diagnosis_text(): 진단 텍스트 포맷
- _format_modal_reports(): 모달별 결과 → 프롬프트용 텍스트 변환
"""
import json
import logging
import time

import boto3

from config import settings
from prompt_templates import (
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_EN,
    USER_PROMPT_TEMPLATE,
    USER_PROMPT_TEMPLATE_EN,
    RAG_SECTION_PLACEHOLDER,
    RAG_SECTION_PLACEHOLDER_EN,
    RAG_SECTION_TEMPLATE,
)

logger = logging.getLogger("report-svc")


class ReportGenerator:
    """AWS Bedrock Claude를 사용한 종합 소견서 생성."""

    def __init__(self):
        # boto3 Bedrock Runtime 클라이언트 — AWS 자격 증명 필요
        # K8s에서는 IRSA(IAM Roles for Service Accounts) 사용 권장
        self.bedrock = boto3.client(
            "bedrock-runtime",
            region_name=settings.bedrock_region,
        )
        # 사용할 Bedrock 모델 ID
        self.model_id = settings.bedrock_model_id

    # ------------------------------------------------------------------
    # Public API — 외부에서 호출하는 메인 메서드
    # ------------------------------------------------------------------
    def generate(
        self,
        patient_id: str,
        patient_info: dict,
        modal_reports: list[dict],
        lang: str = "ko",
        rag_evidence: list[dict] | None = None,
    ) -> dict:
        """
        멀티모달 분석 결과를 종합하여 최종 진단 보고서 생성.

        Args:
            patient_id: 환자 ID
            patient_info: 환자 정보 dict (age, sex, chief_complaint, history)
            modal_reports: 각 모달의 분석 결과 리스트
                          [{"modal": "chest", "report": "...", "findings": [...], "summary": "..."}, ...]
            lang: 보고서 언어 (ko: 한국어 / en: 영어)
            rag_evidence: RAG 검색 결과 (rag-svc에서 반환된 유사 케이스 리스트, optional)

        Returns:
            {"report": str, "diagnosis": str, "metadata": dict}
        """
        start_time = time.time()

        # 1단계: 프롬프트 조립 — 시스템 프롬프트(역할/규칙) + 유저 프롬프트(데이터)
        system_prompt = self._build_system_prompt(lang, rag_evidence)
        user_prompt = self._build_user_prompt(patient_info, modal_reports, lang)

        # 2단계: Bedrock Claude API 호출
        response = self._invoke_bedrock(
            system_prompt, user_prompt,
            settings.temperature, settings.max_tokens,
        )

        # 3단계: Claude 응답에서 JSON 추출 (실패 시 temperature=0.0으로 재시도)
        try:
            parsed = self._parse_response(response)
        except (ValueError, json.JSONDecodeError):
            # JSON 파싱 실패 — temperature를 0.0으로 낮춰서 재시도
            # 더 결정적인 출력을 유도하여 올바른 JSON 형식 확보
            logger.warning("JSON 파싱 실패 — temperature=0.0으로 재시도")
            response = self._invoke_bedrock(
                system_prompt, user_prompt,
                settings.retry_temperature, settings.max_tokens,
            )
            parsed = self._parse_response(response)

        # 4단계: 파싱된 JSON에서 보고서 구성요소 추출
        narrative = parsed.get("narrative", "")          # 자연어 서술형 판독문
        summary = parsed.get("summary", "")              # 1~2문장 요약
        structured = parsed.get("structured", {})         # 구조화된 소견 (JSON)
        impression = structured.get("impression", summary)  # 종합 인상
        risk_level = structured.get("risk_level", "ROUTINE")  # 위험도 분류
        differential = parsed.get("differential_diagnosis", [])  # 감별 진단 목록

        # 5단계: 최종 보고서 텍스트 조립
        report_text = self._compose_report_text(narrative, structured)
        diagnosis_text = self._compose_diagnosis_text(impression, differential, risk_level)

        # 응답 시간 측정 (밀리초)
        latency_ms = int((time.time() - start_time) * 1000)

        return {
            "report": report_text,       # 종합 판독문 텍스트
            "diagnosis": diagnosis_text,  # 진단 텍스트
            "metadata": {
                "patient_id": patient_id,
                "model_used": self.model_id,
                "input_tokens": response.get("usage", {}).get("input_tokens", 0),
                "output_tokens": response.get("usage", {}).get("output_tokens", 0),
                "latency_ms": latency_ms,
                "risk_level": risk_level,
                "report_language": lang,
                "modals_included": [r.get("modal", "") for r in modal_reports],
            },
        }

    # ------------------------------------------------------------------
    # Bedrock 호출 — AWS Bedrock Claude API
    # ------------------------------------------------------------------
    def _invoke_bedrock(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> dict:
        """
        Bedrock Claude API 호출.

        Anthropic Messages API 형식으로 요청을 구성합니다.
        system 필드에 역할/규칙을, messages 필드에 실제 데이터를 전달합니다.
        """
        body = {
            "anthropic_version": "bedrock-2023-05-31",  # Bedrock Anthropic API 버전
            "max_tokens": max_tokens,      # 최대 출력 토큰 수
            "temperature": temperature,    # 생성 온도 (0.0 ~ 1.0)
            "system": system_prompt,       # 시스템 프롬프트 (역할, 판독 원칙, RAG 근거)
            "messages": [
                {"role": "user", "content": user_prompt},  # 유저 프롬프트 (환자 정보 + 모달 결과)
            ],
        }

        # Bedrock invoke_model API 호출
        response = self.bedrock.invoke_model(
            modelId=self.model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )
        # 응답 body를 JSON으로 파싱하여 반환
        return json.loads(response["body"].read())

    # ------------------------------------------------------------------
    # 프롬프트 빌더 — 시스템/유저 프롬프트 조립
    # ------------------------------------------------------------------
    def _build_system_prompt(
        self,
        lang: str,
        rag_evidence: list[dict] | None = None,
    ) -> str:
        """
        시스템 프롬프트 조립 — RAG 섹션 포함.

        RAG 유사 케이스가 있으면 시스템 프롬프트에 참고용으로 삽입합니다.
        없으면 "일반적인 의학 지식을 바탕으로 작성" 안내를 삽입합니다.
        """
        if rag_evidence:
            # RAG 유사 케이스가 있는 경우 — 상위 3개만 프롬프트에 삽입
            rag_section = RAG_SECTION_TEMPLATE.format(
                rag_cases="\n\n".join([
                    f"[유사 케이스 {i+1}] (유사도: {r.get('similarity', 'N/A')})\n{r.get('impression', '')}"
                    for i, r in enumerate(rag_evidence[:3])
                ])
            )
        else:
            # RAG 결과 없음 — 플레이스홀더 삽입
            rag_section = (
                RAG_SECTION_PLACEHOLDER if lang == "ko"
                else RAG_SECTION_PLACEHOLDER_EN
            )

        # 언어에 맞는 시스템 프롬프트 템플릿 선택
        template = SYSTEM_PROMPT if lang == "ko" else SYSTEM_PROMPT_EN
        # {rag_section} 플레이스홀더를 실제 RAG 섹션으로 교체
        return template.format(rag_section=rag_section)

    def _build_user_prompt(
        self,
        patient_info: dict,
        modal_reports: list[dict],
        lang: str,
    ) -> str:
        """
        유저 프롬프트 조립 — 환자정보 + 모달별 결과.

        환자 정보와 각 모달의 분석 결과를 텍스트로 포맷팅하여
        유저 프롬프트 템플릿에 삽입합니다.
        """
        # 환자 정보를 텍스트로 포맷팅 (나이, 성별, 주소, 병력)
        patient_info_section = self._format_patient_info(patient_info)
        # 모달별 분석 결과를 텍스트로 포맷팅 (chest, ecg, blood 각각)
        modal_reports_section = self._format_modal_reports(modal_reports)

        # 언어에 맞는 유저 프롬프트 템플릿 선택
        template = (
            USER_PROMPT_TEMPLATE if lang == "ko"
            else USER_PROMPT_TEMPLATE_EN
        )
        return template.format(
            patient_info_section=patient_info_section,
            modal_reports_section=modal_reports_section,
        )

    # ------------------------------------------------------------------
    # 응답 파싱 — Claude 응답에서 JSON 추출
    # ------------------------------------------------------------------
    def _parse_response(self, response: dict) -> dict:
        """
        Bedrock 응답에서 JSON 추출.

        Claude 응답은 자연어 텍스트 안에 JSON이 포함된 형태이므로,
        ```json ... ``` 블록 또는 중괄호 매칭으로 JSON을 추출합니다.
        """
        # Claude 응답 텍스트 추출
        text = response["content"][0]["text"]

        # 방법 1: ```json ... ``` 마크다운 코드 블록에서 추출
        if "```json" in text:
            json_str = text.split("```json")[1].split("```")[0].strip()
        # 방법 2: ``` ... ``` 블록 중 {로 시작하는 것을 찾음
        elif "```" in text and "{" in text:
            parts = text.split("```")
            json_str = None
            for part in parts:
                stripped = part.strip()
                if stripped.startswith("{"):
                    json_str = stripped
                    break
            if json_str is None:
                # 코드 블록에서 못 찾으면 중괄호 매칭으로 시도
                json_str = self._extract_json_braces(text)
        # 방법 3: 코드 블록 없이 직접 중괄호 매칭
        elif "{" in text:
            json_str = self._extract_json_braces(text)
        else:
            raise ValueError("Bedrock 응답에서 JSON을 찾을 수 없습니다")

        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            # JSON 문자열 값 내부의 리터럴 개행을 \n으로 변환 후 재시도
            fixed = self._fix_json_newlines(json_str)
            return json.loads(fixed)

    def _extract_json_braces(self, text: str) -> str:
        """
        중괄호 매칭으로 JSON 추출.

        첫 번째 '{'부터 매칭되는 '}'까지의 문자열을 반환합니다.
        중첩된 중괄호도 올바르게 처리합니다.
        """
        start = text.index("{")
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        # depth가 0이 안 되면 마지막 '}'까지 잘라서 반환
        end = text.rindex("}") + 1
        return text[start:end]

    def _fix_json_newlines(self, text: str) -> str:
        """
        JSON 문자열 값 내부의 리터럴 개행을 \\n으로 변환.

        Claude가 JSON 문자열 안에 실제 줄바꿈을 넣는 경우가 있어,
        이를 이스케이프된 \\n으로 변환하여 유효한 JSON으로 만듭니다.
        """
        result = []
        in_string = False     # 현재 JSON 문자열 값 내부인지 추적
        escape_next = False   # 다음 문자가 이스케이프된 것인지 추적
        for ch in text:
            if escape_next:
                result.append(ch)
                escape_next = False
            elif ch == "\\":
                result.append(ch)
                escape_next = True
            elif ch == '"':
                result.append(ch)
                in_string = not in_string
            elif ch == "\n" and in_string:
                # 문자열 값 내부의 줄바꿈 → 이스케이프 처리
                result.append("\\n")
            elif ch == "\r" and in_string:
                # 캐리지 리턴은 무시
                pass
            else:
                result.append(ch)
        return "".join(result)

    # ------------------------------------------------------------------
    # 포맷팅 헬퍼 — 프롬프트 및 보고서 텍스트 생성
    # ------------------------------------------------------------------
    def _format_patient_info(self, info: dict) -> str:
        """
        환자 정보 포맷팅 — 프롬프트에 삽입할 텍스트 생성.

        Args:
            info: {"age": 65, "sex": "M", "chief_complaint": "흉통", "history": ["고혈압", "당뇨"]}

        Returns:
            "나이: 65세\\n성별: 남성\\n주소: 흉통\\n병력: 고혈압, 당뇨"
        """
        if not info:
            return "정보 없음"
        lines = []
        if info.get("age"):
            lines.append(f"나이: {info['age']}세")
        if info.get("sex"):
            sex_kr = "남성" if info["sex"] == "M" else "여성"
            lines.append(f"성별: {sex_kr}")
        if info.get("chief_complaint"):
            lines.append(f"주소: {info['chief_complaint']}")
        history = info.get("history", [])
        if history:
            lines.append(f"병력: {', '.join(history)}")
        return "\n".join(lines) if lines else "정보 없음"

    def _format_modal_reports(self, reports: list[dict]) -> str:
        """
        모달별 분석 결과 포맷팅 — 프롬프트에 삽입할 텍스트 생성.

        각 모달의 report, findings, summary를 구조화된 텍스트로 변환합니다.
        이 텍스트가 Claude에게 전달되어 종합 소견서의 입력이 됩니다.
        """
        if not reports:
            return "분석 결과 없음"

        sections = []
        for r in reports:
            modal = r.get("modal", "unknown").upper()  # 모달명 대문자로 표시
            lines = [f"=== {modal} ==="]

            # report 텍스트 — 해당 모달의 분석 보고서 원문
            report_text = r.get("report", "")
            if report_text:
                lines.append(report_text)

            # findings — 개별 소견 항목 목록 (질환명, 검출 여부, 신뢰도)
            findings = r.get("findings", [])
            if findings:
                lines.append("\n[주요 소견]")
                for f in findings:
                    name = f.get("name", "")            # 질환명
                    detected = f.get("detected", False)  # 검출 여부
                    confidence = f.get("confidence", 0)  # 모델 신뢰도 (0~1)
                    detail = f.get("detail", "")         # 추가 상세 정보
                    status = "양성" if detected else "음성"
                    line = f"  - {name}: {status} (신뢰도: {confidence:.2f})"
                    if detail:
                        line += f" — {detail}"
                    lines.append(line)

            # summary — 해당 모달의 요약 텍스트
            summary = r.get("summary", "")
            if summary:
                lines.append(f"\n[요약] {summary}")

            sections.append("\n".join(lines))

        return "\n\n".join(sections)

    def _compose_report_text(self, narrative: str, structured: dict) -> str:
        """
        최종 보고서 텍스트 조립.

        자연어 서술형 판독문(narrative)과 구조화된 소견(structured)을 합칩니다.
        """
        parts = []

        # 자연어 서술형 판독문 (Claude가 생성한 종합 소견)
        if narrative:
            parts.append(narrative)

        # 구조화된 소견 — 모달별 요약, 상관관계, 인상, 권고사항 등
        if structured:
            parts.append("\n--- 구조화 소견 ---")
            for key, value in structured.items():
                if value and key not in ("risk_level",):  # risk_level은 별도 표시
                    label = key.upper() if key != "summary_per_modal" else "MODAL SUMMARIES"
                    if isinstance(value, dict):
                        parts.append(f"\n[{label}]")
                        for k, v in value.items():
                            parts.append(f"  {k.upper()}: {v}")
                    else:
                        parts.append(f"[{label}] {value}")

        return "\n".join(parts) if parts else "보고서 생성 실패"

    def _compose_diagnosis_text(
        self,
        impression: str,
        differential: list[dict],
        risk_level: str,
    ) -> str:
        """
        진단 텍스트 조립 — 종합 인상 + 감별 진단 + 위험도.

        URGENT 또는 CRITICAL인 경우 위험도 라벨을 앞에 표시합니다.
        """
        parts = []

        # 위험도가 높으면 라벨 표시 (URGENT, CRITICAL)
        if risk_level in ("URGENT", "CRITICAL"):
            parts.append(f"[{risk_level}]")

        # 종합 인상 (종합적인 진단 요약)
        if impression:
            parts.append(impression)

        # 감별 진단 목록 (가능성이 높은 순서)
        if differential:
            parts.append("\n감별 진단:")
            for i, d in enumerate(differential, 1):
                diag = d.get("diagnosis", "")       # 진단명
                prob = d.get("probability", "")     # 가능성 (high/medium/low)
                parts.append(f"  {i}. {diag} (가능성: {prob})")

        return "\n".join(parts) if parts else "진단 정보 없음"
