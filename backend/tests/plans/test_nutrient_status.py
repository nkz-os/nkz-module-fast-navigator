import asyncio
import json
import uuid

import asyncpg

from tests.fakes import URN
from tests.plans import test_api_signing as signing
from tests.plans.test_api_signing import BASE, HOLDER, SECRET, SHEET, _calculated

client = signing.client  # the Postgres-backed app fixture, shared

AUTH = {"X-Internal-Service-Secret": SECRET}
URL = f"{BASE}/internal/parcels/{URN}/nutrient-status"
PARAMS = {"tenant_id": "tenant-a", "campaign": 2027}


def _sql(pg_url, query, *args, fetch=False):
    async def go():
        conn = await asyncpg.connect(pg_url)
        try:
            return await (conn.fetch if fetch else conn.execute)(query, *args)
        finally:
            await conn.close()

    return asyncio.run(go())


def _stored_results(pg_url, plan_id) -> list[dict]:
    rows = _sql(pg_url, "SELECT r.result FROM fast.results r JOIN fast.crop_sheets s "
                "ON s.id = r.sheet_id WHERE s.plan_id = $1 ORDER BY s.seq",
                uuid.UUID(plan_id), fetch=True)
    return [json.loads(r["result"]) if isinstance(r["result"], str) else r["result"]
            for r in rows]


def _close(client, plan):
    r = client.post(f"{BASE}/plans/{plan['id']}/close", headers=HOLDER,
                    json={"row_version": plan["row_version"],
                          "closure_basis": "titular_sin_obligacion", "signer_name": "Juan"})
    assert r.status_code == 200, r.text
    return r.json()


def _get(client, params=PARAMS, url=URL):
    return client.get(url, params=params, headers=AUTH)


def test_auth_required(client):
    assert client.get(URL, params=PARAMS).status_code == 401
    bad = client.get(URL, params=PARAMS, headers={"X-Internal-Service-Secret": "nope"})
    assert bad.status_code == 401


def test_no_plan_is_200_with_plan_null(client):
    r = _get(client)
    assert r.status_code == 200
    body = r.json()
    assert body["plan"] is None and body["sheets"] == []
    assert body["parcel_id"] == URN and body["campaign"] == 2027
    assert body["units"]["p2o5"] == "kg P2O5/ha"


def test_bare_parcel_id_is_accepted(client):
    r = _get(client, url=f"{BASE}/internal/parcels/p1/nutrient-status")
    assert r.status_code == 200 and r.json()["parcel_id"] == URN


def test_calculated_fresh_plan_returns_stored_figures(client, pg_url):
    pid, _ = _calculated(client, pg_url)
    body = _get(client).json()
    assert body["plan"]["id"] == pid and body["plan"]["state"] == "calculated"
    assert body["plan"]["calc_fresh"] is True and body["plan"]["signed_at"] is None
    (sheet,) = body["sheets"]
    (stored,) = _stored_results(pg_url, pid)
    assert sheet["n_kg_ha"] == {"min": stored["n"]["min_kg_ha"], "avg": stored["n"]["avg_kg_ha"],
                                "max": stored["n"]["max_kg_ha"]}
    assert sheet["p2o5_kg_ha"] == stored["p2o5"]["rate_kg_ha"]
    assert sheet["k2o_kg_ha"] == stored["k2o"]["rate_kg_ha"]
    assert sheet["soil"]["p_threshold_mg_kg"] == stored["p2o5"]["threshold_mg_kg"]
    assert sheet["soil"]["k_threshold_mg_kg"] == stored["k2o"]["threshold_mg_kg"]
    assert sheet["soil"]["p_olsen_mg_kg"]["value"] == stored["inputs"]["soil.p_olsen_mg_kg"]["value"]
    assert sheet["status"] == stored["status"] and sheet["provisional"] == stored["provisional"]
    assert sheet["crop_eppo"] == stored["inputs"]["crop.eppo"]["value"]
    assert body["versions"]["engine"] == stored["versions"]["engine"]


def test_signed_plan_matches_stored_results_exactly(client, pg_url):
    pid, plan = _calculated(client, pg_url)
    _close(client, plan)
    body = _get(client).json()
    assert body["plan"]["state"] == "signed" and body["plan"]["signed_at"]
    (stored,) = _stored_results(pg_url, pid)
    (sheet,) = body["sheets"]
    assert json.dumps(sheet["n_kg_ha"]["avg"]) == json.dumps(stored["n"]["avg_kg_ha"])
    assert json.dumps(sheet["p2o5_kg_ha"]) == json.dumps(stored["p2o5"]["rate_kg_ha"])
    assert json.dumps(sheet["k2o_kg_ha"]) == json.dumps(stored["k2o"]["rate_kg_ha"])


def test_stale_calculation_returns_result_null(client, pg_url):
    pid, _ = _calculated(client, pg_url)
    _sql(pg_url, "UPDATE fast.plans SET inputs_changed_at = clock_timestamp() + interval '1 minute' "
         "WHERE id = $1", uuid.UUID(pid))
    body = _get(client).json()
    assert body["plan"]["id"] == pid and body["plan"]["calc_fresh"] is False
    (sheet,) = body["sheets"]
    assert sheet["result"] is None and sheet["n_kg_ha"] is None and sheet["p2o5_kg_ha"] is None


def test_draft_returns_result_null(client):
    plan = client.post(f"{BASE}/plans", json={"campaign": 2027}, headers=HOLDER).json()
    client.put(f"{BASE}/plans/{plan['id']}/sheets", headers=HOLDER,
               json={"row_version": plan["row_version"], "sheets": [SHEET]})
    body = _get(client).json()
    assert body["plan"]["state"] == "draft"
    assert [s["result"] for s in body["sheets"]] == [None]


def test_signed_wins_over_a_newer_open_plan(client, pg_url):
    open_id, _ = _calculated(client, pg_url)
    _sql(pg_url, "UPDATE fast.plans SET farm = 'farm-x' WHERE id = $1", uuid.UUID(open_id))
    signed_id, plan = _calculated(client, pg_url)
    _close(client, plan)
    _sql(pg_url, "UPDATE fast.plans SET updated_at = now() + interval '1 hour' WHERE id = $1",
         uuid.UUID(open_id))
    body = _get(client).json()
    assert body["plan"]["id"] == signed_id and body["plan"]["state"] == "signed"


def test_other_parcel_and_other_campaign_have_no_plan(client, pg_url):
    _calculated(client, pg_url)
    other = _get(client, url=f"{BASE}/internal/parcels/urn:ngsi-ld:AgriParcel:p2/nutrient-status")
    assert other.json()["plan"] is None
    assert _get(client, {**PARAMS, "campaign": 2026}).json()["plan"] is None


def test_tenant_isolation(client, pg_url):
    _calculated(client, pg_url)
    assert _get(client).json()["plan"] is not None
    assert _get(client, {**PARAMS, "tenant_id": "tenant-b"}).json()["plan"] is None


def test_read_only_no_state_change(client, pg_url):
    pid, _ = _calculated(client, pg_url)
    q = "SELECT row_version, calculated_at, updated_at FROM fast.plans WHERE id = $1"
    before = _sql(pg_url, q, uuid.UUID(pid), fetch=True)
    _get(client)
    assert _sql(pg_url, q, uuid.UUID(pid), fetch=True) == before


def test_parameters_validated(client):
    assert client.get(URL, params={"tenant_id": "tenant-a"}, headers=AUTH).status_code == 422
    assert client.get(URL, params={"campaign": 2027}, headers=AUTH).status_code == 422
    assert client.get(URL, params={**PARAMS, "campaign": 1999}, headers=AUTH).status_code == 422
