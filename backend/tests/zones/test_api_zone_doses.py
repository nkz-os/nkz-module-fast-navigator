import asyncio
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from app.api import get_sources_factory
from app.config import get_settings
from app.main import app
from app.plans.clock import legal_today
from app.sources.errors import SourceUnavailable
from tests.fakes import URN, FakeSources, complete_data
from tests.zones.test_read import kv, normalized

HOLDER = {"X-Tenant-ID": "tenant-a", "X-User-ID": "u-holder", "X-User-Roles": "TenantAdmin"}
FIELD = {"X-Tenant-ID": "tenant-a", "X-User-ID": "u-field", "X-User-Roles": "Farmer"}
OTHER = {"X-Tenant-ID": "tenant-b", "X-User-ID": "u-b", "X-User-Roles": "TenantAdmin"}
BASE = "/api/fast/plans"
RUN = "run-ndvi"
FERT = {"stage": "pre_plant", "kind": "mineral", "product_name": "Nitrate 20", "n_pct": 20,
        "n_form": "nitric", "product_rate_kg_ha": 300, "method": "broadcast", "machine": "spreader"}
NO_N = {**FERT, "product_name": "Superphosphate", "n_pct": 0, "n_form": None, "p2o5_pct": 18}
SHEET = {"key": "wheat", "campaign": 2027, "parcel_ids": [URN], "tillage": True,
         "irrigated": False, "rotation_years": 4, "applications": [FERT, NO_N]}


def zone_set(values, area=2.5, run=RUN, **extra):
    """Zone entities of the parcel (keyValues) with the given vegetation means."""
    out = []
    for i, v in enumerate(values):
        e = kv(i, run=run, parcel=URN, areaHa=area, **extra)
        e["id"] = f"urn:ngsi-ld:AgriManagementZone:p1:Z{i}"
        e["dateZoned"] = legal_today().isoformat() + "T05:00:00Z"
        if v is None:
            del e["meanValue"]
        else:
            e["meanValue"] = v
        out.append(e)
    return out


@pytest.fixture
def data():
    d = complete_data()
    d["zones"] = {URN: zone_set([0.4, 0.6, 0.5, 0.5])}
    return d


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
    from tests.conftest import _truncate
    asyncio.run(_truncate(pg_url))


def calculated_plan(client, sheet=SHEET, calculate=True):
    plan = client.post(BASE, json={"campaign": 2027}, headers=HOLDER).json()
    r = client.put(f"{BASE}/{plan['id']}/sheets", headers=HOLDER,
                   json={"row_version": plan["row_version"], "sheets": [sheet]})
    assert r.status_code == 200, r.text
    plan = r.json()
    if calculate:
        r = client.post(f"{BASE}/{plan['id']}/calculate", headers=HOLDER,
                        json={"row_version": plan["row_version"]})
        assert r.status_code == 200, r.text
        plan = r.json()
    return plan


def ask(client, plan, *, headers=HOLDER, key="wheat", **body):
    body = {"parcel_urn": URN, "zoning_run_id": RUN, "target": {"n_kg_ha": 60.0}, **body}
    return client.post(f"{BASE}/{plan['id']}/sheets/{key}/zone-doses", headers=headers, json=body)


def doses(res):
    return [z["n_kg_ha"] for z in res["zones"]]


def test_uniform_is_the_default_and_carries_the_whole_response(client):
    plan = calculated_plan(client)
    r = ask(client, plan, target={"n_kg_ha": 60.0, "product": {"name": "Nitrate 27", "n_pct": 27}})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["strategy"] == "uniform" and res["strategy_unavailable"] is None
    assert res["plan"] == {"id": plan["id"], "state": "calculated", "campaign": 2027}
    assert res["sheet"]["key"] == "wheat" and set(res["sheet"]["n_kg_ha"]) == {"min", "avg", "max"}
    assert res["sheet"]["crop"] == {"eppo": "TRZAX", "n_fixing": False}
    assert res["zoning"] == {"run_id": RUN, "method": "vegetationIndex", "variable": "NDVI",
                             "date": legal_today().isoformat(), "zone_count": 4}
    assert res["target"] == {"n_kg_ha": 60.0, "source": "given",
                             "product": {"name": "Nitrate 27", "n_pct": 27.0}}
    assert res["cap"] == {"pct": 20.0, "min_n_kg_ha": 48.0, "max_n_kg_ha": 72.0}
    assert doses(res) == [60.0] * 4
    assert {z["product_kg_ha"] for z in res["zones"]} == {222.22}
    assert {z["basis"] for z in res["zones"]} == {"sheet"}
    assert [z["rank"] for z in res["zones"]] == [1, 2, 3, 4]
    assert res["rest"] == {"area_ha": 0.0, "n_kg_ha": 60.0, "product_kg_ha": 222.22}
    assert res["totals"] == {"area_ha": 10.0, "n_kg": 600.0, "mean_n_kg_ha": 60.0,
                             "uniform_n_kg": 600.0}
    assert res["notices"] == [] and res["units"] == {"n": "kg N/ha", "product": "kg/ha"}
    assert res["versions"]["zone_doses"] == "1.0.0" and "calc" in res["versions"]


def test_potential_and_compensate_share_the_dose_and_keep_the_mean(client):
    plan = calculated_plan(client)
    # means 0.4, 0.6, 0.5, 0.5: mean 0.5, relative vigors 0.8, 1.2, 1, 1
    res = ask(client, plan, strategy="potential").json()
    assert res["strategy_unavailable"] is None
    assert doses(res) == [48.0, 72.0, 60.0, 60.0]
    assert [z["relative_vigor"] for z in res["zones"]] == [0.8, 1.2, 1.0, 1.0]
    assert [z["basis"] for z in res["zones"]] == ["vigor"] * 4
    assert res["totals"]["mean_n_kg_ha"] == 60.0 and res["totals"]["n_kg"] == 600.0
    res = ask(client, plan, strategy="compensate").json()
    assert doses(res) == [72.0, 48.0, 60.0, 60.0]
    assert [z["factor"] for z in res["zones"]] == [1.2, 0.8, 1.0, 1.0]


def test_the_cap_is_applied_and_reported_in_kg(client, data):
    data["zones"][URN] = zone_set([0.75, 0.45, 0.4, 0.4])      # relative vigors 1.5, .9, .8, .8
    plan = calculated_plan(client)
    res = ask(client, plan, strategy="potential", cap_pct=20).json()
    assert [z["capped"] for z in res["zones"]] == [True, False, False, False]
    assert doses(res) == [72.0, 60.48, 53.76, 53.76]
    assert res["cap"]["min_n_kg_ha"] == 48.0 and res["cap"]["max_n_kg_ha"] == 72.0
    assert res["totals"]["mean_n_kg_ha"] == 60.0
    flat = ask(client, plan, strategy="potential", cap_pct=0).json()
    assert doses(flat) == [60.0] * 4 and flat["cap"]["min_n_kg_ha"] == 60.0


def test_an_application_of_the_plan_is_the_target(client):
    plan = calculated_plan(client)
    res = ask(client, plan, strategy="potential", target={"application_seq": 0}).json()
    assert res["target"] == {"n_kg_ha": 60.0, "source": "application",
                             "product": {"name": "Nitrate 20", "n_pct": 20.0}}
    assert doses(res) == [48.0, 72.0, 60.0, 60.0]
    assert [z["product_kg_ha"] for z in res["zones"]] == [240.0, 360.0, 300.0, 300.0]
    assert ask(client, plan, target={"application_seq": 2}).status_code == 422


def test_an_application_without_n_is_no_target(client):
    plan = calculated_plan(client)
    res = ask(client, plan, strategy="potential", target={"application_seq": 1}).json()
    assert res["strategy_unavailable"] == "no_target_n"
    assert res["target"]["n_kg_ha"] is None and doses(res) == [None] * 4
    assert res["totals"]["n_kg"] is None and res["cap"]["min_n_kg_ha"] is None


def test_a_manual_zoning_has_no_vegetation_value(client, data):
    manual = zone_set([None] * 3, run="man", zoningMethod="manual", area=10 / 3)
    for e in manual:
        e.pop("variableAttribute")
    data["zones"][URN] = manual
    plan = calculated_plan(client)
    res = ask(client, plan, strategy="potential", zoning_run_id="man").json()
    assert res["strategy_unavailable"] == "zoning_without_vegetation_value"
    assert res["zoning"]["method"] == "manual" and res["zoning"]["variable"] is None
    assert doses(res) == [60.0] * 3 and res["strategy"] == "potential"
    assert [z["missing"] for z in res["zones"]] == [["mean_value"]] * 3
    assert ask(client, plan, zoning_run_id="man").json()["zones"][0]["missing"] == []


def test_a_single_zone_cannot_be_shared(client, data):
    data["zones"][URN] = zone_set([0.5], area=10.0)
    res = ask(client, calculated_plan(client), strategy="compensate").json()
    assert res["strategy_unavailable"] == "single_zone" and doses(res) == [60.0]


def test_a_nitrogen_fixing_crop_gets_no_variable_dose(client, data):
    data["coefficients"]["TRZAX"]["n_fixing"] = True
    plan = calculated_plan(client)
    res = ask(client, plan, strategy="potential").json()
    assert res["strategy_unavailable"] == "n_fixing_crop" and doses(res) == [60.0] * 4
    assert res["sheet"]["crop"]["n_fixing"] is True


def test_a_zone_without_value_takes_the_target_and_is_reported(client, data):
    data["zones"][URN] = zone_set([0.4, 0.6, None, 0.5], area=2.5)
    res = ask(client, calculated_plan(client), strategy="potential").json()
    assert res["strategy_unavailable"] is None
    z = res["zones"]
    assert z[2]["basis"] == "sheet" and z[2]["factor"] is None and z[2]["relative_vigor"] is None
    assert z[2]["missing"] == ["mean_value"] and z[2]["n_kg_ha"] == 60.0
    assert [x["basis"] for x in (z[0], z[1], z[3])] == ["vigor"] * 3
    assert res["totals"]["mean_n_kg_ha"] == 60.0


def test_a_zone_without_area_makes_the_strategy_unavailable(client, data):
    data["zones"][URN][1].pop("areaHa")
    res = ask(client, calculated_plan(client), strategy="potential").json()
    assert res["strategy_unavailable"] == "zone_without_area"
    assert res["zones"][1]["area_ha"] is None and res["zones"][1]["missing"] == ["area_ha"]
    assert doses(res) == [60.0] * 4
    assert res["totals"] == {"area_ha": None, "n_kg": None, "mean_n_kg_ha": None,
                             "uniform_n_kg": None}


def test_zones_that_do_not_cover_the_parcel_leave_a_rest_at_the_target(client, data):
    data["zones"][URN] = zone_set([0.4, 0.6, 0.5], area=2.5)       # 7.5 ha of the parcel's 10
    res = ask(client, calculated_plan(client), strategy="potential").json()
    assert res["rest"]["area_ha"] == 2.5 and res["rest"]["n_kg_ha"] == 60.0
    assert res["totals"]["area_ha"] == 10.0
    assert [n["code"] for n in res["notices"]] == ["zones_do_not_cover_parcel"]


def test_an_old_image_is_a_notice_only_when_the_vigor_is_used(client, data):
    for e in data["zones"][URN]:
        e["dateZoned"] = "2020-01-01T05:00:00Z"
    plan = calculated_plan(client)
    res = ask(client, plan, strategy="potential").json()
    assert [n["code"] for n in res["notices"]] == ["zoning_image_old"]
    assert ask(client, plan, strategy="uniform").json()["notices"] == []


def test_the_link_and_the_attributes_may_arrive_in_the_other_spelling(client, data):
    zs = [normalized(i, run=RUN, link="refAgriParcel", parcel=URN, prefix="nkz:")
          for i in range(2)]
    for i, (z, v) in enumerate(zip(zs, (0.4, 0.6))):
        z["id"] = f"urn:ngsi-ld:AgriManagementZone:p1:Z{i}"
        z["nkz:meanValue"]["value"] = v
        z["nkz:areaHa"]["value"] = 5.0
    data["zones"][URN] = zs
    res = ask(client, calculated_plan(client), strategy="potential", cap_pct=30).json()
    assert res["zoning"]["date"] == "2026-10-01" and doses(res) == [48.0, 72.0]


def test_an_uncalculated_sheet_is_a_422(client):
    plan = calculated_plan(client, calculate=False)
    r = ask(client, plan)
    assert r.status_code == 422 and "calculate the plan" in r.json()["detail"]


def test_a_stale_calculation_is_flagged_not_refused(client):
    plan = calculated_plan(client)
    r = client.put(f"{BASE}/{plan['id']}/sheets", headers=HOLDER, json={
        "row_version": plan["row_version"], "sheets": [{**SHEET, "irrigated": True}]})
    assert r.status_code == 200
    res = ask(client, plan).json()
    assert [n["code"] for n in res["notices"]] == ["plan_calculation_stale"]


def test_another_tenant_cannot_read_the_plan(client):
    plan = calculated_plan(client)
    assert ask(client, plan, headers=OTHER).status_code == 404


def test_a_farmer_can_read_but_no_role_means_no_access(client):
    plan = calculated_plan(client)
    assert ask(client, plan, headers=FIELD).status_code == 200
    assert ask(client, plan, headers={"X-Tenant-ID": "tenant-a"}).status_code == 401
    assert ask(client, plan, headers={**HOLDER, "X-User-Roles": "Other"}).status_code == 403


def test_the_parcel_must_be_in_the_sheet_and_the_sheet_and_zoning_must_exist(client):
    plan = calculated_plan(client)
    r = ask(client, plan, parcel_urn="urn:ngsi-ld:AgriParcel:parcel-9")
    assert r.status_code == 422 and "not in sheet" in r.json()["detail"]
    assert ask(client, plan, key="barley").status_code == 404
    r = ask(client, plan, zoning_run_id="nope")
    assert r.status_code == 404 and "zoning" in r.json()["detail"]
    assert ask(client, plan, parcel_urn="p1").status_code == 200      # a bare id is accepted


def test_the_broker_failing_is_a_503_naming_it(client, monkeypatch):
    plan = calculated_plan(client)

    async def boom(self, urn):
        raise SourceUnavailable("broker", "unreachable (ConnectError)")

    monkeypatch.setattr(FakeSources, "zone_entities", boom)
    r = ask(client, plan, strategy="potential")
    assert r.status_code == 503 and r.json()["source"] == "broker"


@pytest.mark.parametrize("body", [
    {"target": {"n_kg_ha": 60, "application_seq": 0}},
    {"target": {}},
    {"target": {"application_seq": 0, "product": {"name": "x", "n_pct": 20}}},
    {"target": {"n_kg_ha": 0}},
    {"target": {"n_kg_ha": 60, "product": {"name": "x", "n_pct": 0}}},
    {"cap_pct": 31},
    {"cap_pct": -1},
    {"strategy": "random"},
    {"zoning_run_id": ""},
    {"unknown": 1},
])
def test_invalid_bodies_are_422(client, body):
    plan = calculated_plan(client)
    assert ask(client, plan, **body).status_code == 422


def zonings(client, plan, *, headers=HOLDER, key="wheat", parcel=URN):
    return client.get(f"{BASE}/{plan['id']}/sheets/{key}/zonings", headers=headers,
                      params={"parcel_urn": parcel})


def test_the_zonings_of_a_parcel_are_listed_most_recent_first(client, data):
    old = zone_set([0.4, 0.6], run="old", area=5.0)
    for e in old:
        e["dateZoned"] = "2026-01-05T05:00:00Z"
    manual = zone_set([None] * 3, run="man", zoningMethod="manual", area=3.0)
    for e in manual:
        e.pop("variableAttribute")
        e["dateZoned"] = "2026-03-01T05:00:00Z"
    for group in (old, manual):
        for e in group:
            e["id"] = e["id"].replace(":p1:", f":{e['zoningRunId']}:")
    data["zones"][URN] = old + manual + zone_set([0.4, 0.6, 0.5, 0.5])
    r = zonings(client, calculated_plan(client))
    assert r.status_code == 200, r.text
    got = r.json()["zonings"]
    assert [z["run_id"] for z in got] == [RUN, "man", "old"]
    assert got[0] == {"run_id": RUN, "method": "vegetationIndex", "variable": "NDVI",
                      "date": legal_today().isoformat(), "zone_count": 4,
                      "has_vegetation_value": True}
    assert got[1]["method"] == "manual" and got[1]["variable"] is None
    assert got[1]["has_vegetation_value"] is False and got[1]["zone_count"] == 3
    assert got[2]["date"] == "2026-01-05"


def test_a_parcel_without_zonings_gets_an_empty_list(client, data):
    data["zones"][URN] = []
    r = zonings(client, calculated_plan(client))
    assert r.status_code == 200 and r.json() == {"zonings": []}


def test_zonings_need_no_calculation(client):
    r = zonings(client, calculated_plan(client, calculate=False))
    assert r.status_code == 200 and len(r.json()["zonings"]) == 1


def test_zonings_of_another_tenant_are_a_404(client):
    plan = calculated_plan(client)
    assert zonings(client, plan, headers=OTHER).status_code == 404


def test_zonings_roles_follow_zone_doses(client):
    plan = calculated_plan(client)
    assert zonings(client, plan, headers=FIELD).status_code == 200
    assert zonings(client, plan, headers={"X-Tenant-ID": "tenant-a"}).status_code == 401
    assert zonings(client, plan, headers={**HOLDER, "X-User-Roles": "Other"}).status_code == 403


def test_zonings_parcel_must_be_in_the_sheet_and_the_sheet_must_exist(client):
    plan = calculated_plan(client)
    r = zonings(client, plan, parcel="urn:ngsi-ld:AgriParcel:parcel-9")
    assert r.status_code == 422 and "not in sheet" in r.json()["detail"]
    assert zonings(client, plan, key="barley").status_code == 404
    assert zonings(client, plan, parcel="p1").status_code == 200
    r = client.get(f"{BASE}/{plan['id']}/sheets/wheat/zonings", headers=HOLDER)
    assert r.status_code == 422


def test_zonings_broker_failing_is_a_503_naming_it(client, monkeypatch):
    plan = calculated_plan(client)

    async def boom(self, urn):
        raise SourceUnavailable("broker", "unreachable (ConnectError)")

    monkeypatch.setattr(FakeSources, "zone_entities", boom)
    r = zonings(client, plan)
    assert r.status_code == 503 and r.json()["source"] == "broker"
