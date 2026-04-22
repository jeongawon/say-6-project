"""
HAPI FHIR httpx 래퍼 — read, create, patch, transaction.

[이 파일이 하는 일]
HAPI FHIR 서버(=DB)와 HTTP로 통신하는 코드.
다른 파일들이 FHIR 서버에 데이터 넣고 뺄 때 이 파일을 통해서 함.

[함수 설명]
- create(resource_type, body) → FHIR 서버에 새 리소스 저장 (POST)
- read(resource_type, id)     → FHIR 서버에서 리소스 조회 (GET)
- patch(resource_type, id, body) → FHIR 서버에서 리소스 수정 (PATCH)
- transaction(bundle)         → 여러 리소스를 한 번에 저장 (POST Bundle)
- search(resource_type, params) → 조건으로 리소스 검색 (GET ?params)

[FHIR 설명]
HAPI FHIR 서버는 REST API를 제공하는 DB 서버.
POST /fhir/Patient {JSON} → 환자 저장
GET /fhir/Observation?encounter=xxx → 해당 방문의 검사 결과 조회
이 파일이 그 HTTP 호출을 감싸주는 래퍼.
"""
from __future__ import annotations

import httpx
import logging
from typing import Any

from app.config import FHIR_BASE_URL

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=FHIR_BASE_URL,
            headers={"Content-Type": "application/fhir+json"},
            timeout=30.0,
        )
    return _client


async def create(resource_type: str, body: dict) -> dict:
    """POST a single FHIR resource."""
    client = await _get_client()
    resp = await client.post(f"/{resource_type}", json=body)
    resp.raise_for_status()
    return resp.json()


async def read(resource_type: str, resource_id: str) -> dict:
    """GET a single FHIR resource by id."""
    client = await _get_client()
    resp = await client.get(f"/{resource_type}/{resource_id}")
    resp.raise_for_status()
    return resp.json()


async def patch(resource_type: str, resource_id: str, body: dict) -> dict:
    """PATCH (JSON Merge Patch) a FHIR resource."""
    client = await _get_client()
    resp = await client.patch(
        f"/{resource_type}/{resource_id}",
        json=body,
        headers={"Content-Type": "application/merge-patch+json"},
    )
    resp.raise_for_status()
    return resp.json()


async def transaction(bundle: dict) -> dict:
    """POST a Bundle (type=transaction) to the FHIR root."""
    client = await _get_client()
    resp = await client.post("/", json=bundle)
    resp.raise_for_status()
    return resp.json()


async def search(resource_type: str, params: dict) -> list[dict]:
    """GET search with query params, return list of entries."""
    client = await _get_client()
    resp = await client.get(f"/{resource_type}", params=params)
    resp.raise_for_status()
    bundle = resp.json()
    return [e["resource"] for e in bundle.get("entry", [])]
