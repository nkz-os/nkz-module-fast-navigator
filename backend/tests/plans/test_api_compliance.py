import asyncio
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from app.api import get_sources_factory
from app.config import get_settings
from app.main import app
from app.sources.errors import SourceUnavailable
from tests.conftest import _truncate
from tests.fakes import URN, FakeSources, complete_data
from tests.plans.test_api_signing import BASE, HOLDER, SECRET, _calculated

OP = {"id": "urn:ngsi-ld:AgriParcelOperation:op1", "type": "AgriParcelOperation",
      "operationType": "fertilization", "status": "completed", "fertilizerType": "NAC 27",
      "fertilizerRate": 200, "nitrogenContent": 27, "phosphorusPentoxideContent": 0,
      "potassiumOxideContent": 0, "nitrogenForm": "ammoniacal", "hasAgriParcel": URN,
      "endedAt": {"@type": "DateTime", "@value": "2027-02-10T08:00:00Z"}}


def _client(pg_url, monkeypatch):
    monkeypatch.setenv("POSTGRES_URL", pg_url)
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", SECRET)
    get_settings.cache_clear()
    data = complete_data()
    data["fertilizations"] = {URN: [OP]}

    @asynccontextmanager
    async def factory(tenant_id):
        yield FakeSources(**data)

    app.dependency_overrides[get_sources_factory] = lambda: factory
    return TestClient(app)


@pytest.fixture
def client_with_ops(pg_url, monkeypatch):
    with _client(pg_url, monkeypatch) as c:
        yield c
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    asyncio.run(_truncate(pg_url))


def test_compliance_route(client_with_ops, pg_url):
    pid, _plan = _calculated(client_with_ops, pg_url)
    r = client_with_ops.get(f"{BASE}/plans/{pid}/compliance", headers=HOLDER)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["campaign"] == 2027 and body["live"] is True
    (s,) = body["sheets"]
    assert s["realized"]["mineral_n_kg_ha"] > 0 and s["status"] in ("ok", "exceeded")


def test_compliance_is_tenant_scoped(client_with_ops, pg_url):
    pid, _ = _calculated(client_with_ops, pg_url)
    other = {"X-Tenant-ID": "tenant-b", "X-User-ID": "u", "X-User-Roles": "TenantAdmin"}
    assert client_with_ops.get(f"{BASE}/plans/{pid}/compliance", headers=other).status_code == 404


def test_compliance_of_a_signed_plan_reads_the_frozen_copy(client_with_ops, pg_url):
    pid, plan = _calculated(client_with_ops, pg_url)
    r = client_with_ops.post(f"{BASE}/plans/{pid}/close", headers=HOLDER, json={
        "row_version": plan["row_version"], "closure_basis": "titular_sin_obligacion",
        "signer_name": "Juan"})
    assert r.status_code == 200, r.text
    body = client_with_ops.get(f"{BASE}/plans/{pid}/compliance", headers=HOLDER).json()
    assert body["live"] is False
    (s,) = body["sheets"]
    assert s["realized"]["mineral_n_kg_ha"] > 0


def test_a_down_source_is_503(pg_url, monkeypatch):
    with _client(pg_url, monkeypatch) as c:
        pid, _ = _calculated(c, pg_url)
        down = FakeSources(**{**complete_data(), "fertilizations": {URN: [OP]},
                              "fail": {"fertilizations": SourceUnavailable("orion", "down")}})

        @asynccontextmanager
        async def factory(tenant_id):
            yield down

        app.dependency_overrides[get_sources_factory] = lambda: factory
        assert c.get(f"{BASE}/plans/{pid}/compliance", headers=HOLDER).status_code == 503
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    asyncio.run(_truncate(pg_url))


def test_pdf_route(client_with_ops, pg_url):
    pid, _ = _calculated(client_with_ops, pg_url)
    r = client_with_ops.get(f"{BASE}/plans/{pid}/pdf", headers=HOLDER)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    assert "fast-plan-2027-v1.pdf" in r.headers["content-disposition"]
    assert client_with_ops.get(f"{BASE}/plans/{pid}/pdf", params={"lang": "xx"},
                               headers=HOLDER).status_code == 422


def test_pdf_route_json_envelope(client_with_ops, pg_url):
    import base64
    pid, _ = _calculated(client_with_ops, pg_url)
    r = client_with_ops.get(f"{BASE}/plans/{pid}/pdf", params={"envelope": "json"},
                            headers=HOLDER)
    assert r.status_code == 200 and r.headers["content-type"] == "application/json"
    body = r.json()
    assert body["filename"] == "fast-plan-2027-v1.pdf" and body["media_type"] == "application/pdf"
    assert base64.b64decode(body["content_base64"]).startswith(b"%PDF")
    assert client_with_ops.get(f"{BASE}/plans/{pid}/pdf", params={"envelope": "xml"},
                               headers=HOLDER).status_code == 422


def test_pdf_route_concurrent_requests(client_with_ops, pg_url):
    from concurrent.futures import ThreadPoolExecutor
    pid, _ = _calculated(client_with_ops, pg_url)

    def get(_):
        return client_with_ops.get(f"{BASE}/plans/{pid}/pdf", headers=HOLDER)

    with ThreadPoolExecutor(2) as ex:
        results = list(ex.map(get, range(2)))
    assert all(r.status_code == 200 and r.content.startswith(b"%PDF") for r in results)
    from app.api import plans
    assert plans._PDF_LIMIT is not None
