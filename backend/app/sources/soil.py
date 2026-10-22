"""Soil module: laboratory analyses of a parcel and its estimated topsoil (spec §4, §5.1)."""
from __future__ import annotations

import httpx

from .http import get_json, signed_headers

SOURCE = "soil"


async def fetch_lab_analyses(client: httpx.AsyncClient, base_url: str, tenant_id: str,
                             hmac_secret: str, parcel_urn: str) -> list[dict]:
    data = await get_json(client, SOURCE, f"{base_url}/v1/soil/parcel/{parcel_urn}/lab-analyses",
                          headers=signed_headers(tenant_id, hmac_secret))
    return list((data or {}).get("analyses") or [])


async def fetch_estimated_horizons(client: httpx.AsyncClient, base_url: str, tenant_id: str,
                                   hmac_secret: str, parcel_urn: str) -> list[dict]:
    data = await get_json(client, SOURCE, f"{base_url}/v1/soil/parcel/{parcel_urn}/horizons",
                          params={"depth": "0-30"}, headers=signed_headers(tenant_id, hmac_secret))
    return list((data or {}).get("horizons") or [])
