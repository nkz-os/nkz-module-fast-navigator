import httpx
import pytest
from nkz_platform_sdk.crypto import verify_hmac_signature

from app.sources.errors import SourceUnavailable
from app.sources.http import USER_ID, get_json, signed_headers


def test_signed_headers_carry_a_valid_signature():
    h = signed_headers("tenant-a", "s3cret")
    assert h["X-Tenant-ID"] == "tenant-a"
    assert h["X-User-ID"] == USER_ID
    assert verify_hmac_signature("s3cret", h["X-Auth-Signature"], "", "tenant-a")


def test_signed_headers_without_secret_omit_the_signature():
    assert "X-Auth-Signature" not in signed_headers("tenant-a", "")


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_get_json_returns_the_body():
    async with _client(lambda r: httpx.Response(200, json={"a": 1})) as c:
        assert await get_json(c, "src", "http://svc/x") == {"a": 1}


async def test_get_json_404_is_none():
    async with _client(lambda r: httpx.Response(404, json={"detail": "x"})) as c:
        assert await get_json(c, "src", "http://svc/x") is None


@pytest.mark.parametrize("status", [401, 422, 500, 503])
async def test_get_json_other_status_raises_naming_the_source(status):
    async with _client(lambda r: httpx.Response(status)) as c:
        with pytest.raises(SourceUnavailable) as err:
            await get_json(c, "soil", "http://svc/x")
    assert err.value.source == "soil"
    assert str(status) in err.value.detail


async def test_get_json_network_error_raises():
    def boom(request):
        raise httpx.ConnectError("down", request=request)

    async with _client(boom) as c:
        with pytest.raises(SourceUnavailable) as err:
            await get_json(c, "soil", "http://svc/x")
    assert "ConnectError" in err.value.detail


async def test_get_json_invalid_json_raises():
    async with _client(lambda r: httpx.Response(200, content=b"<html>")) as c:
        with pytest.raises(SourceUnavailable):
            await get_json(c, "soil", "http://svc/x")
