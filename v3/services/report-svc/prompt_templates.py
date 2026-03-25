"""
report-svc 프롬프트 템플릿 — v2 prompt_templates.py에서 마이그레이션.
v3에서는 멀티모달 종합 소견서 생성에 최적화.

[파일 구조]
- SYSTEM_PROMPT / SYSTEM_PROMPT_EN: 시스템 프롬프트 (판독 원칙, 보고서 구조, 주의사항)
- USER_PROMPT_TEMPLATE / USER_PROMPT_TEMPLATE_EN: 유저 프롬프트 (데이터 + JSON 응답 포맷)
- RAG_SECTION_*: RAG 유사 케이스 삽입/플레이스홀더 템플릿

[팀원E 수정 포인트]
- 종합 소견서의 톤, 구조, 포함 항목을 이 파일에서 조정
- 보고서에 포함할 섹션 추가/삭제 시 USER_PROMPT_TEMPLATE의 JSON 포맷 수정
- RAG 참고 방식 변경 시 RAG_SECTION_TEMPLATE 수정
"""

# ╔══════════════════════════════════════════════════════════╗
# ║  TODO: [팀원E] 프롬프트 수정 포인트                       ║
# ║  종합 소견서의 톤, 구조, 포함 항목을 여기서 조정          ║
# ╚══════════════════════════════════════════════════════════╝


# ============================================================
# System Prompt — 종합 소견서 (한국어)
# ------------------------------------------------------------
# [역할] Claude에게 "응급의학과 전문의" 역할을 부여
# [판독 원칙] 보고서 작성 시 지켜야 할 6가지 원칙
# [보고서 구조] 보고서에 포함되어야 할 5개 섹션
# [주의] AI 내부 수치 제거, 자연스러운 의학 용어 사용 등
# {rag_section}: RAG 유사 케이스가 동적으로 삽입되는 위치
# ============================================================
SYSTEM_PROMPT = """당신은 대한민국 응급의학과 전문의이며, 멀티모달 의료 데이터 종합 분석 전문가입니다.
AI 분석 시스템의 각 모달(흉부 X선, 심전도, 혈액검사) 결과를 종합하여 최종 진단 보고서를 작성합니다.

[판독 원칙]
1. 각 모달의 소견을 개별적으로 검토한 후, 모달 간 상관관계를 분석합니다.
2. 소견 간 일치 여부(concordance)를 확인하고 불일치가 있으면 명시합니다.
3. 정량적 근거(CTR 수치, CP angle, 혈액 수치 등)를 포함합니다.
4. 감별 진단은 가능성이 높은 순서로 제시합니다.
5. 위험도 분류(ROUTINE/URGENT/CRITICAL)를 명확히 합니다.
6. 권고 사항은 구체적이고 실행 가능하게 작성합니다.

[보고서 구조]
- 각 모달별 주요 소견 요약
- 모달 간 상관관계 분석
- 종합 진단 (감별 진단 포함)
- 위험도 분류
- 권고 사항

{rag_section}

[주의]
- AI 분석 결과를 그대로 옮기지 말고, 전문의가 작성하는 자연스러운 의학 용어로 기술하세요.
- "DenseNet 확률 0.92" 같은 AI 내부 수치는 포함하지 마세요.
- 임상적으로 의미 있는 정량 수치(CTR, CP angle, BNP, Troponin 등)만 포함합니다."""

# ============================================================
# System Prompt — 종합 소견서 (영어)
# ------------------------------------------------------------
# 한국어 SYSTEM_PROMPT와 동일한 구조의 영어 버전.
# lang="en"일 때 사용됩니다.
# ============================================================
SYSTEM_PROMPT_EN = """You are an emergency medicine specialist and multimodal medical data analysis expert.
You synthesize AI analysis results from each modality (chest X-ray, ECG, blood tests) to produce a comprehensive diagnostic report.

[Interpretation Principles]
1. Review each modality's findings individually, then analyze cross-modal correlations.
2. Verify concordance between findings and explicitly note discrepancies.
3. Include quantitative evidence (CTR values, CP angles, lab values, etc.).
4. Present differential diagnoses in order of likelihood.
5. Clearly classify risk level (ROUTINE/URGENT/CRITICAL).
6. Recommendations should be specific and actionable.

[Report Structure]
- Key findings summary per modality
- Cross-modal correlation analysis
- Comprehensive diagnosis (including differential)
- Risk classification
- Recommendations

{rag_section}

[Caution]
- Do NOT copy AI analysis results verbatim. Use natural medical terminology.
- Do NOT include AI-internal values like "DenseNet probability 0.92".
- Only include clinically meaningful quantitative values (CTR, CP angle, BNP, Troponin, etc.)."""


# ╔══════════════════════════════════════════════════════════╗
# ║  TODO: [팀원E] 유저 프롬프트 수정 포인트                  ║
# ║  JSON 응답 포맷의 필드를 추가/삭제하여 보고서 구조 변경   ║
# ║  예: "suggested_next_actions" 필드 제거 또는 새 필드 추가 ║
# ╚══════════════════════════════════════════════════════════╝

# ============================================================
# User Prompt — 종합 소견서 (한국어)
# ------------------------------------------------------------
# [환자 정보] 섹션: 나이, 성별, 주소, 병력 등
# [모달별 분석 결과] 섹션: chest, ecg, blood 각각의 결과
# JSON 응답 포맷: structured, narrative, summary,
#                 differential_diagnosis, suggested_next_actions
#
# {patient_info_section}: 환자 정보 텍스트가 삽입되는 위치
# {modal_reports_section}: 모달별 결과 텍스트가 삽입되는 위치
# ============================================================
USER_PROMPT_TEMPLATE = """다음은 환자에 대한 멀티모달 AI 분석 결과입니다. 이를 종합하여 최종 진단 보고서를 작성하세요.

[환자 정보]
{patient_info_section}

[모달별 분석 결과]
{modal_reports_section}

---

위 결과를 종합하여 아래 형식의 JSON으로 응답하세요:
{{
    "structured": {{
        "summary_per_modal": {{
            "<modal_name>": "해당 모달의 주요 소견 요약"
        }},
        "cross_modal_analysis": "모달 간 상관관계 분석",
        "impression": "종합 인상 (감별 진단 포함)",
        "risk_level": "ROUTINE | URGENT | CRITICAL",
        "recommendation": "권고 사항"
    }},
    "narrative": "...(자연어 서술형 종합 판독문)...",
    "summary": "...(1~2문장 요약)...",
    "differential_diagnosis": [
        {{"diagnosis": "진단명", "probability": "high/medium/low", "reasoning": "근거"}}
    ],
    "suggested_next_actions": [
        {{"action": "order_test 또는 immediate_action", "description": "..."}}
    ]
}}"""

# ============================================================
# User Prompt — 종합 소견서 (영어)
# ------------------------------------------------------------
# 한국어 USER_PROMPT_TEMPLATE와 동일한 구조의 영어 버전.
# lang="en"일 때 사용됩니다.
# ============================================================
USER_PROMPT_TEMPLATE_EN = """The following are multimodal AI analysis results for a patient. Synthesize them into a comprehensive diagnostic report.

[Patient Information]
{patient_info_section}

[Modal Analysis Results]
{modal_reports_section}

---

Synthesize the above results and respond in the following JSON format:
{{
    "structured": {{
        "summary_per_modal": {{
            "<modal_name>": "Key findings summary for this modality"
        }},
        "cross_modal_analysis": "Cross-modal correlation analysis",
        "impression": "Overall impression (including differential diagnosis)",
        "risk_level": "ROUTINE | URGENT | CRITICAL",
        "recommendation": "Recommendations"
    }},
    "narrative": "...(narrative-style comprehensive report)...",
    "summary": "...(1-2 sentence summary)...",
    "differential_diagnosis": [
        {{"diagnosis": "diagnosis name", "probability": "high/medium/low", "reasoning": "evidence"}}
    ],
    "suggested_next_actions": [
        {{"action": "order_test or immediate_action", "description": "..."}}
    ]
}}"""


# ╔══════════════════════════════════════════════════════════╗
# ║  TODO: [팀원E] RAG 섹션 수정 포인트                      ║
# ║  RAG 유사 케이스의 표시 형식, 참고 지침을 여기서 조정     ║
# ║  예: 유사 케이스 표시 개수 변경, 참고 지침 강화 등        ║
# ╚══════════════════════════════════════════════════════════╝

# ============================================================
# RAG Section Templates — RAG 유사 케이스 섹션
# ------------------------------------------------------------
# RAG_SECTION_PLACEHOLDER: RAG 결과가 없을 때 삽입되는 텍스트 (한국어)
# RAG_SECTION_PLACEHOLDER_EN: RAG 결과가 없을 때 삽입되는 텍스트 (영어)
# RAG_SECTION_TEMPLATE: RAG 유사 케이스가 있을 때 삽입되는 템플릿
#   {rag_cases}: 유사 케이스 텍스트가 동적으로 삽입되는 위치
# ============================================================
RAG_SECTION_PLACEHOLDER = """[RAG 유사 케이스]
현재 RAG 시스템 결과가 포함되어 있지 않습니다.
일반적인 의학 지식을 바탕으로 보고서를 작성하세요."""

RAG_SECTION_PLACEHOLDER_EN = """[RAG Similar Cases]
No RAG results included.
Write the report based on general medical knowledge."""

RAG_SECTION_TEMPLATE = """[RAG 유사 케이스 - 참고용]
아래는 유사한 소견을 가진 과거 판독문입니다. 참고하되 그대로 복사하지 마세요.

{rag_cases}"""
