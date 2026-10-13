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
