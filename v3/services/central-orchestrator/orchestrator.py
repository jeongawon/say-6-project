"""
central-orchestrator — LLM 기반 순차 검사 루프 엔진 (CORE LOGIC).

Bedrock LLM이 환자 상태와 누적 결과를 보고 다음 검사를 결정.
DONE 또는 max_iterations에 도달하면 종합 소견서 생성.

이 파일이 오케스트레이터의 핵심 로직입니다.
전체 흐름: 세션 생성 → [Bedrock 질의 → 모달 호출 → 결과 누적] × N → 소견서 생성 → 세션 완료
"""

import logging
import time
from typing import Any

import asyncpg
import redis.asyncio as aioredis

import modal_client              # 모달 서비스 HTTP 클라이언트 (chest/ecg/blood/report)
import session_manager           # DB + Redis 세션 관리
from config import settings      # 환경 변수 설정
from prompts import ask_bedrock_next_exam  # Bedrock LLM 검사 결정 호출

logger = logging.getLogger("orchestrator.engine")


# ╔══════════════════════════════════════════════════════════╗
# ║  TODO: [팀원D] 순차 루프 수정 포인트                      ║
# ║  이 함수가 오케스트레이터의 메인 루프입니다.                ║
# ║  max_iterations, 종료 조건, 결과 누적 방식 등을            ║
# ║  프로젝트 요구사항에 맞게 조정하세요.                      ║
# ╚══════════════════════════════════════════════════════════╝
async def run_sequential_exam(
    patient_id: str,
    patient_info: dict[str, Any],
    data: dict[str, Any],
    db_pool: asyncpg.Pool,
    redis_client: aioredis.Redis,
) -> dict[str, Any]:
    """
    LLM 기반 순차 검사 루프 — 오케스트레이터의 핵심 함수.

    처리 흐름:
    1. 세션 생성 (DB + Redis)
    2. 반복: Bedrock에 다음 검사 질의 → 모달 서비스 호출 → 결과 누적
    3. report-svc를 통해 종합 소견서 생성
    4. 세션 완료 처리

    Args:
        patient_id: 환자 고유 식별자
        patient_info: {"age": int, "sex": str, "chief_complaint": str, "history": [...]}
        data: 모달별 입력 데이터 (키: 모달명, 값: 해당 모달 데이터)
        db_pool: asyncpg 커넥션 풀
        redis_client: Redis 비동기 클라이언트

    Returns:
        ExamResponse 호환 dict (전체 검사 결과 포함)
    """
    start_time = time.time()

    # ──────────────────────────────────────────────────────────────────
    # [단계 1] 세션 생성: DB에 exam_sessions 레코드 삽입 + Redis 캐시
    # ──────────────────────────────────────────────────────────────────
    session = await session_manager.create_session(patient_id, patient_info, db_pool, redis_client)
    logger.info("Starting sequential exam: session=%d, patient=%s", session.id, patient_id)

    accumulated_results: list[dict[str, Any]] = []    # 지금까지 수행한 모달 검사 결과 누적
    exams_performed: list[str] = []                    # 수행 완료된 검사 이름 목록
    exam_decisions: list[dict[str, str]] = []          # Bedrock의 검사 결정 이력

    try:
        # ──────────────────────────────────────────────────────────────
        # [단계 2] 순차 검사 루프
        # Bedrock이 DONE을 반환하거나 max_iterations에 도달할 때까지 반복
        # ──────────────────────────────────────────────────────────────
        iteration = 0
        while iteration < settings.max_exam_iterations:
            iteration += 1
            logger.info("Exam loop iteration %d/%d", iteration, settings.max_exam_iterations)

            # ── [단계 2a] Bedrock에 다음 검사 질의 ──
            # "환자 정보 + 지금까지 결과"를 보내고, 다음에 할 검사를 결정받음
            decision = await ask_bedrock_next_exam(patient_info, accumulated_results)
            next_modal = decision.get("next_exam", "DONE")    # "chest" | "ecg" | "blood" | "DONE"
            reasoning = decision.get("reasoning", "")          # 결정 사유 (임상적 근거)
            exam_decisions.append(decision)

            logger.info(
                "Bedrock decision (iter %d): next_exam=%s, reasoning=%s",
                iteration, next_modal, reasoning,
            )

            # ── [단계 2b] 종료 조건 확인 ──
            # Bedrock이 "충분한 정보 확보"라고 판단하면 DONE 반환
            if next_modal == "DONE":
                logger.info("Bedrock decided: examination complete.")
                break

            # ── [단계 2c] 중복 검사 방지 (안전 장치) ──
            # 이미 수행한 검사는 건너뜀 (LLM이 실수로 중복 지시할 경우 대비)
            if next_modal in exams_performed:
                logger.warning("Exam '%s' already performed, skipping.", next_modal)
                continue

            # ── [단계 2d] 모달 서비스 호출 ──
            # chest-svc, ecg-svc, blood-svc 중 해당 서비스의 /predict 엔드포인트 호출
            result = await modal_client.predict(
                modal=next_modal,
                patient_id=patient_id,
                patient_info=patient_info,
                data=data,
                accumulated_results=accumulated_results,
            )

            # ── [단계 2e] 결과 누적 ──
            # 다음 Bedrock 질의 시 이전 검사 결과를 포함하여 전달
            accumulated_results.append(result)
            exams_performed.append(next_modal)

            # ── [단계 2f] DB + Redis에 결과 저장 ──
            # modal_results 테이블에 삽입 + Redis 세션 캐시 업데이트
            await session_manager.save_modal_result(session.id, result, db_pool, redis_client)

            # ── [단계 2g] 에러 발생 시 로깅 (루프는 계속 진행) ──
            # 하나의 모달이 실패해도 나머지 검사는 수행할 수 있도록 함
            if result.get("status") == "error":
                logger.warning("Modal %s returned error: %s", next_modal, result.get("summary", ""))

        # ──────────────────────────────────────────────────────────────
        # [단계 3] 종합 소견서 생성
        # 모든 모달 결과를 report-svc에 전달하여 최종 소견서 생성
        # ──────────────────────────────────────────────────────────────
        logger.info("Generating comprehensive report for session %d", session.id)
        report_response = await modal_client.call_report_service(
            patient_id=patient_id,
            patient_info=patient_info,
            accumulated_results=accumulated_results,
        )

        # ──────────────────────────────────────────────────────────────
        # [단계 4] 세션 완료 처리
        # exam_sessions 상태를 'completed'로 업데이트 + 종합 소견서 DB 저장
        # ──────────────────────────────────────────────────────────────
        await session_manager.complete_session(session.id, report_response, db_pool)

        elapsed_ms = int((time.time() - start_time) * 1000)

        # 성공 응답 반환
        return {
            "status": "success",
            "patient_id": patient_id,
            "session_id": session.id,
            "exams_performed": exams_performed,          # 수행된 검사 목록
            "modal_reports": accumulated_results,        # 각 모달 검사 상세 결과
            "exam_decisions": exam_decisions,             # Bedrock 결정 이력
            "final_report": report_response.get("report", ""),    # 종합 소견서
            "diagnosis": report_response.get("diagnosis", ""),    # 최종 진단
            "metadata": {
                "total_time_ms": elapsed_ms,             # 전체 소요 시간 (밀리초)
                "exams_count": len(exams_performed),      # 수행된 검사 수
                "iterations": iteration,                  # 루프 반복 횟수
            },
        }

    except Exception as e:
        # ──────────────────────────────────────────────────────────────
        # [예외 처리] 세션 실패 처리
        # exam_sessions 상태를 'failed'로 업데이트하고 에러 정보 반환
        # ──────────────────────────────────────────────────────────────
        logger.exception("Sequential exam failed for session %d: %s", session.id, e)
        await session_manager.fail_session(session.id, str(e), db_pool)

        elapsed_ms = int((time.time() - start_time) * 1000)

        return {
            "status": "error",
            "patient_id": patient_id,
            "session_id": session.id,
            "exams_performed": exams_performed,
            "modal_reports": accumulated_results,
            "exam_decisions": exam_decisions,
            "final_report": "",
            "diagnosis": "",
            "error": str(e),
            "metadata": {
                "total_time_ms": elapsed_ms,
                "exams_count": len(exams_performed),
            },
        }
