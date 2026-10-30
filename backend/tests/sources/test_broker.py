import httpx
import pytest

from app.sources import broker
from app.sources.errors import SourceUnavailable

_REQ = httpx.Request("GET", "http://orion/ngsi-ld/v1/entities")


def _status(code: int) -> httpx.HTTPStatusError:
    return httpx.HTTPStatusError("x", request=_REQ, response=httpx.Response(code, request=_REQ))


class FakeOrion:
    def __init__(self, entity=None, pages=(), error=None):
        self.entity, self.pages, self.error, self.calls = entity, list(pages), error, []

    async def get_entity(self, entity_id, options=None):
        self.calls.append(("get", entity_id, options))
        if self.error:
            raise self.error
        return self.entity

    async def query_entities(self, type=None, q=None, limit=100, offset=0, attrs=None,
                             options=None):
        self.calls.append(("query", type, q, limit, offset, options))
        if self.error:
            raise self.error
        index = offset // limit
        return self.pages[index] if index < len(self.pages) else []


async def test_parcel_is_read_as_key_values():
    orion = FakeOrion(entity={"id": "urn:ngsi-ld:AgriParcel:p1"})
    assert await broker.fetch_parcel(orion, "urn:ngsi-ld:AgriParcel:p1") == {
        "id": "urn:ngsi-ld:AgriParcel:p1"}
    assert orion.calls == [("get", "urn:ngsi-ld:AgriParcel:p1", "keyValues")]


async def test_absent_parcel_is_none():
    assert await broker.fetch_parcel(FakeOrion(error=_status(404)), "urn:x") is None


@pytest.mark.parametrize("error", [_status(500), httpx.ConnectError("down", request=_REQ)])
async def test_broker_failure_raises(error):
    with pytest.raises(SourceUnavailable) as err:
        await broker.fetch_parcel(FakeOrion(error=error), "urn:x")
    assert err.value.source == "broker"


async def test_harvests_query_and_pagination():
    full = [{"id": f"h{i}"} for i in range(broker.PAGE)]
    orion = FakeOrion(pages=[full, [{"id": "last"}]])
    got = await broker.fetch_harvests(orion, "urn:ngsi-ld:AgriParcel:p1")
    assert len(got) == broker.PAGE + 1
    _, typ, q, _limit, _offset, options = orion.calls[0]
    assert typ == "AgriParcelOperation" and options == "keyValues"
    assert q == ('hasAgriParcel=="urn:ngsi-ld:AgriParcel:p1";operationType=="harvesting";'
                 'status=="completed"')
    assert [c[4] for c in orion.calls] == [0, broker.PAGE]


async def test_fertilizations_include_started_but_not_issued_or_planned():
    by_status = {"completed": [{"id": "a"}], "incomplete": [{"id": "b"}],
                 "needs_review": [{"id": "a"}, {"id": "c"}]}

    class ByStatus(FakeOrion):
        async def query_entities(self, type=None, q=None, **kw):
            self.calls.append(("query", type, q))
            return by_status[q.rsplit('status=="', 1)[1].rstrip('"')]

    orion = ByStatus()
    got = await broker.fetch_fertilizations(orion, "urn:ngsi-ld:AgriParcel:p1")
    assert sorted(e["id"] for e in got) == ["a", "b", "c"]          # duplicates collapse
    assert sorted(by_status) == sorted(c[2].rsplit('status=="', 1)[1].rstrip('"')
                                       for c in orion.calls)


async def test_fetch_parcels_pages_through_all():
    pages = [[{"id": f"p{i}"} for i in range(100)], [{"id": f"p{i}"} for i in range(100, 200)],
             [{"id": f"p{i}"} for i in range(200, 250)]]
    orion = FakeOrion(pages=pages)
    got = await broker.fetch_parcels(orion)
    assert len(got) == 250
    assert [c[4] for c in orion.calls] == [0, 100, 200]
    assert all(c[1] == "AgriParcel" and c[5] == "keyValues" for c in orion.calls)


async def test_fetch_parcels_sends_no_q_param_with_the_real_client():
    from nkz_platform_sdk import OrionClient
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[{"id": "urn:ngsi-ld:AgriParcel:p1"}])

    orion = OrionClient("tenant-a", base_url="http://orion.test")
    orion._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert await broker.fetch_parcels(orion) == [{"id": "urn:ngsi-ld:AgriParcel:p1"}]
    assert "q" not in seen[0].url.params and seen[0].url.params["type"] == "AgriParcel"
    assert "NGSILD-Tenant" in seen[0].headers and "Link" in seen[0].headers
