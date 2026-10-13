"""Outbound HTTP to platform services: signed like the api-gateway, one error contract."""
from __future__ import annotations

import logging
from typing import Any

import httpx
from nkz_platform_sdk.crypto import generate_hmac_signature

from .errors import SourceUnavailable

logger = logging.getLogger(__name__)

USER_ID = "fast-navigator"


def signed_headers(tenant_id: str, hmac_secret: str) -> dict[str, str]:
    """Gateway-equivalent identity for a module-to-module call.

    Backends verify X-Auth-Signature over (token, tenant). A service call has no user token,
    so the signed token is the empty string (SDK convention for internal calls). Without
    HMAC_SECRET the header is left out; a backend that requires it answers 401, which
    surfaces as SourceUnavailable, never as data.
    """
    headers = {"X-Tenant-ID": tenant_id, "X-User-ID": USER_ID}
    if hmac_secret:
        headers["X-Auth-Signature"] = generate_hmac_signature(hmac_secret, "", tenant_id)
    return headers


async def get_json(client: httpx.AsyncClient, source: str, url: str, *,
                   params: dict[str, Any] | None = None,
                   headers: dict[str, str] | None = None,
                   timeout: float = 20.0) -> Any | None:
    """GET a JSON document. 404 means the source has nothing (None); any other failure raises."""
    try:
        resp = await client.get(url, params=params, headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        logger.warning("source unreachable source=%s error=%s", source, type(exc).__name__)
        raise SourceUnavailable(source, f"unreachable ({type(exc).__name__})") from exc
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        logger.warning("source error source=%s status=%s", source, resp.status_code)
        raise SourceUnavailable(source, f"answered {resp.status_code}")
    try:
        return resp.json()
    except ValueError as exc:
        logger.warning("source answered invalid JSON source=%s", source)
        raise SourceUnavailable(source, "answered invalid JSON") from exc
