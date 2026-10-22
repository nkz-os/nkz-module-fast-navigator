import httpx
import pytest

from app.sources import bioorch


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_coefficients_url():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"eppo": "TRZAX"})

    async with _client(handler) as c:
        assert await bioorch.fetch_coefficients(c, "http://bio:8420", "TRZAX") == {"eppo": "TRZAX"}
    assert seen["url"] == "http://bio:8420/api/graph/agriculture/crop-balance-coefficients?eppo=TRZAX"


async def test_unknown_crop_is_none():
    async with _client(lambda r: httpx.Response(404, json={"detail": "x"})) as c:
        assert await bioorch.fetch_coefficients(c, "http://bio:8420", "ORYSA") is None


async def test_regional_yields_params():
    seen = {}

    def handler(request):
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={})

    async with _client(handler) as c:
        await bioorch.fetch_regional_yields(c, "http://bio:8420", "TRZAX", "ES22")
    assert seen["params"] == {"eppo": "TRZAX", "nuts": "ES22", "recent": "5"}


async def test_nuts_region_by_municipality_or_point():
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"nuts": "ES22"})

    async with _client(handler) as c:
        await bioorch.fetch_nuts_region(c, "http://bio:8420", municipality="31201")
        await bioorch.fetch_nuts_region(c, "http://bio:8420", lat=42.8, lon=-1.6)
    assert seen == [{"municipality": "31201"}, {"lat": "42.8", "lon": "-1.6"}]


async def test_nuts_region_needs_a_key():
    async with _client(lambda r: httpx.Response(200, json={})) as c:
        with pytest.raises(ValueError):
            await bioorch.fetch_nuts_region(c, "http://bio:8420")
