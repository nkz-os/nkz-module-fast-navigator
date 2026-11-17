import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta

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
                             "date": legal_today().isoformat(),
                             "image_date": legal_today().isoformat(), "zone_count": 4}
    assert res["target"] == {"n_kg_ha": 60.0, "source": "given",
                             "product": {"name": "Nitrate 27", "n_pct": 27.0}}
    assert res["cap"] == {"pct": 20.0, "min_n_kg_ha": 48.0, "max_n_kg_ha": 72.0}
    assert doses(res) == [60.0] * 4
    assert {z["product_kg_ha"] for z in res["zones"]} == {222.22}
    assert {z["basis"] for z in res["zones"]} == {"sheet"}
    assert [z["rank"] for z in res["zones"]] == [1, 2, 3, 4]
    assert res["rest"] == {"area_ha": 0.0, "n_kg_ha": 60.0, "product_kg_ha": 222.22,
                           "p2o5_kg_ha": 50.3, "k2o_kg_ha": 83.76}
    assert res["totals"] == {"area_ha": 10.0, "n_kg": 600.0, "mean_n_kg_ha": 60.0,
                             "uniform_n_kg": 600.0}
    assert res["notices"] == [] and res["units"] == {
        "n": "kg N/ha", "product": "kg/ha", "p2o5": "kg P2O5/ha", "k2o": "kg K2O/ha"}
    assert res["versions"]["zone_doses"] == "1.1.0" and "calc" in res["versions"]


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
                      "date": legal_today().isoformat(),
                      "image_date": legal_today().isoformat(), "zone_count": 4,
                      "has_vegetation_value": True}
    assert got[1]["method"] == "manual" and got[1]["variable"] is None
    assert got[1]["has_vegetation_value"] is False and got[1]["zone_count"] == 3
    assert got[2]["date"] == "2026-01-05" and got[2]["image_date"] == "2026-01-05"
    assert got[1]["image_date"] == "2026-03-01"


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


def multidate_set(run="md", image_dates=("2026-04-02", "2026-05-20"), **extra):
    """A multi-date zoning: one zone per level, levels as in the frozen entity format."""
    out = zone_set([0.7, 0.5, 0.3, 0.1], run=run, zoningMethod="vegetationIndexMultiDate", **extra)
    for e, lvl in zip(out, ("high", "medium", "low", "critical")):
        e["zoneName"] = lvl
        e["zoneLevel"] = lvl
        if image_dates is not None:
            e["sourceDates"] = list(image_dates)
    return out


def test_a_multidate_zoning_carries_levels_and_the_newest_image_date(client, data):
    data["zones"][URN] = multidate_set(run="md")
    plan = calculated_plan(client)
    res = ask(client, plan, strategy="potential", zoning_run_id="md").json()
    assert [z["level"] for z in res["zones"]] == ["high", "medium", "low", "critical"]
    assert res["zoning"]["method"] == "vegetationIndexMultiDate"
    assert res["zoning"]["image_date"] == "2026-05-20"
    assert [n["code"] for n in res["notices"]] == ["zoning_image_old"]
    assert res["notices"][0]["params"]["date"] == "2026-05-20"
    got = zonings(client, plan).json()["zonings"]
    assert got[0]["image_date"] == "2026-05-20"


def test_the_multidate_notice_follows_the_image_date_not_the_zoning_date(client, data):
    data["zones"][URN] = multidate_set(run="md", image_dates=(legal_today().isoformat(),))
    for e in data["zones"][URN]:
        e["dateZoned"] = "2020-01-01T05:00:00Z"
    res = ask(client, calculated_plan(client), strategy="potential", zoning_run_id="md").json()
    assert res["zoning"]["date"] == "2020-01-01"
    assert res["zoning"]["image_date"] == legal_today().isoformat()
    assert res["notices"] == []


def test_vegetation_index_and_manual_keep_their_behaviour(client, data):
    res = ask(client, calculated_plan(client), strategy="potential").json()
    assert {z["level"] for z in res["zones"]} == {None}
    assert res["zoning"]["image_date"] == res["zoning"]["date"]


# ---- zone soil analyses -------------------------------------------------------------------

def zone_id(i):
    return f"urn:ngsi-ld:AgriManagementZone:p1:Z{i}"


SOIL_SHEET = {**SHEET, "soil_analysis_id": "a1", "nmin_analysis_id": "n1"}
NMIN_DATE = legal_today().isoformat()      # on the day of the zoning (samples must not be older)
LATER = (legal_today() + timedelta(days=1)).isoformat()


def nmin_analysis(id_, nitrate, ammonium, date=NMIN_DATE, **extra):
    h = {"depthFrom": 0, "depthTo": 30, "nitrateN": nitrate, "ammoniumN": ammonium,
         "bulkDensity": 1.0}
    return {"id": id_, "samplingDate": date, "horizons": [h], **extra}


def pk_analysis(id_, p, k, date=NMIN_DATE, **extra):
    h = {"depthFrom": 0, "depthTo": 30, "phosphorusAvailable": p, "phosphorusMethod": "olsen",
         "potassiumExchangeable": k, "potassiumMethod": "ammonium_acetate"}
    return {"id": id_, "samplingDate": date, "horizons": [h], **extra}


def with_analyses(data, *extra):
    data["analyses"][URN] = [*data["analyses"][URN], nmin_analysis("n1", 5.0, 5.0), *extra]


def test_without_zone_samples_the_response_is_what_it_was_plus_empty_soil_fields(client):
    plan = calculated_plan(client)
    res = ask(client, plan, strategy="potential").json()
    assert doses(res) == [48.0, 72.0, 60.0, 60.0] and res["notices"] == []
    assert [z["basis"] for z in res["zones"]] == ["vigor"] * 4
    assert {z["soil_analysis"] for z in res["zones"]} == {None}
    assert {z["nmin_kg_ha"] for z in res["zones"]} == {None}
    p2o5, k2o = res["rest"]["p2o5_kg_ha"], res["rest"]["k2o_kg_ha"]
    assert p2o5 is not None and k2o is not None
    assert {z["p2o5_kg_ha"] for z in res["zones"]} == {p2o5}
    assert {z["k2o_kg_ha"] for z in res["zones"]} == {k2o}
    assert res["units"] == {"n": "kg N/ha", "product": "kg/ha", "p2o5": "kg P2O5/ha",
                            "k2o": "kg K2O/ha"}
    assert res["cap"] == {"pct": 20.0, "min_n_kg_ha": 48.0, "max_n_kg_ha": 72.0}


def test_a_zone_nmin_replaces_the_parcel_one_in_that_zone_only(client, data):
    with_analyses(data, nmin_analysis("zn0", 8.0, 3.0, hasAgriManagementZone=zone_id(0)))
    plan = calculated_plan(client, SOIL_SHEET)
    res = ask(client, plan, strategy="potential").json()
    # parcel Nmin 27, zone 0 Nmin 29.7: share by vigor (48, 72, 60, 60), zone 0 credits 2.7 more
    assert doses(res) == [45.3, 72.0, 60.0, 60.0]
    assert [z["capped"] for z in res["zones"]] == [False] * 4      # clipped by the cap: none
    assert [z["outside_cap"] for z in res["zones"]] == [True, False, False, False]
    z0 = res["zones"][0]
    assert z0["nmin_kg_ha"] == 29.7 and z0["basis"] == "zone_soil"
    assert z0["soil_analysis"] == {"id": "zn0", "date": NMIN_DATE, "n_samples": 1,
                                   "p_date": None, "k_date": None}
    assert res["zones"][1]["nmin_kg_ha"] is None and res["zones"][1]["basis"] == "vigor"
    assert res["zones"][1]["soil_analysis"] is None
    assert res["cap"]["min_n_kg_ha"] == 48.0 and res["cap"]["max_n_kg_ha"] == 72.0
    codes = [n["code"] for n in res["notices"]]
    assert "zone_soil_missing" in codes
    missing = next(n for n in res["notices"] if n["code"] == "zone_soil_missing")
    assert len(missing["params"]["zones"]) == 3


def test_the_nmin_floor_is_zero(client, data):
    with_analyses(data, nmin_analysis("zn0", 80.0, 30.0, hasAgriManagementZone=zone_id(0)))
    res = ask(client, calculated_plan(client, SOIL_SHEET), strategy="potential").json()
    assert res["zones"][0]["n_kg_ha"] == 0.0
    floored = [n for n in res["notices"] if n["code"] == "zone_dose_floored"]
    assert floored == [{"code": "zone_dose_floored", "params": {"zone": zone_id(0)}}]


def test_uniform_subtracts_the_zone_nmin(client, data):
    with_analyses(data, nmin_analysis("zn1", 8.0, 3.0, hasAgriManagementZone=zone_id(1)))
    res = ask(client, calculated_plan(client, SOIL_SHEET)).json()
    assert res["strategy"] == "uniform"
    assert doses(res) == [60.0, 57.3, 60.0, 60.0]
    assert res["totals"]["n_kg"] == 2.5 * (60 + 57.3 + 60 + 60)


def test_a_zone_nmin_of_another_date_is_not_used(client, data):
    with_analyses(data, nmin_analysis("zn0", 8.0, 3.0, date=LATER,
                                      hasAgriManagementZone=zone_id(0)))
    res = ask(client, calculated_plan(client, SOIL_SHEET), strategy="potential").json()
    assert doses(res) == [48.0, 72.0, 60.0, 60.0]
    other = next(n for n in res["notices"] if n["code"] == "zone_nmin_other_date")
    assert other["params"]["date"] == LATER


def test_zone_p_and_k_rerun_the_sheet_with_the_zone_soil(client, data):
    with_analyses(data, pk_analysis("zp0", 4.0, 90.0, hasAgriManagementZone=zone_id(0)))
    res = ask(client, calculated_plan(client, SOIL_SHEET), strategy="potential").json()
    z = res["zones"]
    assert z[0]["p2o5_kg_ha"] > res["rest"]["p2o5_kg_ha"]
    assert z[0]["k2o_kg_ha"] > res["rest"]["k2o_kg_ha"]
    assert {x["p2o5_kg_ha"] for x in z[1:]} == {res["rest"]["p2o5_kg_ha"]}
    assert {x["k2o_kg_ha"] for x in z[1:]} == {res["rest"]["k2o_kg_ha"]}
    assert z[0]["basis"] == "zone_soil" and z[0]["nmin_kg_ha"] is None
    assert z[0]["soil_analysis"] == {"id": "zp0", "date": NMIN_DATE, "n_samples": 1,
                                     "p_date": NMIN_DATE, "k_date": NMIN_DATE}
    assert doses(res) == [48.0, 72.0, 60.0, 60.0]          # N untouched without zone Nmin


def test_the_assembly_and_the_analyses_are_fetched_once(client, data, monkeypatch):
    with_analyses(data, pk_analysis("zp0", 4.0, 90.0, hasAgriManagementZone=zone_id(0)))
    plan = calculated_plan(client, SOIL_SHEET)
    calls = []
    original = FakeSources.lab_analyses

    async def counting(self, urn):
        calls.append(urn)
        return await original(self, urn)

    monkeypatch.setattr(FakeSources, "lab_analyses", counting)
    assert ask(client, plan, strategy="potential").status_code == 200
    assert calls == [URN]


def test_an_analysis_outside_every_zone_is_reported(client, data):
    with_analyses(data, pk_analysis("far", 4.0, 90.0, location={"lat": 5.0, "lon": 5.0}),
                  pk_analysis("in0", 4.0, 90.0, location={"lat": 0.5, "lon": 0.5}))
    res = ask(client, calculated_plan(client, SOIL_SHEET), strategy="potential").json()
    out = next(n for n in res["notices"] if n["code"] == "zone_soil_outside")
    assert out["params"] == {"n": 1}
    assert [z["soil_analysis"]["id"] for z in res["zones"] if z["soil_analysis"]] == ["in0"]


def test_unlocated_parcel_analyses_are_not_reported_as_outside(client, data):
    with_analyses(data)
    res = ask(client, calculated_plan(client, SOIL_SHEET), strategy="potential").json()
    assert res["notices"] == []


def _unavailable_checks(res, plain):
    assert doses(res) == doses(plain) and res["zones"] == plain["zones"]
    assert res["rest"] == plain["rest"] and res["totals"] == plain["totals"]
    assert {z["soil_analysis"] for z in res["zones"]} == {None}
    assert [n["code"] for n in res["notices"]] == ["zone_soil_unavailable"]


def _soil_data(data):
    with_analyses(data, pk_analysis("zp0", 4.0, 90.0, hasAgriManagementZone=zone_id(0)),
                  nmin_analysis("zn1", 8.0, 3.0, hasAgriManagementZone=zone_id(1)))


def test_lab_analyses_failing_keeps_the_parcel_doses(client, data, monkeypatch):
    plan = calculated_plan(client, SOIL_SHEET)
    plain = ask(client, plan, strategy="potential").json()
    _soil_data(data)

    async def boom(self, urn):
        raise SourceUnavailable("soil", "unreachable (ConnectError)")

    monkeypatch.setattr(FakeSources, "lab_analyses", boom)
    _unavailable_checks(ask(client, plan, strategy="potential").json(), plain)


def test_lab_analyses_timing_out_keeps_the_parcel_doses(client, data, monkeypatch):
    plan = calculated_plan(client, SOIL_SHEET)
    plain = ask(client, plan, strategy="potential").json()

    async def slow(self, urn):
        raise TimeoutError

    monkeypatch.setattr(FakeSources, "lab_analyses", slow)
    _unavailable_checks(ask(client, plan, strategy="potential").json(), plain)


def test_the_assembly_failing_keeps_the_parcel_doses(client, data, monkeypatch):
    plan = calculated_plan(client, SOIL_SHEET)
    plain = ask(client, plan, strategy="potential").json()
    _soil_data(data)

    async def boom(self, eppo):
        raise SourceUnavailable("bioorch", "unreachable (ConnectError)")

    monkeypatch.setattr(FakeSources, "coefficients", boom)
    _unavailable_checks(ask(client, plan, strategy="potential").json(), plain)


def test_a_zone_calculation_failing_only_affects_that_zone(client, data, monkeypatch):
    with_analyses(data, pk_analysis("zp0", 4.0, 90.0, hasAgriManagementZone=zone_id(0)),
                  pk_analysis("zp1", 4.0, 90.0, hasAgriManagementZone=zone_id(1)))
    plan = calculated_plan(client, SOIL_SHEET)
    import app.zones.service as svc
    real = svc.calculate
    seen = []

    def flaky(a):
        seen.append(1)
        if len(seen) == 2:          # the first call is the parcel's own rerun
            raise ValueError("boom")
        return real(a)

    monkeypatch.setattr(svc, "calculate", flaky)
    res = ask(client, plan, strategy="potential").json()
    z = res["zones"]
    parcel = res["rest"]["p2o5_kg_ha"]
    assert z[0]["p2o5_kg_ha"] == parcel and z[0]["soil_analysis"] is None
    assert z[0]["basis"] == "vigor" and z[1]["basis"] == "zone_soil"
    assert z[1]["p2o5_kg_ha"] > parcel
    failed = [n for n in res["notices"] if n["code"] == "zone_soil_calc_failed"]
    assert failed == [{"code": "zone_soil_calc_failed", "params": {"zone": zone_id(0)}}]


def strip_soil(res):
    """The response without the additive zone-soil keys."""
    out = {k: v for k, v in res.items() if k not in ("units", "versions")}
    out["zones"] = [{k: v for k, v in z.items()
                     if k not in ("nmin_kg_ha", "p2o5_kg_ha", "k2o_kg_ha")} for z in res["zones"]]
    out["rest"] = {k: v for k, v in res["rest"].items() if k not in ("p2o5_kg_ha", "k2o_kg_ha")}
    return out


def test_the_sheets_own_located_analyses_are_not_zone_samples(client, data):
    plan = calculated_plan(client, SOIL_SHEET)
    plain = {s: ask(client, plan, strategy=s).json() for s in ("uniform", "potential")}
    inside = {"location": {"lat": 0.5, "lon": 0.5}}
    data["analyses"][URN] = [{**data["analyses"][URN][0], "samplingDate": NMIN_DATE, **inside},
                             nmin_analysis("n1", 5.0, 5.0, **inside)]
    for s_, before in plain.items():
        res = ask(client, plan, strategy=s_).json()
        assert res == before
        assert {z["basis"] for z in res["zones"]} <= {"sheet", "vigor"}
        assert {z["soil_analysis"] for z in res["zones"]} == {None}


def test_the_default_analysis_of_the_sheet_is_not_a_zone_sample_either(client, data):
    plan = calculated_plan(client)                 # no ids chosen: the newest is picked
    before = ask(client, plan, strategy="potential").json()
    data["analyses"][URN][0].update(location={"lat": 0.5, "lon": 0.5}, samplingDate=NMIN_DATE)
    res = ask(client, plan, strategy="potential").json()
    assert res == before and res["notices"] == []
    assert {z["soil_analysis"] for z in res["zones"]} == {None}


def two_applications(client, data):
    """Two N applications: seq 0 first (60 N), seq 1 later."""
    sheet = {**SOIL_SHEET, "applications": [FERT, {**FERT, "stage": "top_dressing"}]}
    with_analyses(data, nmin_analysis("zn0", 8.0, 3.0, hasAgriManagementZone=zone_id(0)))
    return calculated_plan(client, sheet)


def codes(res):
    return [n["code"] for n in res["notices"]]


def test_zone_nmin_applies_to_the_first_application_only(client, data):
    plan = two_applications(client, data)
    first = ask(client, plan, strategy="potential", target={"application_seq": 0}).json()
    assert first["zones"][0]["n_kg_ha"] == 45.3 and "zone_nmin_first_pass_only" not in codes(first)
    later = ask(client, plan, strategy="potential", target={"application_seq": 1}).json()
    assert doses(later) == [48.0, 72.0, 60.0, 60.0]
    assert later["zones"][0]["basis"] == "vigor" and later["zones"][0]["soil_analysis"] is None
    assert "zone_soil_missing" not in codes(later)          # no zone uses its own soil
    note = next(n for n in later["notices"] if n["code"] == "zone_nmin_first_pass_only")
    assert note["params"] == {"applied": False}


def test_a_free_dose_gets_the_zone_nmin_and_the_warning(client, data):
    plan = two_applications(client, data)
    res = ask(client, plan, strategy="potential").json()
    assert res["zones"][0]["n_kg_ha"] == 45.3
    note = next(n for n in res["notices"] if n["code"] == "zone_nmin_first_pass_only")
    assert note["params"] == {"applied": True}


def test_p_and_k_are_flagged_when_the_inputs_changed_since_the_calculation(client, data):
    with_analyses(data, pk_analysis("zp0", 4.0, 90.0, hasAgriManagementZone=zone_id(0)))
    plan = calculated_plan(client, SOIL_SHEET)
    assert "zone_soil_inputs_changed" not in codes(ask(client, plan, strategy="potential").json())
    data["analyses"][URN][0]["horizons"][0]["phosphorusAvailable"] = 3.0      # the parcel's a1
    res = ask(client, plan, strategy="potential").json()
    assert "zone_soil_inputs_changed" in codes(res)
    assert res["rest"]["p2o5_kg_ha"] == 50.3          # the stored value is kept


def test_recalculation_is_asked_only_when_an_old_result_had_an_nmin_analysis(client, data,
                                                                            monkeypatch):
    import app.calc.sheet as sheet_mod
    with_analyses(data, nmin_analysis("zn0", 8.0, 3.0, hasAgriManagementZone=zone_id(0)))
    real = sheet_mod._inputs

    def old(a):
        out = real(a)
        out.pop("soil.nmin_analysis")
        return out

    monkeypatch.setattr(sheet_mod, "_inputs", old)
    old_plan = calculated_plan(client, SOIL_SHEET)
    res = ask(client, old_plan, strategy="potential").json()
    assert "zone_nmin_needs_recalculation" in codes(res)
    assert {z["nmin_kg_ha"] for z in res["zones"]} == {None}


def test_no_recalculation_notice_when_the_old_result_had_no_nmin_analysis(client, data,
                                                                         monkeypatch):
    import app.calc.sheet as sheet_mod
    with_analyses(data, nmin_analysis("zn0", 8.0, 3.0, hasAgriManagementZone=zone_id(0)))
    real = sheet_mod._inputs
    monkeypatch.setattr(sheet_mod, "_inputs",
                        lambda a: {k: v for k, v in real(a).items() if k != "soil.nmin_analysis"})
    plan = calculated_plan(client)                    # no Nmin analysis chosen
    assert "zone_nmin_needs_recalculation" not in codes(
        ask(client, plan, strategy="potential").json())


def test_basis_is_zone_soil_only_for_values_actually_used(client, data, monkeypatch):
    with_analyses(data, pk_analysis("zp0", 4.0, 90.0, hasAgriManagementZone=zone_id(0)))
    plan = calculated_plan(client, SOIL_SHEET, calculate=False)
    for param, value in (("soil.p_olsen_mg_kg", 20.0), ("soil.k_mg_kg", 200.0)):
        r = client.put(f"{BASE}/{plan['id']}/sheets/wheat/overrides/{param}", headers={**HOLDER, "X-User-Roles": "TenantAdmin,TechnicalConsultant"},
                       json={"row_version": plan["row_version"], "value": value, "reason": "lab"})
        assert r.status_code == 200, r.text
        plan = r.json()
    r = client.post(f"{BASE}/{plan['id']}/calculate", headers=HOLDER,
                    json={"row_version": plan["row_version"]})
    assert r.status_code == 200, r.text
    plan = r.json()
    res = ask(client, plan, strategy="potential").json()
    assert res["zones"][0]["basis"] == "vigor" and res["zones"][0]["soil_analysis"] is None


def test_an_nmin_only_zone_counts_its_nmin_analyses(client, data):
    with_analyses(data, nmin_analysis("zn0", 8.0, 3.0, hasAgriManagementZone=zone_id(0)),
                  nmin_analysis("zn0b", 6.0, 3.0, hasAgriManagementZone=zone_id(0)))
    res = ask(client, calculated_plan(client, SOIL_SHEET), strategy="potential").json()
    assert res["zones"][0]["soil_analysis"]["n_samples"] == 2
    assert res["zones"][0]["basis"] == "zone_soil"


def test_a_zone_nmin_alone_counts_one_sample(client, data):
    with_analyses(data, nmin_analysis("zn0", 8.0, 3.0, hasAgriManagementZone=zone_id(0)))
    res = ask(client, calculated_plan(client, SOIL_SHEET), strategy="potential").json()
    assert res["zones"][0]["soil_analysis"] == {"id": "zn0", "date": NMIN_DATE, "n_samples": 1,
                                                "p_date": None, "k_date": None}


def test_capped_keeps_its_meaning_of_clipped_by_the_cap(client, data):
    data["zones"][URN] = zone_set([0.75, 0.45, 0.4, 0.4])
    with_analyses(data, nmin_analysis("zn1", 10.0, 5.0, hasAgriManagementZone=zone_id(1)))
    res = ask(client, calculated_plan(client, SOIL_SHEET), strategy="potential",
              cap_pct=20).json()
    assert [z["capped"] for z in res["zones"]] == [True, False, False, False]
    assert [z["outside_cap"] for z in res["zones"]] == [False, True, False, False]


def test_the_parcel_rerun_failing_falls_back_to_the_parcel_values(client, data, monkeypatch):
    plan = calculated_plan(client, SOIL_SHEET)
    plain = ask(client, plan, strategy="potential").json()
    _soil_data(data)
    import app.zones.service as svc

    def boom(a):
        raise ValueError("boom")

    monkeypatch.setattr(svc, "calculate", boom)
    _unavailable_checks(ask(client, plan, strategy="potential").json(), plain)


def test_the_free_dose_notice_is_only_given_when_the_correction_was_applied(client, data):
    with_analyses(data, nmin_analysis("zn0", 8.0, 3.0, date=LATER,
                                      hasAgriManagementZone=zone_id(0)))
    res = ask(client, calculated_plan(client, SOIL_SHEET), strategy="potential").json()
    assert "zone_nmin_first_pass_only" not in codes(res)


def test_a_zone_nmin_of_another_depth_is_not_credited(client, data):
    deep = nmin_analysis("zn0", 8.0, 3.0, hasAgriManagementZone=zone_id(0))
    deep["horizons"] = [{"depthFrom": 0, "depthTo": 30, "nitrateN": 8.0, "ammoniumN": 3.0,
                         "bulkDensity": 1.0},
                        {"depthFrom": 30, "depthTo": 90, "nitrateN": 8.0, "ammoniumN": 3.0,
                         "bulkDensity": 1.0}]
    with_analyses(data, deep)
    res = ask(client, calculated_plan(client, SOIL_SHEET), strategy="potential").json()
    assert doses(res) == [48.0, 72.0, 60.0, 60.0] and res["zones"][0]["nmin_kg_ha"] is None
    assert {"code": "zone_nmin_depth_differs", "params": {"zone": zone_id(0)}} in res["notices"]
    assert "zone_soil_unusable" not in codes(res)          # the specific notice is enough


def test_bad_zone_data_is_unusable_not_a_500(client, data):
    with_analyses(data, nmin_analysis("zn0", -1.0, 3.0, hasAgriManagementZone=zone_id(0)))
    res = ask(client, calculated_plan(client, SOIL_SHEET), strategy="potential").json()
    assert doses(res) == [48.0, 72.0, 60.0, 60.0]
    assert "zone_nmin_incomplete" in codes(res)


def test_a_zone_soil_function_raising_is_flagged_for_that_zone(client, data, monkeypatch):
    with_analyses(data, nmin_analysis("zn0", 8.0, 3.0, hasAgriManagementZone=zone_id(0)))
    plan = calculated_plan(client, SOIL_SHEET)
    import app.zones.service as svc

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(svc, "zone_soil", boom)
    res = ask(client, plan, strategy="potential").json()
    assert doses(res) == [48.0, 72.0, 60.0, 60.0]
    assert {"code": "zone_soil_calc_failed", "params": {"zone": zone_id(0)}} in res["notices"]


def test_a_sample_with_an_unusable_method_is_reported(client, data):
    odd = pk_analysis("zp0", 4.0, 90.0, hasAgriManagementZone=zone_id(0))
    odd["horizons"][0]["phosphorusMethod"] = "unknown_method"
    odd["horizons"][0]["potassiumMethod"] = "mehlich3"
    with_analyses(data, odd)
    res = ask(client, calculated_plan(client, SOIL_SHEET), strategy="potential").json()
    assert {"code": "zone_soil_unusable", "params": {"zone": zone_id(0), "analyses": ["zp0"]}
            } in res["notices"]
    assert res["zones"][0]["basis"] == "vigor"


def test_samples_older_than_the_zoning_are_not_zone_samples(client, data):
    plan = calculated_plan(client, SOIL_SHEET)
    before = ask(client, plan, strategy="potential").json()
    with_analyses(data, pk_analysis("old", 4.0, 90.0, date="2020-03-01",
                                    location={"lat": 0.5, "lon": 0.5}),
                  pk_analysis("old2", 4.0, 90.0, date="2020-03-01",
                              hasAgriManagementZone=zone_id(0)))
    data["analyses"][URN] = [a for a in data["analyses"][URN] if a["id"] != "n1"]
    data["analyses"][URN].append(nmin_analysis("n1", 5.0, 5.0))
    assert ask(client, plan, strategy="potential").json() == before


def test_a_zoning_without_a_date_has_no_zone_samples(client, data):
    for e in data["zones"][URN]:
        e.pop("dateZoned")
    with_analyses(data, pk_analysis("zp0", 4.0, 90.0, hasAgriManagementZone=zone_id(0)))
    res = ask(client, calculated_plan(client, SOIL_SHEET), strategy="potential").json()
    assert "zone_soil_no_zoning_date" in codes(res)
    assert {z["soil_analysis"] for z in res["zones"]} == {None}


def test_a_same_date_campaign_makes_the_sheets_analysis_a_zone_sample(client, data):
    chosen = {**data["analyses"][URN][0], "samplingDate": NMIN_DATE,
              "location": {"lat": 0.5, "lon": 0.5}}
    chosen["hasAgriManagementZone"] = zone_id(0)
    data["analyses"][URN] = [chosen, nmin_analysis("n1", 5.0, 5.0),
                             pk_analysis("zp1", 4.0, 90.0, hasAgriManagementZone=zone_id(1))]
    res = ask(client, calculated_plan(client, SOIL_SHEET), strategy="potential").json()
    z = res["zones"]
    assert z[0]["basis"] == "zone_soil" and z[0]["soil_analysis"]["id"] == "a1"
    assert z[0]["p2o5_kg_ha"] == res["rest"]["p2o5_kg_ha"]       # same numbers as the parcel
    assert z[1]["basis"] == "zone_soil" and z[1]["p2o5_kg_ha"] > res["rest"]["p2o5_kg_ha"]


def test_a_partly_measured_zone_nulls_the_date_it_does_not_use(client, data):
    only_p = pk_analysis("zp0", 4.0, 90.0, hasAgriManagementZone=zone_id(0))
    only_p["horizons"][0]["potassiumMethod"] = "mehlich3"
    with_analyses(data, only_p)
    res = ask(client, calculated_plan(client, SOIL_SHEET), strategy="potential").json()
    assert res["zones"][0]["soil_analysis"] == {"id": "zp0", "date": NMIN_DATE, "n_samples": 1,
                                                "p_date": NMIN_DATE, "k_date": None}
    assert res["zones"][0]["k2o_kg_ha"] == res["rest"]["k2o_kg_ha"]


def test_the_first_pass_is_the_earliest_planned_date(client, data):
    sheet = {**SOIL_SHEET, "applications": [
        {**FERT, "stage": "top_dressing", "planned_date": "2027-03-10"},
        {**FERT, "planned_date": "2027-01-10"}]}
    with_analyses(data, nmin_analysis("zn0", 8.0, 3.0, hasAgriManagementZone=zone_id(0)))
    plan = calculated_plan(client, sheet)
    first = ask(client, plan, strategy="potential", target={"application_seq": 1}).json()
    assert first["zones"][0]["n_kg_ha"] == 45.3
    later = ask(client, plan, strategy="potential", target={"application_seq": 0}).json()
    assert later["zones"][0]["n_kg_ha"] == 48.0 and "zone_nmin_first_pass_only" in codes(later)


def test_the_first_pass_warning_needs_a_correction_that_could_apply(client, data):
    sheet = {**SOIL_SHEET, "applications": [FERT, {**FERT, "stage": "top_dressing"}]}
    plan = calculated_plan(client, sheet)             # no zone samples at all
    res = ask(client, plan, strategy="potential", target={"application_seq": 1}).json()
    assert "zone_nmin_first_pass_only" not in codes(res)


def test_zone_n_with_no_nmin_analysis_on_the_plan_is_explained(client, data):
    with_analyses(data, nmin_analysis("zn0", 8.0, 3.0, hasAgriManagementZone=zone_id(0)))
    res = ask(client, calculated_plan(client, SHEET), strategy="potential").json()   # no Nmin id
    note = [n for n in res["notices"] if n["code"] == "zone_nmin_parcel_unusable"]
    assert note == [{"code": "zone_nmin_parcel_unusable", "params": {"reason": "no_nmin_analysis"}}]
    assert "zone_soil_unusable" not in codes(res)       # an N-only sample is not "unusable"
    assert doses(res) == [48.0, 72.0, 60.0, 60.0]


def test_zone_n_with_an_unknown_parcel_nmin_depth_is_explained(client, data):
    with_analyses(data, nmin_analysis("zn0", 8.0, 3.0, hasAgriManagementZone=zone_id(0)))
    n1 = next(a for a in data["analyses"][URN] if a["id"] == "n1")
    n1["horizons"].append({**n1["horizons"][0], "depthFrom": 60, "depthTo": 90})   # a gap
    res = ask(client, calculated_plan(client, SOIL_SHEET), strategy="potential").json()
    note = [n for n in res["notices"] if n["code"] == "zone_nmin_parcel_unusable"]
    assert note[0]["params"] == {"reason": "depth_unknown"}
    assert "zone_soil_unusable" not in codes(res)


def test_no_nmin_notice_without_zone_n_data(client, data):
    with_analyses(data, pk_analysis("zp0", 4.0, 90.0, hasAgriManagementZone=zone_id(0)))
    res = ask(client, calculated_plan(client, SHEET), strategy="potential").json()
    assert "zone_nmin_parcel_unusable" not in codes(res)


def test_the_depth_lookup_is_skipped_when_the_soil_is_unavailable(client, data, monkeypatch,
                                                                  caplog):
    plan = calculated_plan(client, SOIL_SHEET)

    async def boom(self, urn):
        raise SourceUnavailable("soil", "unreachable (ConnectError)")

    monkeypatch.setattr(FakeSources, "lab_analyses", boom)
    res = ask(client, plan, strategy="potential").json()
    assert codes(res) == ["zone_soil_unavailable"]
    assert "depth of the parcel" not in caplog.text


def test_with_a_zone_mean_parcel_soil_the_zone_samples_still_count_as_zone_samples(client, data):
    from tests.zones.test_parcel_zone_mean import pk

    data["analyses"][URN] += [pk("zp0", 4.0, 90.0, zone_id(0)), pk("zp1", 8.0, 110.0, zone_id(1))]
    res = ask(client, calculated_plan(client), strategy="potential").json()
    z = res["zones"]
    assert [x["basis"] for x in z] == ["zone_soil", "zone_soil", "vigor", "vigor"]
    assert [x["soil_analysis"]["id"] for x in z[:2]] == ["zp0", "zp1"]
    assert z[0]["p2o5_kg_ha"] > res["rest"]["p2o5_kg_ha"] > z[1]["p2o5_kg_ha"]
    assert {x["p2o5_kg_ha"] for x in z[2:]} == {res["rest"]["p2o5_kg_ha"]}
    assert "zone_soil_inputs_changed" not in [n["code"] for n in res["notices"]]


def _only_pk(a):
    for k in ("sand", "clay", "ph", "organicMatter"):
        a["horizons"][0].pop(k)
    return a


def test_the_zones_are_read_once_per_request(client, data, monkeypatch):
    from tests.zones.test_parcel_zone_mean import pk
    data["analyses"][URN] += [pk("zp0", 4.0, 90.0, zone_id(0)), pk("zp1", 8.0, 110.0, zone_id(1))]
    plan = calculated_plan(client)
    calls = []
    original = FakeSources.zone_entities

    async def counting(self, urn):
        calls.append(urn)
        return await original(self, urn)

    monkeypatch.setattr(FakeSources, "zone_entities", counting)
    assert ask(client, plan, strategy="potential").status_code == 200
    assert calls == [URN]


def test_the_fallback_analysis_of_the_parcel_soil_is_not_reported_as_outside(client, data):
    from tests.zones.test_parcel_zone_mean import pk
    par = pk("par", 14.0, 220.0, day=LATER)
    par["location"] = {"lat": 5.0, "lon": 5.0}
    data["analyses"][URN] += [_only_pk(pk("zp0", 4.0, 90.0, zone_id(0))),
                              _only_pk(pk("zp1", 8.0, 110.0, zone_id(1))), par]
    res = ask(client, calculated_plan(client), strategy="potential").json()
    assert "zone_soil_outside" not in [n["code"] for n in res["notices"]]
    assert [x["basis"] for x in res["zones"]][:2] == ["zone_soil", "zone_soil"]
