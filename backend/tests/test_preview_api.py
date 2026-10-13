from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from app.api import get_sources_factory
from app.main import app
from app.sources.errors import SourceUnavailable
from tests.fakes import URN, FakeSources, complete_data

FARMER = {"X-Tenant-ID": "tenant-a", "X-User-ID": "u-farmer", "X-User-Roles": "Farmer"}
TECH = {"X-Tenant-ID": "tenant-a", "X-User-ID": "u-tech", "X-User-Roles": "TechnicalConsultant"}
BODY = {"campaign": 2027, "parcel_ids": [URN], "tillage": True, "irrigated": False,
        "rotation_years": 4}


@pytest.fixture
def data():
    return complete_data()


@pytest.fixture
def client(data):
    @asynccontextmanager
    async def factory(tenant_id):
        yield FakeSources(**data)

    app.dependency_overrides[get_sources_factory] = lambda: factory
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_preview_needs_the_gateway_identity(client):
    assert client.post("/api/fast/calc/preview", json=BODY).status_code == 401


def test_preview_needs_a_plan_role(client):
    viewer = dict(FARMER, **{"X-User-Roles": "Viewer"})
    assert client.post("/api/fast/calc/preview", json=BODY, headers=viewer).status_code == 403


def test_preview_of_a_complete_sheet(client):
    r = client.post("/api/fast/calc/preview", json=BODY, headers=FARMER)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "complete" and body["n"]["avg_kg_ha"] > 0


def test_a_short_parcel_id_is_accepted(client):
    body = dict(BODY, parcel_ids=["p1"])
    assert client.post("/api/fast/calc/preview", json=body, headers=FARMER).status_code == 200


def test_the_farmer_cannot_override_a_technician_value(client):
    body = dict(BODY, overrides=[{"param": "irrigation.uptake", "value": 0.5, "reason": "x"}])
    assert client.post("/api/fast/calc/preview", json=body, headers=FARMER).status_code == 403


def test_the_technician_overrides_and_is_recorded(client):
    body = dict(BODY, overrides=[{"param": "soil.ph", "value": 7.2, "reason": "new lab sheet"}])
    r = client.post("/api/fast/calc/preview", json=body, headers=TECH)
    assert r.status_code == 200
    ph = r.json()["inputs"]["soil.ph"]
    assert ph["provenance"] == "entered" and ph["note"] == "new lab sheet"
    assert ph["source"].startswith("user:u-tech@")


def test_the_farmer_sets_the_organic_availability(client):
    body = dict(BODY, organic=[{"material": "slurry", "rate_t_ha": 30, "n_pct": 0.5,
                                "p2o5_pct": 0.2, "k2o_pct": 0.6}],
                overrides=[{"param": "organic.0.availability", "value": 0.6, "reason": "own analysis"}])
    r = client.post("/api/fast/calc/preview", json=body, headers=FARMER)
    assert r.status_code == 200
    assert r.json()["inputs"]["organic.0.availability"]["provenance"] == "entered"


@pytest.mark.parametrize("override", [
    {"param": "soil.ph", "value": 7.2, "reason": ""},
    {"param": "soil.ph", "value": 7.2, "reason": "   "},
    {"param": "soil.ph", "value": 99, "reason": "typo"},
    {"param": "soil.unknown", "value": 1, "reason": "x"},
])
def test_bad_overrides_are_rejected(client, override):
    body = dict(BODY, overrides=[override])
    assert client.post("/api/fast/calc/preview", json=body, headers=TECH).status_code == 422


def test_an_invalid_organic_application_is_rejected(client):
    body = dict(BODY, organic=[{"material": "guano", "rate_t_ha": 1, "n_pct": 1,
                                "p2o5_pct": 1, "k2o_pct": 1}])
    assert client.post("/api/fast/calc/preview", json=body, headers=FARMER).status_code == 422


def test_a_failing_source_is_a_503_naming_it(client, data):
    data["fail"] = {"lab_analyses": SourceUnavailable("soil", "answered 500")}
    r = client.post("/api/fast/calc/preview", json=BODY, headers=FARMER)
    assert r.status_code == 503
    assert r.json() == {"error": "source_unavailable", "source": "soil", "detail": "answered 500"}


def test_an_unknown_parcel_is_a_404(client):
    body = dict(BODY, parcel_ids=["urn:ngsi-ld:AgriParcel:nope"])
    assert client.post("/api/fast/calc/preview", json=body, headers=FARMER).status_code == 404


def test_wizard_data_of_a_parcel(client):
    r = client.get("/api/fast/sources/parcels/p1", params={"campaign": 2027}, headers=FARMER)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["parcel"]["area_ha"]["value"] == 10.0
    assert body["crop"]["value"] == "TRZAX" and body["previous_crop"]["value"] == "TRZAX"
    assert body["analyses"] == [{"id": "a1", "samplingDate": "2026-09-01",
                                 "laboratoryReference": None,
                                 "fields": sorted(complete_data()["analyses"][URN][0]["horizons"][0])}]


def test_the_template_example_routes_are_gone(client):
    assert client.get("/api/fast/data", headers=FARMER).status_code == 404


@pytest.mark.parametrize("bad", ['p"1', "p;1", "urn:ngsi-ld:AgriParcel:a'b"])
def test_unsafe_parcel_ids_are_rejected(client, bad):
    body = dict(BODY, parcel_ids=[bad])
    assert client.post("/api/fast/calc/preview", json=body, headers=FARMER).status_code == 422
    r = client.get("/api/fast/sources/parcels/" + bad, params={"campaign": 2027}, headers=FARMER)
    assert r.status_code == 422


def test_an_override_of_a_missing_organic_application_is_rejected(client):
    body = dict(BODY, organic=[{"material": "slurry", "rate_t_ha": 30, "n_pct": 0.5,
                                "p2o5_pct": 0.2, "k2o_pct": 0.6}],
                overrides=[{"param": "organic.1.availability", "value": 0.6, "reason": "x"}])
    assert client.post("/api/fast/calc/preview", json=body, headers=FARMER).status_code == 422
