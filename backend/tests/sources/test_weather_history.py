import httpx

from app.sources import weather

URN = "urn:ngsi-ld:AgriParcel:p1"
ATTR = "Contains modified Copernicus Climate Change Service information 2026; Open-Meteo (CC BY 4.0)"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _fetch(handler):
    async with _client(handler) as c:
        return await weather.fetch_history_precip(c, "http://wx:8000", "tenant-a", "s3cret", URN,
                                                  2016, 2025)


async def test_ready_history_is_one_signed_call_with_the_whole_window():
    seen = []

    def handler(request):
        seen.append((request.url.path, dict(request.url.params), "X-Auth-Signature" in request.headers))
        return httpx.Response(200, json={
            "days": [{"date": "2016-01-01", "precip_mm": 1.5}], "attribution": ATTR,
            "latest_available": "2026-11-09", "provenance": {"precip_mm": {"source": "era5"}}})

    got = await _fetch(handler)
    assert seen == [("/api/weather/parcel/p1/history",
                     {"start": "2016-01-01", "end": "2025-12-31", "resolution": "daily",
                      "vars": "precip_mm"}, True)]
    assert got.ready and got.reason is None and got.attribution == ATTR
    assert list(got.days) == [{"date": "2016-01-01", "precip_mm": 1.5}]


async def test_incomplete_years_is_not_ready():
    got = await _fetch(lambda r: httpx.Response(200, json={
        "days": [{"date": "2025-01-01", "precip_mm": 0.0}], "incomplete_years": [2016, 2017]}))
    assert not got.ready and got.reason == "not_ready" and not got.days


async def test_503_is_not_ready():
    got = await _fetch(lambda r: httpx.Response(503, json={"detail": "history is being prepared"}))
    assert not got.ready and got.reason == "not_ready"


async def test_422_400_and_502_are_unavailable():
    for status in (422, 400, 502, 401):
        got = await _fetch(lambda r, s=status: httpx.Response(s, json={"error": "x"}))
        assert not got.ready and got.reason == "unavailable", status


async def test_timeout_is_not_ready():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    got = await _fetch(handler)
    assert not got.ready and got.reason == "not_ready"


async def test_connection_error_and_bad_body_are_unavailable():
    def boom(request):
        raise httpx.ConnectError("down", request=request)

    assert (await _fetch(boom)).reason == "unavailable"
    assert (await _fetch(lambda r: httpx.Response(200, content=b"not json"))).reason == "unavailable"
    assert (await _fetch(lambda r: httpx.Response(200, json={"days": []}))).reason == "unavailable"


async def test_history_timeout_is_the_weather_api_deadline():
    assert weather.HISTORY_TIMEOUT_S == 10.0
