"""Reads from the context broker through the SDK client (platform @context, keyValues)."""
from __future__ import annotations

import logging

import httpx

from .errors import SourceUnavailable

logger = logging.getLogger(__name__)

SOURCE = "broker"
PAGE = 100


def _failure(exc: httpx.HTTPError) -> SourceUnavailable:
    if isinstance(exc, httpx.HTTPStatusError):
        detail = f"answered {exc.response.status_code}"
    else:
        detail = f"unreachable ({type(exc).__name__})"
    logger.warning("broker read failed: %s", detail)
    return SourceUnavailable(SOURCE, detail)


async def _get(orion, entity_id: str) -> dict | None:
    try:
        return await orion.get_entity(entity_id, options="keyValues")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return None
        raise _failure(exc) from exc
    except httpx.HTTPError as exc:
        raise _failure(exc) from exc


async def _query_all(orion, entity_type: str, q: str) -> list[dict]:
    out: list[dict] = []
    offset = 0
    try:
        while True:
            page = await orion.query_entities(type=entity_type, q=q, limit=PAGE, offset=offset,
                                              options="keyValues")
            out.extend(page or [])
            if not page or len(page) < PAGE:
                return out
            offset += PAGE
    except httpx.HTTPError as exc:
        raise _failure(exc) from exc


async def fetch_parcel(orion, urn: str) -> dict | None:
    return await _get(orion, urn)


async def fetch_harvests(orion, parcel_urn: str) -> list[dict]:
    """Completed harvests of the parcel (field notebook). `refAgriParcel` shares the IRI."""
    q = f'hasAgriParcel=="{parcel_urn}";operationType=="harvesting";status=="completed"'
    return await _query_all(orion, "AgriParcelOperation", q)


async def fetch_water_quality(orion, entity_id: str) -> dict | None:
    return await _get(orion, entity_id)
