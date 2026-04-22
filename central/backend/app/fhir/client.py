"""HAPI FHIR httpx 래퍼 — read, create, patch, transaction."""
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
