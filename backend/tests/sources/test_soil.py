import httpx

from app.sources import soil

URN = "urn:ngsi-ld:AgriParcel:p1"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_lab_analyses_signed_request():
    seen = {}

    def handler(request):
        seen["url"], seen["headers"] = str(request.url), request.headers
        return httpx.Response(200, json={"parcelId": URN, "analyses": [{"id": "a1"}]})

    async with _client(handler) as c:
        got = await soil.fetch_lab_analyses(c, "http://soil:8000", "tenant-a", "s3cret", URN)
    assert got == [{"id": "a1"}]
    assert seen["url"] == f"http://soil:8000/v1/soil/parcel/{URN}/lab-analyses"
    assert seen["headers"]["X-Tenant-ID"] == "tenant-a"
    assert "X-Auth-Signature" in seen["headers"]


async def test_estimated_horizons_topsoil():
    seen = {}

    def handler(request):
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"horizons": [{"depthFrom": 0, "depthTo": 30}]})

    async with _client(handler) as c:
        got = await soil.fetch_estimated_horizons(c, "http://soil:8000", "tenant-a", "", URN)
    assert got == [{"depthFrom": 0, "depthTo": 30}] and seen["params"] == {"depth": "0-30"}


async def test_nothing_for_the_parcel_is_an_empty_list():
    async with _client(lambda r: httpx.Response(404, json={"detail": "x"})) as c:
        assert await soil.fetch_lab_analyses(c, "http://soil:8000", "t", "", URN) == []
        assert await soil.fetch_estimated_horizons(c, "http://soil:8000", "t", "", URN) == []
