import asyncio
import json
import uuid
from contextlib import asynccontextmanager

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.api import get_sources_factory
from app.config import get_settings
from app.main import app
from tests.conftest import _truncate
from tests.fakes import URN, FakeSources, complete_data

FARMER = {"X-Tenant-ID": "tenant-a", "X-User-ID": "u-farmer", "X-User-Roles": "Farmer"}
TECH = {"X-Tenant-ID": "tenant-a", "X-User-ID": "u-tech", "X-User-Roles": "TechnicalConsultant"}
BASE = "/api/fast"
SECRET = "test-internal-secret"
APP = {"stage": "pre_plant", "kind": "mineral", "product_name": "NPK 10-5-5", "n_pct": 10,
       "p2o5_pct": 5, "k2o_pct": 5, "n_form": "ammoniacal", "product_rate_kg_ha": 100,
       "method": "broadcast", "machine": "spreader"}
SHEET = {"key": "wheat", "campaign": 2027, "parcel_ids": [URN], "tillage": True,
         "irrigated": False, "rotation_years": 4, "nuts": "ES22",
         "sigpac": {URN: "31201A00100123"}, "applications": [APP]}


@pytest.fixture
def client(pg_url, monkeypatch):
    monkeypatch.setenv("POSTGRES_URL", pg_url)
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", SECRET)
    get_settings.cache_clear()
    data = complete_data()      # 10 ha of rainfed wheat: exempt from advice on any date

    @asynccontextmanager
    async def factory(tenant_id):
        yield FakeSources(**data)

    app.dependency_overrides[get_sources_factory] = lambda: factory
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    asyncio.run(_truncate(pg_url))


def store_rain(pg_url: str, plan_id: str) -> None:
    """The fake sources have no daily weather: store a rain normal straight into the plan."""
    async def go():
        conn = await asyncpg.connect(pg_url)
        try:
            await conn.execute("UPDATE fast.plans SET rain = $2::jsonb WHERE id = $1",
                               uuid.UUID(plan_id),
                               json.dumps({"annual_mm": 600.0, "years": [2016]}))
        finally:
            await conn.close()

    asyncio.run(go())


def _calculated(client, pg_url, sheet=SHEET):
    plan = client.post(f"{BASE}/plans", json={"campaign": 2027}, headers=FARMER).json()
    pid = plan["id"]
    plan = client.put(f"{BASE}/plans/{pid}/sheets", headers=FARMER,
                      json={"row_version": plan["row_version"], "sheets": [sheet]}).json()
    store_rain(pg_url, pid)
    plan = client.get(f"{BASE}/plans/{pid}", headers=FARMER).json()
    plan = client.post(f"{BASE}/plans/{pid}/calculate", json={"row_version": plan["row_version"]},
                       headers=FARMER).json()
    return pid, plan


def test_advisor_profile(client):
    assert client.get(f"{BASE}/advisors/me", headers=TECH).status_code == 404
    r = client.put(f"{BASE}/advisors/me", json={"name": "Ana", "registration_number": "NA-1"},
                   headers=TECH)
    assert r.status_code == 200 and r.json() == {"name": "Ana", "registration_number": "NA-1"}
    assert client.get(f"{BASE}/advisors/me", headers=FARMER).status_code == 403
    assert client.put(f"{BASE}/advisors/me", json={"name": "", "registration_number": "x"},
                      headers=TECH).status_code == 422


def test_sign_then_revise(client, pg_url):
    pid, plan = _calculated(client, pg_url)
    plan = client.post(f"{BASE}/plans/{pid}/submit", json={"row_version": plan["row_version"]},
                       headers=FARMER).json()
    client.put(f"{BASE}/advisors/me", json={"name": "Ana", "registration_number": "NA-1"},
               headers=TECH)
    r = client.post(f"{BASE}/plans/{pid}/sign", json={"row_version": plan["row_version"]},
                    headers=TECH)
    assert r.status_code == 200, r.text
    signed = r.json()
    assert signed["state"] == "signed" and len(signed["snapshot_sha256"]) == 64
    r = client.post(f"{BASE}/plans/{pid}/revise", json={"row_version": signed["row_version"]},
                    headers=FARMER)
    assert r.status_code == 201 and r.json()["version"] == 2


def test_close_by_the_holder_and_the_internal_summary(client, pg_url):
    pid, plan = _calculated(client, pg_url)
    r = client.post(f"{BASE}/plans/{pid}/close", headers=FARMER,
                    json={"row_version": plan["row_version"],
                          "closure_basis": "titular_sin_obligacion", "signer_name": "Juan"})
    assert r.status_code == 200, r.text
    url = f"{BASE}/internal/plans/summary"
    params = {"tenant_id": "tenant-a", "parcel_id": URN, "campaign": 2027}
    assert client.get(url, params=params).status_code == 401
    s = client.get(url, params=params, headers={"X-Internal-Service-Secret": SECRET})
    assert s.status_code == 200 and s.json()["plan_id"] == pid
    missing = client.get(url, params={**params, "campaign": 2026},
                         headers={"X-Internal-Service-Secret": SECRET})
    assert missing.status_code == 404


def test_close_refused_by_a_technician_and_with_a_bad_basis(client, pg_url):
    pid, plan = _calculated(client, pg_url)
    body = {"row_version": plan["row_version"], "closure_basis": "titular_sin_obligacion",
            "signer_name": "Juan"}
    assert client.post(f"{BASE}/plans/{pid}/close", json=body, headers=TECH).status_code == 403
    bad = {**body, "closure_basis": "nope"}
    assert client.post(f"{BASE}/plans/{pid}/close", json=bad, headers=FARMER).status_code == 422


def test_declarations(client, pg_url):
    pid, plan = _calculated(client, pg_url)
    r = client.put(f"{BASE}/plans/{pid}/declarations", headers=FARMER,
                   json={"row_version": plan["row_version"], "vulnerable_zone": False,
                         "vulnerable_zone_source": "regional order",
                         "voluntary_digital_notebook": True})
    assert r.status_code == 200 and r.json()["declarations"]["voluntary_digital_notebook"] is True
    assert r.json()["state"] == "draft"


def test_signing_with_a_blocking_finding_is_a_409(client, pg_url):
    pid, plan = _calculated(client, pg_url, {**SHEET, "applications": []})
    plan = client.post(f"{BASE}/plans/{pid}/submit", json={"row_version": plan["row_version"]},
                       headers=FARMER).json()
    client.put(f"{BASE}/advisors/me", json={"name": "Ana", "registration_number": "NA-1"},
               headers=TECH)
    r = client.post(f"{BASE}/plans/{pid}/sign", json={"row_version": plan["row_version"]},
                    headers=TECH)
    assert r.status_code == 409 and r.json()["error"] == "blocking_findings"
    assert "ES-RD1051-6.4-content" in r.json()["detail"]
