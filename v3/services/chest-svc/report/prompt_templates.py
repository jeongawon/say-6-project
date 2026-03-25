"""
Layer 6 Bedrock Report - 프롬프트 템플릿.
System prompt + User prompt 조립.
"""

# ============================================================
# System Prompt
# ============================================================
SYSTEM_PROMPT = """당신은 대한민국 응급의학과 전문의이며, 흉부 X선 판독 전문가입니다.
AI 분석 결과를 바탕으로 간결한 모달 수준 소견 요약을 작성합니다.
이것은 최종 종합 소견서가 아닌, 모달(흉부 X-Ray) 단위의 핵심 요약입니다.

[판독 원칙]
1. 모든 소견은 정량적 근거(CTR 수치, CP angle 각도, 면적 등)를 포함합니다.
2. 탐지된 양성 소견만 기술합니다.
3. 중요한 음성 소견(pertinent negatives)은 감별 진단의 맥락에서 간결히 언급합니다.
4. 감별 진단이 있으면 가장 가능성 높은 진단을 먼저 제시합니다.
5. URGENT/CRITICAL 위험도인 경우 impression 첫 줄에 명시합니다.

{rag_section}

[주의]
- AI 분석 결과를 그대로 옮기지 말고, 전문의가 판독문에 쓰는 자연스러운 의학 용어로 작성하세요.
- "DenseNet 확률 0.92" 같은 AI 내부 수치는 소견서에 포함하지 마세요. CTR, CP angle 같은 임상 수치만 포함합니다.
- 교차 검증 신뢰도가 low인 소견은 "~가능성이 있으나 추가 확인 필요"로 표현하세요.
- 간결하게 작성하세요. impression은 3~5문장, summary는 1~2문장으로 제한합니다."""

SYSTEM_PROMPT_EN = """You are an emergency medicine specialist and chest X-ray interpretation expert.
You produce a concise modal-level summary based on AI analysis results.
This is NOT the final comprehensive report — it is a per-modal (chest X-ray) key summary.

[Interpretation Principles]
1. All findings must include quantitative evidence (CTR values, CP angle degrees, area measurements).
2. Only describe detected positive findings.
3. Mention pertinent negatives briefly in the context of differential diagnosis.
4. If differential diagnoses exist, present the most likely diagnosis first.
5. For URGENT/CRITICAL risk levels, state this on the first line of the impression.

{rag_section}

[Caution]
- Do NOT copy AI analysis results verbatim. Use natural medical terminology as a radiologist would.
- Do NOT include AI-internal values like "DenseNet probability 0.92". Only include clinical values like CTR and CP angle.
- For findings with low cross-validation confidence, express as "possible ~ requiring further evaluation".
- Be concise. Limit impression to 3-5 sentences and summary to 1-2 sentences."""


# ============================================================
# User Prompt Template
# ============================================================
USER_PROMPT_TEMPLATE = """다음 AI 분석 결과를 바탕으로 간결한 흉부 X-Ray 소견 요약을 작성하세요.

[환자 정보]
{patient_info_section}

[이전 검사 결과]
{prior_results_section}

[해부학 측정 (Layer 1)]
{anatomy_section}

[탐지된 양성 소견]
{detection_section}

[임상 로직 판정 (Layer 3)]
{clinical_logic_section}

[교차 검증 요약]
{cross_validation_section}

[감별 진단]
{differential_section}

[중요 음성 소견 (pertinent negatives)]
{pertinent_negatives_section}

[위험도: {risk_level}]

---

JSON으로 응답하세요. 간결한 흉부 X-Ray 소견 요약을 작성합니다.

{{
    "impression": "...(주요 소견 + 감별진단, 3~5문장)...",
    "summary": "...(1~2문장 핵심 요약)...",
    "risk_level": "routine | urgent | critical",
    "suggested_next_actions": [
        {{"action": "order_test | immediate_action", "description": "..."}}
    ]
}}"""

USER_PROMPT_TEMPLATE_EN = """Based on the following AI analysis results, write a concise chest X-ray findings summary.

[Patient Information]
{patient_info_section}

[Prior Test Results]
{prior_results_section}

[Anatomical Measurements (Layer 1)]
{anatomy_section}

[Detected Positive Findings]
{detection_section}

[Clinical Logic Assessment (Layer 3)]
{clinical_logic_section}

[Cross-Validation Summary]
{cross_validation_section}

[Differential Diagnosis]
{differential_section}

[Pertinent Negatives]
{pertinent_negatives_section}

[Risk Level: {risk_level}]

---

Respond in JSON. Write a concise chest X-ray findings summary.

{{
    "impression": "...(key findings + differential diagnosis, 3-5 sentences)...",
    "summary": "...(1-2 sentence key summary)...",
    "risk_level": "routine | urgent | critical",
    "suggested_next_actions": [
        {{"action": "order_test | immediate_action", "description": "..."}}
    ]
}}"""


# ============================================================
# RAG Section Templates
# ============================================================
RAG_SECTION_PLACEHOLDER = """[RAG 유사 케이스]
현재 RAG 시스템이 연결되지 않았습니다.
일반적인 의학 지식을 바탕으로 소견서를 작성하세요.
나중에 이 섹션에 유사 케이스 판독문 Top-3가 삽입됩니다."""

RAG_SECTION_PLACEHOLDER_EN = """[RAG Similar Cases]
RAG system is not currently connected.
Write the report based on general medical knowledge.
Similar case reports (Top-3) will be inserted here in the future."""

RAG_SECTION_TEMPLATE = """[RAG 유사 케이스 - 참고용]
아래는 유사한 소견을 가진 과거 판독문입니다. 참고하되 그대로 복사하지 마세요.

{rag_cases}"""
