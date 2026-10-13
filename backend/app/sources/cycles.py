"""Crop cycles of a parcel, resolved by entity-manager (internal route, spec §4)."""
from __future__ import annotations

from datetime import date

import httpx

from .http import get_json

SOURCE = "entity-manager"


async def fetch_timeline(client: httpx.AsyncClient, base_url: str, internal_secret: str,
                         tenant_id: str, parcel_urn: str, at: date) -> dict | None:
    return await get_json(client, SOURCE,
                          f"{base_url}/api/internal/parcels/{parcel_urn}/crop-cycles",
                          params={"tenant_id": tenant_id, "at": at.isoformat()},
                          headers={"X-Internal-Service-Secret": internal_secret}, timeout=15.0)
