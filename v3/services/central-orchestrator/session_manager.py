"""
central-orchestrator — Session state 관리.

PostgreSQL (persistent) + Redis (cache/real-time) 이중 저장.
exam_sessions, modal_results, comprehensive_reports 테이블 사용.

설계 원칙:
- PostgreSQL: 영구 저장 (검사 이력, 소견서 등)
- Redis: 캐시 및 실시간 상태 조회 (검사 진행 중 빠른 접근)
- 두 저장소에 동시 기록하여 일관성 유지
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

import asyncpg
import redis.asyncio as aioredis

logger = logging.getLogger("orchestrator.session")

# Redis 키의 유효 시간 (초) — 1시간 후 자동 만료
SESSION_TTL = 3600  # 1 hour


@dataclass
class Session:
    """검사 세션 데이터 클래스. DB 레코드의 인메모리 표현."""
    id: int                 # 세션 ID (DB 자동 생성)
    patient_id: str         # 환자 고유 식별자
    status: str             # 상태: in_progress / completed / failed
    patient_info: dict      # 환자 기본 정보 스냅샷


# ── 세션 CRUD 함수 ──────────────────────────────────────────────────

async def ensure_patient_exists(
    patient_id: str,
    patient_info: dict[str, Any],
    pool: asyncpg.Pool,
) -> None:
    """
    환자 정보 UPSERT: 존재하지 않으면 삽입, 존재하면 업데이트.

    patients 테이블에 환자 기본 정보를 저장합니다.
    exam_sessions 테이블이 patients를 FK로 참조하므로, 세션 생성 전 반드시 호출해야 합니다.
    """
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO patients (patient_id, age, sex, chief_complaint, history)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            ON CONFLICT (patient_id) DO UPDATE
                SET age = EXCLUDED.age,
                    sex = EXCLUDED.sex,
                    chief_complaint = EXCLUDED.chief_complaint,
                    history = EXCLUDED.history
            """,
            patient_id,
            patient_info.get("age", 0),
            patient_info.get("sex", ""),
            patient_info.get("chief_complaint", ""),
            json.dumps(patient_info.get("history", [])),
        )


async def create_session(
    patient_id: str,
    patient_info: dict[str, Any],
    pool: asyncpg.Pool,
    redis_client: aioredis.Redis,
) -> Session:
    """
    새 검사 세션 생성: DB에 레코드 삽입 + Redis에 캐시.

    1. 환자 정보 UPSERT (FK 참조를 위해)
    2. exam_sessions 테이블에 'in_progress' 상태로 삽입
    3. Redis에 세션 상태 캐시 (빠른 조회용)
    """
    # 환자 레코드 확인/생성 (FK 참조를 위해 필수)
    await ensure_patient_exists(patient_id, patient_info, pool)

    # DB에 세션 레코드 삽입
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO exam_sessions (patient_id, status, patient_info)
            VALUES ($1, 'in_progress', $2::jsonb)
            RETURNING id, patient_id, status
            """,
            patient_id,
            json.dumps(patient_info),
        )

    session = Session(
        id=row["id"],
        patient_id=row["patient_id"],
        status=row["status"],
        patient_info=patient_info,
    )

    # Redis에 세션 상태 캐시 (검사 진행 중 빠른 조회용)
    # 키 형식: "session:{id}", TTL: 1시간
    redis_key = f"session:{session.id}"
    await redis_client.setex(
        redis_key,
        SESSION_TTL,
        json.dumps({
            "id": session.id,
            "patient_id": session.patient_id,
            "status": session.status,
            "patient_info": patient_info,
            "modal_results": [],    # 검사 결과가 누적될 리스트
        }),
    )

    logger.info("Session %d created for patient %s", session.id, patient_id)
    return session


async def save_modal_result(
    session_id: int,
    result: dict[str, Any],
    pool: asyncpg.Pool,
    redis_client: aioredis.Redis,
) -> None:
    """
    모달 검사 결과 저장: DB 영구 저장 + Redis 캐시 업데이트.

    orchestrator.py의 순차 루프에서 각 모달 호출 후 이 함수를 통해 결과를 저장합니다.
    """
    modal = result.get("modal", "unknown")       # 검사 종류 (chest/ecg/blood)
    findings = result.get("findings", [])         # 검출 결과 리스트
    summary = result.get("summary", "")           # 요약 소견
    report = result.get("report", "")             # 상세 리포트
    metadata = result.get("metadata", {})         # 추가 메타데이터

    # PostgreSQL에 모달 결과 삽입
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO modal_results (session_id, modal, findings, summary, report, metadata)
            VALUES ($1, $2, $3::jsonb, $4, $5, $6::jsonb)
            """,
            session_id,
            modal,
            json.dumps(findings),
            summary,
            report,
            json.dumps(metadata),
        )

    # Redis 캐시 업데이트: 세션의 modal_results 리스트에 결과 추가
    redis_key = f"session:{session_id}"
    cached = await redis_client.get(redis_key)
    if cached:
        session_data = json.loads(cached)
        session_data["modal_results"].append(result)
        await redis_client.setex(redis_key, SESSION_TTL, json.dumps(session_data))

    logger.info("Modal result saved: session=%d, modal=%s", session_id, modal)


async def complete_session(
    session_id: int,
    final_report: dict[str, Any],
    pool: asyncpg.Pool,
) -> None:
    """
    세션 완료 처리: 상태를 'completed'로 변경 + 종합 소견서 저장.

    트랜잭션으로 묶어 상태 업데이트와 소견서 삽입의 원자성을 보장합니다.
    """
    report_text = final_report.get("report", "")
    diagnosis = final_report.get("diagnosis", "")

    async with pool.acquire() as conn:
        # 트랜잭션: 세션 상태 업데이트 + 소견서 삽입을 원자적으로 수행
        async with conn.transaction():
            # 세션 상태를 'completed'로 변경
            await conn.execute(
                """
                UPDATE exam_sessions
                SET status = 'completed', completed_at = now()
                WHERE id = $1
                """,
                session_id,
            )

            # 종합 소견서를 comprehensive_reports 테이블에 삽입
            await conn.execute(
                """
                INSERT INTO comprehensive_reports (session_id, report, diagnosis)
                VALUES ($1, $2, $3)
                """,
                session_id,
                report_text,
                diagnosis,
            )

    logger.info("Session %d completed.", session_id)


async def fail_session(
    session_id: int,
    error_msg: str,
    pool: asyncpg.Pool,
) -> None:
    """세션 실패 처리: 상태를 'failed'로 변경."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE exam_sessions
            SET status = 'failed', completed_at = now()
            WHERE id = $1
            """,
            session_id,
        )
    logger.error("Session %d failed: %s", session_id, error_msg)


async def get_session_from_cache(
    session_id: int,
    redis_client: aioredis.Redis,
) -> Optional[dict]:
    """Redis 캐시에서 세션 상태 조회. 캐시 미스 시 None 반환."""
    redis_key = f"session:{session_id}"
    cached = await redis_client.get(redis_key)
    if cached:
        return json.loads(cached)
    return None
