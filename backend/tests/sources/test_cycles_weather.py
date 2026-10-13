from datetime import date

import httpx

from app.sources import cycles, weather

URN = "urn:ngsi-ld:AgriParcel:p1"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_timeline_uses_the_internal_route_and_secret():
    seen = {}

    def handler(request):
        seen["url"], seen["secret"] = str(request.url), request.headers.get("X-Internal-Service-Secret")
        return httpx.Response(200, json={"cycles": []})

    async with _client(handler) as c:
        got = await cycles.fetch_timeline(c, "http://em:5000", "int-secret", "tenant-a", URN,
                                          date(2026, 10, 13))
    assert got == {"cycles": []} and seen["secret"] == "int-secret"
    assert seen["url"] == (f"http://em:5000/api/internal/parcels/{URN}/crop-cycles"
                           "?tenant_id=tenant-a&at=2026-10-13")


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
