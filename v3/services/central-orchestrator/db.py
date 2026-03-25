"""
central-orchestrator — Database 연결 풀 및 테이블 자동 생성.

asyncpg 기반 connection pool.
startup 시 테이블이 없으면 자동 생성 (idempotent).

테이블 구조:
- patients: 환자 기본 정보
- exam_sessions: 검사 세션 (1 환자 → N 세션)
- modal_results: 모달별 검사 결과 (1 세션 → N 결과)
- comprehensive_reports: 종합 소견서 (1 세션 → 1 소견서)
"""

import logging
from urllib.parse import urlparse

import asyncpg

from config import settings

logger = logging.getLogger("orchestrator.db")

# ╔══════════════════════════════════════════════════════════╗
# ║  TODO: [팀원D] 테이블 스키마 변경 시 수정 포인트          ║
# ║  새로운 컬럼이나 테이블이 필요하면 아래 SQL을 수정하세요.  ║
# ║  CREATE TABLE IF NOT EXISTS를 사용하므로 기존 테이블에     ║
# ║  영향을 주지 않습니다. 단, 기존 테이블에 컬럼 추가 시에는  ║
# ║  ALTER TABLE 마이그레이션이 별도로 필요합니다.             ║
# ╚══════════════════════════════════════════════════════════╝

# ── DDL: 테이블 자동 생성 (멱등성 보장) ──────────────────────────────
CREATE_TABLES_SQL = """
-- 환자 기본 정보 테이블
-- patient_id를 PK로 사용하여 중복 방지 (UPSERT 지원)
CREATE TABLE IF NOT EXISTS patients (
    patient_id   TEXT PRIMARY KEY,       -- 환자 고유 식별자
    age          INT,                    -- 나이
    sex          TEXT,                   -- 성별
    chief_complaint TEXT,                -- 주호소 (예: "흉통 및 호흡곤란")
    history      JSONB DEFAULT '[]',     -- 병력 리스트 (JSON 배열)
    created_at   TIMESTAMPTZ DEFAULT now()  -- 최초 등록 시각
);

-- 검사 세션 테이블
-- 환자 1명에 대해 여러 번의 검사 세션을 가질 수 있음
CREATE TABLE IF NOT EXISTS exam_sessions (
    id           SERIAL PRIMARY KEY,     -- 세션 ID (자동 증가)
    patient_id   TEXT NOT NULL REFERENCES patients(patient_id) ON DELETE CASCADE,
    status       TEXT NOT NULL DEFAULT 'in_progress',   -- in_progress | completed | failed
    patient_info JSONB NOT NULL,         -- 세션 시작 시점의 환자 정보 스냅샷
    created_at   TIMESTAMPTZ DEFAULT now(),   -- 세션 시작 시각
    completed_at TIMESTAMPTZ             -- 세션 종료 시각 (완료 또는 실패)
);

-- 모달별 검사 결과 테이블
-- 1개 세션에서 여러 모달(chest, ecg, blood) 결과를 저장
CREATE TABLE IF NOT EXISTS modal_results (
    id           SERIAL PRIMARY KEY,     -- 결과 ID (자동 증가)
    session_id   INT NOT NULL REFERENCES exam_sessions(id) ON DELETE CASCADE,
    modal        TEXT NOT NULL,          -- 모달 종류: chest | ecg | blood
    findings     JSONB DEFAULT '[]',     -- 검출 결과 리스트 (JSON 배열)
    summary      TEXT DEFAULT '',        -- 요약 소견
    report       TEXT DEFAULT '',        -- 상세 리포트
    metadata     JSONB DEFAULT '{}',     -- 추가 메타데이터 (모델 버전, 추론 시간 등)
    created_at   TIMESTAMPTZ DEFAULT now()  -- 결과 저장 시각
);

-- 종합 소견서 테이블
-- 모든 모달 검사 완료 후 report-svc가 생성한 최종 소견서
CREATE TABLE IF NOT EXISTS comprehensive_reports (
    id           SERIAL PRIMARY KEY,     -- 리포트 ID (자동 증가)
    session_id   INT NOT NULL REFERENCES exam_sessions(id) ON DELETE CASCADE,
    report       TEXT NOT NULL,          -- 종합 소견서 본문
    diagnosis    TEXT NOT NULL,          -- 최종 진단
    created_at   TIMESTAMPTZ DEFAULT now()  -- 소견서 생성 시각
);
"""


def _parse_dsn(database_url: str) -> dict:
    """
    DATABASE_URL 문자열을 asyncpg 호환 kwargs로 파싱.

    예) "postgresql://user:pass@host:5432/dbname"
    → {"host": "host", "port": 5432, "user": "user", "password": "pass", "database": "dbname"}
    """
    parsed = urlparse(database_url)
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "user": parsed.username or "postgres",
        "password": parsed.password or "postgres",
        "database": parsed.path.lstrip("/") or "drai",
    }


async def create_pool() -> asyncpg.Pool:
    """
    asyncpg 커넥션 풀 생성 및 테이블 존재 확인.

    1. DATABASE_URL을 파싱하여 접속 정보 추출
    2. 커넥션 풀 생성 (min=2, max=10)
    3. CREATE TABLE IF NOT EXISTS로 테이블 자동 생성 (멱등성)
    """
    dsn_kwargs = _parse_dsn(settings.database_url)
    logger.info("Connecting to PostgreSQL at %s:%s/%s", dsn_kwargs["host"], dsn_kwargs["port"], dsn_kwargs["database"])

    pool = await asyncpg.create_pool(
        **dsn_kwargs,
        min_size=2,           # 최소 커넥션 수 (유휴 상태에서도 유지)
        max_size=10,          # 최대 커넥션 수 (동시 쿼리 제한)
        command_timeout=30,   # 개별 쿼리 타임아웃 (초)
    )

    # 테이블 자동 생성 (IF NOT EXISTS이므로 이미 존재해도 안전)
    async with pool.acquire() as conn:
        await conn.execute(CREATE_TABLES_SQL)
        logger.info("Database tables verified/created.")

    return pool


async def close_pool(pool: asyncpg.Pool) -> None:
    """커넥션 풀 정상 종료. 모든 활성 커넥션을 정리합니다."""
    if pool:
        await pool.close()
        logger.info("Database connection pool closed.")
