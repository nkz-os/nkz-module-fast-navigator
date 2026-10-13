from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from app.api import get_sources_factory
from app.config import get_settings
from app.main import app
from app.sources.errors import SourceUnavailable
from tests.fakes import URN, FakeSources, complete_data

FARMER = {"X-Tenant-ID": "tenant-a", "X-User-ID": "u-farmer", "X-User-Roles": "Farmer"}
TECH = {"X-Tenant-ID": "tenant-a", "X-User-ID": "u-tech", "X-User-Roles": "TechnicalConsultant"}
ADMIN = {"X-Tenant-ID": "tenant-a", "X-User-ID": "u-admin", "X-User-Roles": "TenantAdmin"}
OTHER = {"X-Tenant-ID": "tenant-b", "X-User-ID": "u-b", "X-User-Roles": "Farmer"}
BASE = "/api/fast/plans"
SHEET = {"key": "wheat", "campaign": 2027, "parcel_ids": [URN], "tillage": True,
         "irrigated": False, "rotation_years": 4}


@pytest.fixture
def data():
    return complete_data()


@pytest.fixture
def client(pg_url, monkeypatch, data):
    monkeypatch.setenv("POSTGRES_URL", pg_url)
    get_settings.cache_clear()

    @asynccontextmanager
    async def factory(tenant_id):
        yield FakeSources(**data)

    app.dependency_overrides[get_sources_factory] = lambda: factory
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    import asyncio

    from tests.conftest import _truncate
    asyncio.run(_truncate(pg_url))


def _new(client, headers=FARMER):
    r = client.post(BASE, json={"campaign": 2027}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _with_sheet(client, sheet=SHEET, headers=FARMER):
    plan = _new(client)
    r = client.put(f"{BASE}/{plan['id']}/sheets", headers=headers,
                   json={"row_version": plan["row_version"], "sheets": [sheet]})
    assert r.status_code == 200, r.text
    return r.json()


def test_the_whole_review_round(client):
    plan = _with_sheet(client)
    pid = plan["id"]
    plan = client.post(f"{BASE}/{pid}/calculate", json={"row_version": plan["row_version"]},
                       headers=FARMER).json()
    assert plan["state"] == "calculated" and plan["sheets"][0]["result"]["status"] == "complete"
    plan = client.post(f"{BASE}/{pid}/submit", json={"row_version": plan["row_version"]},
                       headers=FARMER).json()
    assert plan["state"] == "in_review"
    r = client.post(f"{BASE}/{pid}/return", json={"row_version": plan["row_version"],
                                                  "comment": "add the lab analysis"}, headers=TECH)
    assert r.status_code == 200 and r.json()["state"] == "draft"
    log = client.get(f"{BASE}/{pid}/audit", headers=FARMER).json()
    assert [e["action"] for e in log] == ["create", "edit_sheets", "calculate", "submit", "return"]


def test_reading_roles_and_writing_roles(client):
    plan = _new(client)
    assert client.get(f"{BASE}/{plan['id']}", headers=ADMIN).status_code == 200
    r = client.put(f"{BASE}/{plan['id']}/sheets", headers=ADMIN,
                   json={"row_version": plan["row_version"], "sheets": [SHEET]})
    assert r.status_code == 403
    assert client.post(BASE, json={"campaign": 2027}, headers=ADMIN).status_code == 403
    assert client.get(BASE, headers={"X-Tenant-ID": "tenant-a"}).status_code == 401


def test_a_plan_of_another_tenant_is_invisible(client):
    plan = _new(client)
    assert client.get(f"{BASE}/{plan['id']}", headers=OTHER).status_code == 404
    assert client.get(BASE, headers=OTHER).json() == []
    r = client.post(f"{BASE}/{plan['id']}/calculate", json={"row_version": 1}, headers=OTHER)
    assert r.status_code == 404


def test_a_second_open_plan_and_a_stale_version_are_conflicts(client):
    plan = _new(client)
    assert client.post(BASE, json={"campaign": 2027}, headers=TECH).status_code == 409
    r = client.put(f"{BASE}/{plan['id']}/sheets", headers=FARMER,
                   json={"row_version": plan["row_version"] + 5, "sheets": [SHEET]})
    assert r.status_code == 409


def test_overrides_through_their_own_endpoint(client):
    plan = _with_sheet(client)
    pid = plan["id"]
    url = f"{BASE}/{pid}/sheets/wheat/overrides/soil.ph"
    r = client.put(url, json={"row_version": plan["row_version"], "value": 7.2,
                              "reason": "lab sheet"}, headers=TECH)
    assert r.status_code == 200
    override = r.json()["sheets"][0]["overrides"][0]
    assert override["user"] == "u-tech" and override["reason"] == "lab sheet"
    r2 = client.put(url, json={"row_version": r.json()["row_version"], "value": 7.0,
                               "reason": "x"}, headers=FARMER)
    assert r2.status_code == 403
    r3 = client.delete(f"{url}?row_version={r.json()['row_version']}", headers=TECH)
    assert r3.status_code == 200 and r3.json()["sheets"][0]["overrides"] == []


@pytest.mark.parametrize("change", [
    {"overrides": [{"param": "soil.ph", "value": 7.2, "reason": "x"}]},
    {"parcel_ids": [URN, URN]},
    {"sigpac": {"urn:ngsi-ld:AgriParcel:other": "31201A00100123"}},
    {"sigpac": {URN: "CATAST_Pol_ParcelaRusti.344737"}},
    {"key": "Not A Key"},
    {"campaign": 2026},
    {"applications": [{"stage": "pre_plant", "kind": "organic", "organic_index": 0,
                       "product_name": "slurry", "method": "band", "machine": "tanker"}]},
])
def test_invalid_sheets_are_rejected(client, change):
    plan = _new(client)
    r = client.put(f"{BASE}/{plan['id']}/sheets", headers=FARMER,
                   json={"row_version": plan["row_version"], "sheets": [SHEET | change]})
    assert r.status_code == 422, r.text


def test_duplicate_sheet_keys_are_rejected(client):
    plan = _new(client)
    r = client.put(f"{BASE}/{plan['id']}/sheets", headers=FARMER,
                   json={"row_version": plan["row_version"], "sheets": [SHEET, SHEET]})
    assert r.status_code == 422


def test_a_failing_source_is_a_503_and_changes_nothing(client, data):
    plan = _with_sheet(client)
    data["fail"] = {"lab_analyses": SourceUnavailable("soil", "answered 500")}
    r = client.post(f"{BASE}/{plan['id']}/calculate", json={"row_version": plan["row_version"]},
                    headers=FARMER)
    assert r.status_code == 503 and r.json()["source"] == "soil"
    after = client.get(f"{BASE}/{plan['id']}", headers=FARMER).json()
    assert after["state"] == "draft" and after["row_version"] == plan["row_version"]


def test_transition_errors_map_to_http(client):
    plan = _with_sheet(client)
    r = client.post(f"{BASE}/{plan['id']}/submit", json={"row_version": plan["row_version"]},
                    headers=FARMER)
    assert r.status_code == 409 and r.json()["error"] == "not_allowed"
    r = client.post(f"{BASE}/{plan['id']}/return", json={"row_version": plan["row_version"],
                                                         "comment": "x"}, headers=FARMER)
    assert r.status_code == 409 and r.json()["error"] == "not_allowed"
    r = client.put(f"{BASE}/{plan['id']}/sheets/wheat/overrides/irrigation.uptake", headers=FARMER,
                   json={"row_version": plan["row_version"], "value": 0.5, "reason": "x"})
    assert r.status_code == 403 and r.json()["error"] == "forbidden"


def test_rain_normal_endpoint(client):
    plan = _with_sheet(client)
    r = client.post(f"{BASE}/{plan['id']}/rain-normal", headers=FARMER)
    assert r.status_code == 200 and r.json()["rain_normal"]["parcel"] == URN


def test_list_filters_by_campaign(client):
    plan = _new(client)
    assert [p["id"] for p in client.get(f"{BASE}?campaign=2027", headers=FARMER).json()] == [
        plan["id"]]
    assert client.get(f"{BASE}?campaign=2026", headers=FARMER).json() == []
