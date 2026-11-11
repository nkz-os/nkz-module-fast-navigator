"""Closed-day parcel weather from weather-api (gaps filled from Open-Meteo by weather-api)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import httpx

from .http import get_json, signed_headers

logger = logging.getLogger(__name__)

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


# weather-api answers /history within 20 s by design (its own deadline, under the gateway's 30 s).
HISTORY_TIMEOUT_S = 20.0


@dataclass(frozen=True)
class HistoryPrecip:
    """Daily precipitation from the parcel weather history, or why it is not usable now.

    reason: "not_ready" (cold cache, deadline, timeout: a later call may succeed) or
    "unavailable" (the history cannot serve this parcel or window).
    """
    ready: bool
    reason: str | None
    days: tuple[dict, ...]
    attribution: str | None


def _no_history(reason: str) -> HistoryPrecip:
    return HistoryPrecip(False, reason, (), None)


async def fetch_history_precip(client: httpx.AsyncClient, base_url: str, tenant_id: str,
                               hmac_secret: str, parcel_urn: str, first_year: int,
                               last_year: int) -> HistoryPrecip:
    """One /history call for the whole window. Never raises on HTTP or body errors."""
    short = parcel_urn.split(":")[-1]
    try:
        resp = await client.get(
            f"{base_url}/api/weather/parcel/{short}/history",
            params={"start": f"{first_year}-01-01", "end": f"{last_year}-12-31",
                    "resolution": "daily", "vars": "precip_mm"},
            headers=signed_headers(tenant_id, hmac_secret), timeout=HISTORY_TIMEOUT_S)
    except httpx.TimeoutException:
        logger.warning("history unavailable source=%s reason=timeout", SOURCE)
        return _no_history("not_ready")
    except httpx.HTTPError as exc:
        logger.warning("history unavailable source=%s error=%s", SOURCE, type(exc).__name__)
        return _no_history("unavailable")
    if resp.status_code == 503:
        logger.info("history not ready source=%s status=503", SOURCE)
        return _no_history("not_ready")
    if resp.status_code != 200:
        logger.warning("history unavailable source=%s status=%s", SOURCE, resp.status_code)
        return _no_history("unavailable")
    try:
        body = resp.json()
    except ValueError:
        logger.warning("history answered invalid JSON source=%s", SOURCE)
        return _no_history("unavailable")
    if not isinstance(body, dict):
        return _no_history("unavailable")
    if body.get("incomplete_years"):
        logger.info("history not ready source=%s incomplete_years=%s", SOURCE,
                    body["incomplete_years"])
        return _no_history("not_ready")
    days = body.get("days")
    if not isinstance(days, list) or not days:
        logger.warning("history answered no days source=%s", SOURCE)
        return _no_history("unavailable")
    attribution = body.get("attribution")
    return HistoryPrecip(True, None, tuple(d for d in days if isinstance(d, dict)),
                         attribution if isinstance(attribution, str) and attribution else None)
