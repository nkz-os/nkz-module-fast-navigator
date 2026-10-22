from datetime import date

import httpx
import pytest
from nkz_platform_sdk.crop_timeline import CropDataUnavailable, ParcelNotFound

from app.sources import cycles, weather
from app.sources.errors import SourceUnavailable

URN = "urn:ngsi-ld:AgriParcel:p1"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_timeline_resolves_the_platform_rule_over_the_broker(monkeypatch):
    seen = {}
    orion = object()

    async def load(client, urn):
        seen["client"], seen["urn"] = client, urn
        return {"id": urn}, [], []

    monkeypatch.setattr(cycles, "load_crop_data", load)
    got = await cycles.fetch_timeline(orion, URN, date(2026, 10, 13))
    assert seen == {"client": orion, "urn": URN}
    assert got["parcel_id"] == URN and got["cycles"] == [] and got["current"] is None
    assert got["at"] == "2026-10-13"


async def test_timeline_of_an_unknown_parcel_is_none(monkeypatch):
    async def load(client, urn):
        raise ParcelNotFound(urn)

    monkeypatch.setattr(cycles, "load_crop_data", load)
    assert await cycles.fetch_timeline(object(), URN, date(2026, 10, 13)) is None


async def test_timeline_unreadable_broker_is_source_unavailable(monkeypatch):
    async def load(client, urn):
        raise CropDataUnavailable("503: broker down")

    monkeypatch.setattr(cycles, "load_crop_data", load)
    with pytest.raises(SourceUnavailable) as exc:
        await cycles.fetch_timeline(object(), URN, date(2026, 10, 13))
    assert exc.value.source == cycles.SOURCE


async def test_daily_uses_the_short_id_and_the_fill():
    seen = {}

    def handler(request):
        seen["path"], seen["params"] = request.url.path, dict(request.url.params)
        seen["signed"] = "X-Auth-Signature" in request.headers
        return httpx.Response(200, json={"days": [{"date": "2020-01-01", "precip_mm": 1.0}]})

    async with _client(handler) as c:
        got = await weather.fetch_daily(c, "http://wx:8000", "tenant-a", "s3cret", URN,
                                        date(2020, 1, 1), date(2020, 12, 31))
    assert got == [{"date": "2020-01-01", "precip_mm": 1.0}] and seen["signed"]
    assert seen["path"] == "/api/weather/parcel/p1/daily"
    assert seen["params"] == {"start": "2020-01-01", "end": "2020-12-31", "fill": "open_meteo"}
