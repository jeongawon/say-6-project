"""
Layer 5 RAG Lambda 핸들러.

Actions:
  - GET  → 테스트 HTML 페이지
  - POST → RAG 검색 API

POST actions:
  - scenario: 미리 정의된 Layer 3 시나리오로 RAG 검색 (chf, pneumonia, tension_pneumo, normal)
  - custom:   사용자 커스텀 Layer 3 결과로 RAG 검색
  - list_scenarios: 사용 가능한 시나리오 목록
  - health:   인덱스 상태 확인
"""
import json
import os
import sys
import time

# Lambda에서 패키지 경로 설정
sys.path.insert(0, os.environ.get("LAMBDA_TASK_ROOT", "."))

# ============================================================
# Mock 모드 vs 실제 모드
# ============================================================
USE_MOCK = os.environ.get("USE_MOCK", "false").lower() == "true"

if USE_MOCK:
    # FAISS 인덱스 없이 mock 데이터로 응답
    from layer5_rag.mock_data import MOCK_REPORTS, MOCK_L3_SCENARIOS
    from layer5_rag.query_builder import build_query
    rag_service = None
else:
    from layer5_rag.rag_service import RAGService
    from layer5_rag.config import Config
    from layer5_rag.mock_data import MOCK_L3_SCENARIOS
    from layer5_rag.query_builder import build_query
    config = Config()
    rag_service = RAGService(config)


def mock_search(clinical_logic_result: dict, top_k: int = 3) -> dict:
    """Mock 모드: 키워드 매칭으로 유사 판독문 반환."""
    query = build_query(clinical_logic_result)
    findings = clinical_logic_result.get("findings", {})

    # 간단한 키워드 매칭으로 관련 mock 판독문 선택
    scored = []
    for report in MOCK_REPORTS:
        score = 0.0
        imp_lower = report["impression"].lower()

        for disease, result in findings.items():
            if not result.get("detected") or disease == "No_Finding":
                continue
            name = disease.replace("_", " ").lower()
            if name in imp_lower:
                score += 0.3
            # 세부 매칭
            if result.get("severity") and result["severity"] in imp_lower:
                score += 0.1
            if result.get("location") and result["location"].split()[0].lower() in imp_lower:
                score += 0.1

        # Normal 케이스
        if findings.get("No_Finding", {}).get("detected"):
            if "normal" in imp_lower or "no acute" in imp_lower:
                score += 0.5

        scored.append((score, report))

    scored.sort(key=lambda x: -x[0])
    top = scored[:top_k]

    results = []
    for rank, (score, report) in enumerate(top):
        results.append({
            "rank": rank + 1,
            "similarity": round(min(0.95, 0.7 + score), 4),
            "note_id": report["note_id"],
            "subject_id": report["subject_id"],
            "charttime": report["charttime"],
            "impression": report["impression"],
            "findings": report["findings"],
            "indication": report["indication"],
            "examination": report["examination"],
            "comparison": report["comparison"],
            "source": "Mock Data (MIMIC-CXR style)",
        })

    return {
        "rag_evidence": results,
        "query_used": query,
        "total_results": len(results),
        "includes_findings": True,
        "includes_indication": True,
        "mode": "mock",
    }


def handler(event, context):
    # GET → 테스트 페이지
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    if method == "GET" or (not event.get("body") and not event.get("action")):
        try:
            html_path = os.path.join(
                os.environ.get("LAMBDA_TASK_ROOT", "."), "index.html"
            )
            with open(html_path, "r", encoding="utf-8") as f:
                html = f.read()
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "text/html; charset=utf-8"},
                "body": html,
            }
        except Exception:
            pass

    # POST → API
    try:
        if isinstance(event.get("body"), str):
            body = json.loads(event["body"])
        else:
            body = event

        action = body.get("action", "scenario")
        start_time = time.time()

        if action == "list_scenarios":
            return _response(200, {
                "scenarios": list(MOCK_L3_SCENARIOS.keys()),
                "description": {
                    "chf": "심부전 (Cardiomegaly + Effusion + Edema)",
                    "pneumonia": "폐렴 (Consolidation + Pneumonia)",
                    "tension_pneumo": "긴장성 기흉 (Pneumothorax + Fracture)",
                    "normal": "정상 (No Finding)",
                },
            })

        if action == "health":
            if USE_MOCK:
                info = {"mode": "mock", "mock_reports": len(MOCK_REPORTS)}
            else:
                info = {
                    "mode": "live",
                    "index_vectors": rag_service.index.ntotal,
                    "metadata_count": len(rag_service.metadata),
                }
            return _response(200, info)

        # RAG 검색
        if action == "scenario":
            scenario_id = body.get("scenario", "chf")
            clinical_logic = MOCK_L3_SCENARIOS.get(scenario_id)
            if not clinical_logic:
                return _response(400, {"error": f"Unknown scenario: {scenario_id}"})
        elif action == "custom":
            clinical_logic = body.get("clinical_logic", {})
        else:
            return _response(400, {"error": f"Unknown action: {action}"})

        top_k = body.get("top_k", 3)

        # 검색 실행
        if USE_MOCK:
            result = mock_search(clinical_logic, top_k)
        else:
            result = rag_service.search(clinical_logic, top_k)
            result["mode"] = "live"

        elapsed = time.time() - start_time
        result["processing_time_sec"] = round(elapsed, 4)
        result["scenario"] = body.get("scenario", "custom")

        # Layer 6용 포맷팅된 텍스트도 포함
        if USE_MOCK:
            formatted = _format_for_layer6(result)
        else:
            formatted = rag_service.format_for_layer6(result)
        result["layer6_formatted"] = formatted

        return _response(200, result)

    except Exception as e:
        return _response(500, {"error": str(e)})


def _format_for_layer6(rag_result: dict) -> str:
    """Mock 모드용 Layer 6 포맷팅."""
    if not rag_result.get("rag_evidence"):
        return "[RAG 유사 케이스 없음]"

    lines = [
        "[RAG 유사 케이스 — 참고용]",
        "아래는 유사한 소견을 가진 과거 전문의 판독문입니다. "
        "표현 방식과 소견 구조를 참고하세요.\n",
    ]
    for ev in rag_result["rag_evidence"]:
        lines.append(f"[유사 케이스 {ev['rank']}] (유사도: {ev['similarity']:.2f})")
        if ev.get("indication"):
            lines.append(f"▶ INDICATION: {ev['indication']}")
        if ev.get("findings"):
            lines.append(f"▶ FINDINGS: {ev['findings']}")
        lines.append(f"▶ IMPRESSION: {ev['impression']}")
        lines.append("")
    return "\n".join(lines)


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, ensure_ascii=False),
    }
