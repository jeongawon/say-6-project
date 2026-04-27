# ──────────────────────────────────────────────
# 실행: streamlit run app.py
# 설치: pip install streamlit chromadb boto3
# ──────────────────────────────────────────────

import os
import sys

sys.path.insert(0, os.path.abspath("."))

import streamlit as st

from scripts.step6_rag_orchestrator import (
    FALLBACK_RESPONSE,
    Generator,
    Retriever,
    build_user_prompt,
)

# ──────────────────────────────────────────────
# 캐싱
# ──────────────────────────────────────────────
@st.cache_resource
def get_retriever():
    return Retriever()


@st.cache_resource
def get_generator():
    return Generator()


# ──────────────────────────────────────────────
# 페이지 설정
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="AI 의료 어드바이저",
    page_icon="🏥",
    layout="wide",
)

# ──────────────────────────────────────────────
# 세션 초기화
# ──────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": (
                "안녕하세요 👋 **AI 의료 어드바이저**입니다.\n\n"
                "환자의 검사 결과(CXR, ECG, 혈액검사 등)를 **영문으로** 입력해 주시면, "
                "과거 유사 사례를 검색하여 종합 소견을 작성해 드립니다.\n\n"
                "예시: *CXR: Consolidation in the right lower lobe. Blood: WBC 18,500. "
                "ECG: Sinus Tachycardia 110 bpm.*"
            ),
            "sources": None,
        }
    ]

# ──────────────────────────────────────────────
# 사이드바
# ──────────────────────────────────────────────
with st.sidebar:
    st.header("🏥 AI 의료 어드바이저")
    st.caption("과거 사례 기반 종합 소견 서비스")

    st.divider()

    st.markdown(
        "MIMIC-IV 데이터 기반 **49,743건**의 퇴원 요약지 및 "
        "영상의학 보고서에서 유사 환자 사례를 검색하고, "
        "AI가 종합 소견을 작성합니다."
    )

    st.divider()

    st.markdown("**기술 스택**")
    st.markdown(
        "- 🔍 ChromaDB + Titan Embed v2 (512d)\n"
        "- 🤖 Claude 3 Haiku (Bedrock)\n"
        "- 📊 10,000 입원 건"
    )

    st.divider()

    if st.button("🔄 New Consultation", use_container_width=True):
        st.session_state.messages = [st.session_state.messages[0]]  # 환영 메시지만 유지
        st.rerun()

    st.divider()
    st.caption("⚠️ AI can make mistakes. Verify all medical information before clinical application.")


# ──────────────────────────────────────────────
# 출처 렌더링 함수
# ──────────────────────────────────────────────
def render_sources(sources: list[dict]):
    """검색 결과 Top-3를 카드 + 접이식으로 표시"""
    with st.expander("📂 참고한 과거 유사 환자 기록 보기"):
        for i, r in enumerate(sources):
            meta = r["metadata"]
            chunk_type = meta.get("chunk_type", "unknown")
            hadm_id = meta.get("hadm_id", "?")
            sim = r["similarity"]

            st.markdown(
                f"**[사례 {i+1}]** &nbsp; "
                f"`유사도: {sim:.4f}` &nbsp; "
                f"`유형: {chunk_type}` &nbsp; "
                f"`입원번호: {hadm_id}`"
            )

            if chunk_type == "radiology":
                cols = st.columns(4)
                cols[0].metric("Exam Type", meta.get("modality", "-"))
                cols[1].metric("Clinical Status", meta.get("clinical_status", "-"))
                cols[2].metric("Event Seq", meta.get("event_sequence", "-"))
                cols[3].metric("Total Exams", meta.get("total_exams", "-"))

            st.text(r["document"][:400])

            if i < len(sources) - 1:
                st.divider()


# ──────────────────────────────────────────────
# 대화 이력 렌더링
# ──────────────────────────────────────────────
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

        # 출처 표기 (assistant 메시지에 sources가 있을 때)
        if msg.get("sources"):
            _render_sources(msg["sources"]) if callable(globals().get("_render_sources")) else None


# ──────────────────────────────────────────────
# 출처 렌더링 함수
# ──────────────────────────────────────────────
def render_sources(sources: list[dict]):
    """검색 결과 Top-3를 카드 + 접이식으로 표시"""
    with st.expander("📂 참고한 과거 유사 환자 기록 보기"):
        for i, r in enumerate(sources):
            meta = r["metadata"]
            chunk_type = meta.get("chunk_type", "unknown")
            hadm_id = meta.get("hadm_id", "?")
            sim = r["similarity"]

            # 카드 헤더
            st.markdown(
                f"**[사례 {i+1}]** &nbsp; "
                f"`유사도: {sim:.4f}` &nbsp; "
                f"`유형: {chunk_type}` &nbsp; "
                f"`입원번호: {hadm_id}`"
            )

            # radiology는 메타데이터 카드로 표시
            if chunk_type == "radiology":
                cols = st.columns(4)
                cols[0].metric("Exam Type", meta.get("modality", "-"))
                cols[1].metric("Clinical Status", meta.get("clinical_status", "-"))
                cols[2].metric("Event Seq", meta.get("event_sequence", "-"))
                cols[3].metric("Total Exams", meta.get("total_exams", "-"))

            # 문서 원문 미리보기
            st.text(r["document"][:400])

            if i < len(sources) - 1:
                st.divider()


# ──────────────────────────────────────────────
# 대화 이력 다시 렌더링 (sources 포함)
# ──────────────────────────────────────────────
# 위의 이력 렌더링에서 sources를 처리하지 못했으므로 여기서 보완
# (Streamlit의 실행 순서 특성상, 함수 정의 후 다시 렌더링)
for msg in st.session_state.messages:
    if msg.get("sources") and msg["role"] == "assistant":
        # 이미 위에서 content는 렌더링됨 — sources만 추가
        pass  # 아래 chat_input 처리에서 실시간으로 렌더링


# ──────────────────────────────────────────────
# 사용자 입력 처리
# ──────────────────────────────────────────────
user_input = st.chat_input("환자 검사 결과를 영문으로 입력하세요...")

if user_input:
    # 사용자 메시지 표시 & 저장
    st.session_state.messages.append({"role": "user", "content": user_input, "sources": None})
    with st.chat_message("user"):
        st.markdown(user_input)

    # Assistant 응답 생성
    with st.chat_message("assistant"):
        try:
            retriever = get_retriever()
            generator = get_generator()
        except Exception as e:
            st.error(f"시스템 초기화 실패: {e}")
            st.stop()

        with st.status("분석 진행 중...", expanded=True) as status:
            # 1/3: 검색
            st.write("1/3: 입력된 환자 데이터 임베딩 변환 중...")
            try:
                search_result = retriever.search(user_input)
            except Exception as e:
                st.error(f"검색 실패: {e}")
                st.stop()

            if search_result["fallback"]:
                status.update(label="검색 완료", state="complete")
                st.warning(FALLBACK_RESPONSE)
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": FALLBACK_RESPONSE,
                    "sources": None,
                })
                st.stop()

            results = search_result["results"]
            st.write(f"2/3: ChromaDB에서 유사 과거 사례 {len(results)}건 검색 완료")

            # 3/3: 생성
            st.write("3/3: Claude 3 Haiku를 통한 최종 종합 소견 작성 중...")
            user_prompt = build_user_prompt(user_input, results)
            answer = generator.generate(user_prompt)

            status.update(label="분석 완료 ✅", state="complete")

        # 소견 출력
        st.markdown(answer)

        # 출처 표기
        render_sources(results)

        # 세션에 저장
        st.session_state.messages.append({
            "role": "assistant",
            "content": answer,
            "sources": results,
        })
