import asyncio
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from app.api import CAMPAIGN_PARCELS_CONCURRENCY, get_sources_factory
from app.main import app
from app.sources.errors import SourceUnavailable
from tests.fakes import URN, FakeSources, complete_data

FARMER = {"X-Tenant-ID": "tenant-a", "X-User-ID": "u-farmer", "X-User-Roles": "Farmer"}
URL = "/api/fast/sources/campaigns/2027/parcels"
OTHER = "urn:ngsi-ld:AgriParcel:p0"


def _client(make):
    @asynccontextmanager
    async def factory(tenant_id):
        yield make()

    app.dependency_overrides[get_sources_factory] = lambda: factory
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear():
    yield
    app.dependency_overrides.clear()


def _two_parcels():
    data = complete_data()
    data["parcels"][OTHER] = {"id": OTHER, "type": "AgriParcel", "area": 3.0, "name": "Alpha"}
    data["parcels"]["urn:ngsi-ld:AgriParcel:p9"] = {"id": "urn:ngsi-ld:AgriParcel:p9",
                                                    "type": "AgriParcel", "area": 1.0}
    return data


def test_lists_every_parcel_of_the_campaign():
    data = _two_parcels()
    r = _client(lambda: FakeSources(**data)).get(URL, headers=FARMER)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["campaign"] == 2027
    assert [p["id"] for p in body["parcels"]] == [OTHER, URN, "urn:ngsi-ld:AgriParcel:p9"]
    north = body["parcels"][1]
    assert north["cycle"]["crop_id"] == "c2"
    assert north["crop"]["value"] == "TRZAX"
    assert north["analyses"][0]["id"] == "a1"
    assert body["parcels"][0]["cycle"] is None


def test_same_body_as_the_single_parcel_route():
    data = complete_data()
    c = _client(lambda: FakeSources(**data))
    one = c.get("/api/fast/sources/parcels/p1?campaign=2027", headers=FARMER).json()
    listed = c.get(URL, headers=FARMER).json()["parcels"][0]
    assert listed == {**one["parcel"], **{k: v for k, v in one.items() if k != "parcel"}}


def test_needs_a_plan_role():
    c = _client(lambda: FakeSources(**complete_data()))
    assert c.get(URL, headers=dict(FARMER, **{"X-User-Roles": "Viewer"})).status_code == 403
    assert c.get(URL).status_code == 401


def test_a_broker_failure_is_503():
    c = _client(lambda: FakeSources(**complete_data(),
                                    fail={"parcels": SourceUnavailable("broker", "x")}))
    r = c.get(URL, headers=FARMER)
    assert r.status_code == 503 and r.json()["source"] == "broker"


def test_concurrency_is_bounded():
    data = complete_data()
    for i in range(30):
        u = f"urn:ngsi-ld:AgriParcel:q{i}"
        data["parcels"][u] = {"id": u, "type": "AgriParcel", "area": 1.0, "name": f"P{i:02d}"}
    state = {"now": 0, "max": 0}

    class Counting(FakeSources):
        async def timeline(self, urn, at):
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
            await asyncio.sleep(0.01)
            state["now"] -= 1
            return await super().timeline(urn, at)

    r = _client(lambda: Counting(**data)).get(URL, headers=FARMER)
    assert r.status_code == 200 and len(r.json()["parcels"]) == 31
    assert 1 < state["max"] <= CAMPAIGN_PARCELS_CONCURRENCY


def test_campaign_out_of_range_is_422():
    c = _client(lambda: FakeSources(**complete_data()))
    assert c.get("/api/fast/sources/campaigns/1999/parcels", headers=FARMER).status_code == 422


def test_a_parcel_failure_is_503_and_cancels_the_other_parcels_before_closing_the_sources():
    data = _two_parcels()
    events = []

    class FailingOne(FakeSources):
        async def timeline(self, urn, at):
            if urn == OTHER:
                await asyncio.sleep(0.01)
                raise SourceUnavailable("crop-cycles", "x")
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                events.append("cancelled")
                raise
            return await super().timeline(urn, at)

    @asynccontextmanager
    async def factory(tenant_id):
        try:
            yield FailingOne(**data)
        finally:
            events.append("closed")

    app.dependency_overrides[get_sources_factory] = lambda: factory
    r = TestClient(app).get(URL, headers=FARMER)
    assert r.status_code == 503 and r.json()["source"] == "crop-cycles"
    # The other parcels stop before the sources client closes, not after.
    assert "cancelled" in events and events.index("cancelled") < events.index("closed")
