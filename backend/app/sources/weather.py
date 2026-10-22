"""Closed-day parcel weather from weather-api (gaps filled from Open-Meteo by weather-api)."""
from __future__ import annotations

from datetime import date

import httpx

from .http import get_json, signed_headers

SOURCE = "weather-api"
# weather-api fills missing days with a 25 s budget; leave room for the closed-day query.
_TIMEOUT_S = 40.0


async def fetch_daily(client: httpx.AsyncClient, base_url: str, tenant_id: str, hmac_secret: str,
                      parcel_urn: str, start: date, end: date) -> list[dict]:
    short = parcel_urn.split(":")[-1]
    data = await get_json(client, SOURCE, f"{base_url}/api/weather/parcel/{short}/daily",
                          params={"start": start.isoformat(), "end": end.isoformat(),
                                  "fill": "open_meteo"},
                          headers=signed_headers(tenant_id, hmac_secret), timeout=_TIMEOUT_S)
    return list((data or {}).get("days") or [])
