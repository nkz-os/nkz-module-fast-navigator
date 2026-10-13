import uuid
from datetime import date

import pytest

from app.calc.snapshot import sha256_of
from app.plans import repo, service, signing
from app.plans.states import TransitionError
from tests.fakes import URN, FakeSources, complete_data

FARMER = service.Actor("tenant-a", "u-farmer", frozenset({"Farmer"}))
TECH = service.Actor("tenant-a", "u-tech", frozenset({"TechnicalConsultant"}))
OTHER = service.Actor("tenant-b", "u-x", frozenset({"Farmer"}))
EARLY = date(2026, 10, 20)        # before any advice obligation
LATE = date(2027, 10, 20)         # advice required (vulnerable or undeclared)
APP = {"stage": "pre_plant", "kind": "mineral", "product_name": "NPK 10-5-5", "n_pct": 10,
       "p2o5_pct": 5, "k2o_pct": 5, "n_form": "ammoniacal", "product_rate_kg_ha": 100,
       "method": "broadcast", "machine": "spreader", "annex_v": [], "other_measure": None}


def good_sheet(apps=(APP,)):
    inputs = {"campaign": 2027, "tillage": True, "irrigated": False, "rotation_years": 4,
              "strategy": 2, "previous_residues_burned": False, "crop_eppo": None,
              "previous_crop_eppo": None, "cycle_index": 0, "soil_analysis_id": None,
              "nmin_analysis_id": None, "declared_yields": {}, "previous_declared_yields": {},
              "organic": [], "water_m3_ha": None, "water_quality_id": None, "no3_mg_l": None,
              "nuts": "ES22"}         # declared: the zone yields of the fake data are ES22
    return repo.SheetData("wheat", inputs, ((URN, "31201A00100123"),), tuple(apps))


def sources():
    data = complete_data()
    data["parcels"][URN]["area"] = 12.0   # over 10 ha: not exempt from the plan (art. 4.2)
    return FakeSources(**data)


async def ready(pool, apps=(APP,), today=EARLY):
    plan = await service.create(pool, FARMER, 2027, "tenant")
    pid = uuid.UUID(plan["id"])
    plan = await service.edit_sheets(pool, FARMER, pid, plan["row_version"], [good_sheet(apps)])
    async with pool.acquire() as c:
        await repo.set_rain(c, pid, {"annual_mm": 600.0, "years": [2016]})
    plan = await service.get(pool, FARMER, pid)
    plan = await service.calculate_plan(pool, sources(), FARMER, pid, plan["row_version"], today)
    return pid, plan


def blocking(plan):
    return {f["rule_id"] for f in plan["findings"] if f["severity"] == "block"}


async def test_rules_are_evaluated_when_calculating(pool):
    _, plan = await ready(pool, apps=())
    assert "ES-RD1051-6.4-content" in blocking(plan)
    legal = [f for f in plan["findings"] if not f["rule_id"].startswith("FAST-split-")]
    assert legal and all("citation" in f["params"] for f in legal)


async def test_a_clean_plan_is_signed_frozen_and_reproducible(pool):
    pid, plan = await ready(pool)
    assert blocking(plan) == set(), plan["findings"]
    plan = await service.transition(pool, FARMER, pid, plan["row_version"],
                                    service.Action.SUBMIT)
    await signing.put_advisor(pool, TECH, "Ana Pérez", "NA-123")
    signed = await signing.sign(pool, TECH, pid, plan["row_version"], EARLY)
    assert signed["state"] == "signed" and len(signed["snapshot_sha256"]) == 64
    assert signed["signature"]["registration_number"] == "NA-123"
    async with pool.acquire() as c:
        snapshot = await repo.get_snapshot(c, pid)
    assert signing.verify_snapshot(snapshot) == []
    assert sha256_of(snapshot) == signed["snapshot_sha256"]      # the seal survives jsonb
    assert snapshot["versions"]["rules"] == "es-2026.10.1"
    assert snapshot["signature"]["name"] == "Ana Pérez"


async def test_signing_needs_an_advisor_profile(pool):
    pid, plan = await ready(pool)
    plan = await service.transition(pool, FARMER, pid, plan["row_version"],
                                    service.Action.SUBMIT)
    with pytest.raises(service.Invalid):
        await signing.sign(pool, TECH, pid, plan["row_version"], EARLY)


async def test_a_blocking_finding_prevents_signing_and_changes_nothing(pool):
    pid, plan = await ready(pool, apps=())
    plan = await service.transition(pool, FARMER, pid, plan["row_version"],
                                    service.Action.SUBMIT)
    await signing.put_advisor(pool, TECH, "Ana", "NA-1")
    with pytest.raises(TransitionError) as err:
        await signing.sign(pool, TECH, pid, plan["row_version"], EARLY)
    assert err.value.code == "blocking_findings" and "ES-RD1051-6.4-content" in err.value.detail
    after = await service.get(pool, FARMER, pid)
    assert after["state"] == "in_review" and after["row_version"] == plan["row_version"]


async def test_the_holder_closes_when_advice_is_not_required(pool):
    pid, plan = await ready(pool)
    closed = await signing.close(pool, FARMER, pid, plan["row_version"],
                                 "titular_sin_obligacion", "Juan Pérez", EARLY)
    assert closed["state"] == "signed" and closed["signature"]["kind"] == "holder"


async def test_closing_needs_an_advisor_once_the_law_requires_it(pool):
    pid, plan = await ready(pool)
    with pytest.raises(TransitionError) as err:
        await signing.close(pool, FARMER, pid, plan["row_version"], "titular_sin_obligacion",
                            "Juan", LATE)
    assert err.value.code == "advice_required"
    closed = await signing.close(pool, FARMER, pid, plan["row_version"], "titular_cualificado",
                                 "Juan", LATE)
    assert closed["signature"]["closure_basis"] == "titular_cualificado"


async def test_a_declared_non_vulnerable_farm_closes_until_2028(pool):
    pid, plan = await ready(pool)
    plan = await service.set_declarations(pool, FARMER, pid, plan["row_version"],
                                          vulnerable_zone=False,
                                          vulnerable_zone_source="regional order 2023",
                                          voluntary_digital_notebook=False)
    plan = await service.calculate_plan(pool, sources(), FARMER, pid, plan["row_version"], EARLY)
    closed = await signing.close(pool, FARMER, pid, plan["row_version"],
                                 "titular_sin_obligacion", "Juan", LATE)
    assert closed["state"] == "signed"


async def test_a_small_rainfed_farm_closes_without_an_advisor(pool):
    plan = await service.create(pool, FARMER, 2027, "tenant")
    pid = uuid.UUID(plan["id"])
    plan = await service.edit_sheets(pool, FARMER, pid, plan["row_version"], [good_sheet()])
    async with pool.acquire() as c:
        await repo.set_rain(c, pid, {"annual_mm": 600.0, "years": [2016]})
    plan = await service.get(pool, FARMER, pid)
    plan = await service.calculate_plan(pool, FakeSources(**complete_data()), FARMER, pid,
                                        plan["row_version"], EARLY)       # 10 ha, rainfed
    closed = await signing.close(pool, FARMER, pid, plan["row_version"],
                                 "titular_sin_obligacion", "Juan", LATE)
    assert closed["state"] == "signed"


async def test_declaring_non_vulnerable_needs_a_source(pool):
    pid, plan = await ready(pool)
    with pytest.raises(service.Invalid):
        await service.set_declarations(pool, FARMER, pid, plan["row_version"],
                                       vulnerable_zone=False, vulnerable_zone_source="  ",
                                       voluntary_digital_notebook=False)


@pytest.mark.parametrize("basis,name", [("whatever", "Juan"), ("titular_cualificado", " ")])
async def test_closing_needs_a_basis_and_a_name(pool, basis, name):
    pid, plan = await ready(pool)
    with pytest.raises(service.Invalid):
        await signing.close(pool, FARMER, pid, plan["row_version"], basis, name, EARLY)


async def test_revising_creates_the_next_version(pool):
    pid, plan = await ready(pool)
    closed = await signing.close(pool, FARMER, pid, plan["row_version"],
                                 "titular_sin_obligacion", "Juan", EARLY)
    new = await signing.revise(pool, FARMER, pid, closed["row_version"])
    assert new["version"] == 2 and new["supersedes"] == str(pid) and new["state"] == "draft"
    assert [s["key"] for s in new["sheets"]] == ["wheat"]
    old = await service.get(pool, FARMER, pid)
    assert old["state"] == "superseded"
    with pytest.raises(TransitionError):
        await service.edit_sheets(pool, FARMER, pid, old["row_version"], [good_sheet()])


async def test_summary_for_the_field_notebook(pool):
    pid, plan = await ready(pool)
    await signing.close(pool, FARMER, pid, plan["row_version"], "titular_sin_obligacion",
                        "Juan", EARLY)
    s = await signing.summary(pool, "tenant-a", URN, 2027)
    assert s["plan_id"] == str(pid) and s["signature"]["kind"] == "holder"
    assert "user_id" not in s["signature"]
    (sheet,) = s["sheets"]
    assert sheet["crop_eppo"] == "TRZAX" and sheet["n_kg_ha"]["avg"] > 0
    with pytest.raises(service.NotFound):
        await signing.summary(pool, "tenant-b", URN, 2027)
    with pytest.raises(service.NotFound):
        await signing.summary(pool, "tenant-a", "urn:ngsi-ld:AgriParcel:other", 2027)


async def test_history_feeds_the_five_year_limits(pool):
    pid, plan = await ready(pool)
    await signing.close(pool, FARMER, pid, plan["row_version"], "titular_sin_obligacion",
                        "Juan", EARLY)
    nxt = await service.create(pool, FARMER, 2028, "tenant")
    nid = uuid.UUID(nxt["id"])
    sheet = good_sheet()
    sheet = repo.SheetData(sheet.key, {**sheet.inputs, "campaign": 2028}, sheet.parcels,
                           sheet.applications)
    nxt = await service.edit_sheets(pool, FARMER, nid, nxt["row_version"], [sheet])
    async with pool.acquire() as c:
        plan_row = await repo.get_plan(c, "tenant-a", nid)
        ctx, _, _ = await service.build_context(c, plan_row, EARLY)
    assert [h["campaign"] for h in ctx.sheets[0].history] == [2027]


async def test_advisor_profile_round_trip(pool):
    assert await signing.get_advisor(pool, TECH) is None
    await signing.put_advisor(pool, TECH, "Ana", "NA-1")
    assert await signing.get_advisor(pool, TECH) == {"name": "Ana", "registration_number": "NA-1"}
    with pytest.raises(service.Invalid):
        await signing.put_advisor(pool, TECH, " ", "NA-1")
