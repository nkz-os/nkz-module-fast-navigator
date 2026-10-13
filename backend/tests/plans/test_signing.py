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
    assert snapshot["versions"]["rules"] == "es-2026.10.3"
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
    await signing.put_holder_qualification(pool, TECH, "Juan", "Ingeniero Agronomo", "COIA 1")
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
    assert old["state"] == "signed"           # stays in force until the revision is signed
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


async def _audit_count(pool, pid):
    async with pool.acquire() as c:
        return len(await repo.get_audit(c, pid))


async def _assert_untouched(pool, pid, before, audits):
    after = await service.get(pool, FARMER, pid)
    assert after["state"] == before["state"] and after["row_version"] == before["row_version"]
    assert after["snapshot_sha256"] is None and after["signed_at"] is None
    assert await _audit_count(pool, pid) == audits
    async with pool.acquire() as c:
        assert await repo.get_snapshot(c, pid) is None


async def test_one_clock_for_the_signature_time(pool):
    from datetime import datetime
    pid, plan = await ready(pool)
    closed = await signing.close(pool, FARMER, pid, plan["row_version"],
                                 "titular_sin_obligacion", "Juan", EARLY)
    async with pool.acquire() as c:
        snapshot = await repo.get_snapshot(c, pid)
    assert datetime.fromisoformat(closed["signed_at"]) == \
        datetime.fromisoformat(snapshot["signature"]["signed_at"])


async def test_a_farmer_cannot_sign_even_without_a_profile_check(pool):
    pid, plan = await ready(pool)
    plan = await service.transition(pool, FARMER, pid, plan["row_version"],
                                    service.Action.SUBMIT)
    with pytest.raises(TransitionError) as err:
        await signing.sign(pool, FARMER, pid, plan["row_version"], EARLY)
    assert err.value.code == "forbidden"


async def test_a_blocked_sign_changes_nothing(pool):
    pid, plan = await ready(pool, apps=())
    plan = await service.transition(pool, FARMER, pid, plan["row_version"],
                                    service.Action.SUBMIT)
    await signing.put_advisor(pool, TECH, "Ana", "NA-1")
    audits = await _audit_count(pool, pid)
    with pytest.raises(TransitionError):
        await signing.sign(pool, TECH, pid, plan["row_version"], EARLY)
    await _assert_untouched(pool, pid, plan, audits)


async def test_a_blocked_close_changes_nothing(pool):
    pid, plan = await ready(pool)
    audits = await _audit_count(pool, pid)
    with pytest.raises(TransitionError) as err:
        await signing.close(pool, FARMER, pid, plan["row_version"], "titular_sin_obligacion",
                            "Juan", LATE)
    assert err.value.code == "advice_required"
    await _assert_untouched(pool, pid, plan, audits)


async def test_a_stale_calculation_cannot_be_signed_or_closed_after_an_edit(pool):
    pid, plan = await ready(pool)
    plan = await service.edit_sheets(pool, FARMER, pid, plan["row_version"], [good_sheet()])
    with pytest.raises(TransitionError) as err:
        await signing.close(pool, FARMER, pid, plan["row_version"], "titular_sin_obligacion",
                            "Juan", EARLY)
    assert err.value.code == "not_allowed"     # an edit sends a calculated plan back to draft
    await service.calculate_plan(pool, sources(), FARMER, pid, plan["row_version"], EARLY)
    plan = await service.get(pool, FARMER, pid)
    plan = await service.transition(pool, FARMER, pid, plan["row_version"],
                                    service.Action.SUBMIT)
    await signing.put_advisor(pool, TECH, "Ana", "NA-1")
    plan = await service.edit_sheets(pool, TECH, pid, plan["row_version"], [good_sheet()])
    with pytest.raises(TransitionError) as err:
        await signing.sign(pool, TECH, pid, plan["row_version"], EARLY)
    assert err.value.code == "stale_calculation"


async def test_another_tenant_sees_no_plan(pool):
    pid, plan = await ready(pool)
    rv = plan["row_version"]
    with pytest.raises(service.NotFound):
        await signing.sign(pool, OTHER, pid, rv, EARLY)
    with pytest.raises(service.NotFound):
        await signing.close(pool, OTHER, pid, rv, "titular_sin_obligacion", "Juan", EARLY)
    with pytest.raises(service.NotFound):
        await signing.revise(pool, OTHER, pid, rv)


async def test_revising_copies_everything_the_plan_holds(pool):
    pid, plan = await ready(pool)
    plan = await service.set_override(pool, TECH, pid, plan["row_version"], "wheat", "soil.ph",
                                      7.2, "lab")
    plan = await service.set_declarations(pool, FARMER, pid, plan["row_version"],
                                          vulnerable_zone=False, vulnerable_zone_source="order",
                                          voluntary_digital_notebook=True)
    plan = await service.calculate_plan(pool, sources(), FARMER, pid, plan["row_version"], EARLY)
    closed = await signing.close(pool, FARMER, pid, plan["row_version"],
                                 "titular_sin_obligacion", "Juan", EARLY)
    new = await signing.revise(pool, FARMER, pid, closed["row_version"])
    (sheet,) = new["sheets"]
    assert sheet["applications"] == [APP]
    assert [o["param"] for o in sheet["overrides"]] == ["soil.ph"]
    assert new["declarations"] == {"vulnerable_zone": False, "vulnerable_zone_source": "order",
                                   "voluntary_digital_notebook": True}
    assert new["rain_normal"] == closed["rain_normal"] and new["rain_normal"] is not None


async def test_history_values_come_from_the_signed_plan(pool):
    pid, plan = await ready(pool)
    closed = await signing.close(pool, FARMER, pid, plan["row_version"],
                                 "titular_sin_obligacion", "Juan", EARLY)
    (old,) = closed["sheets"]
    nxt = await service.create(pool, FARMER, 2028, "tenant")
    nid = uuid.UUID(nxt["id"])
    base = good_sheet()
    mine = repo.SheetData("wheat", {**base.inputs, "campaign": 2028}, base.parcels,
                          base.applications)
    other = repo.SheetData("other", {**base.inputs, "campaign": 2028},
                           (("urn:ngsi-ld:AgriParcel:other", None),), base.applications)
    await service.edit_sheets(pool, FARMER, nid, nxt["row_version"], [mine, other])
    async with pool.acquire() as c:
        ctx, _, _ = await service.build_context(c, await repo.get_plan(c, "tenant-a", nid), EARLY)
    by_key = {s.key: s.history for s in ctx.sheets}
    (entry,) = by_key["wheat"]
    assert set(entry) == {"campaign", "p2o5_planned_kg_ha", "p2o5_calculated_kg_ha",
                          "k2o_planned_kg_ha", "k2o_calculated_kg_ha"}
    summary = old["applications_summary"]
    assert entry["campaign"] == 2027
    assert entry["p2o5_planned_kg_ha"] == summary["p2o5_kg_ha"] and summary["p2o5_kg_ha"] > 0
    assert entry["k2o_planned_kg_ha"] == summary["k2o_kg_ha"]
    assert entry["p2o5_calculated_kg_ha"] == old["result"]["p2o5"]["before_organic_kg_ha"]
    assert entry["k2o_calculated_kg_ha"] == old["result"]["k2o"]["before_organic_kg_ha"]
    assert by_key["other"] == ()


async def _closed_with_split(pool):
    pid, plan = await ready(pool)
    closed = await signing.close(pool, FARMER, pid, plan["row_version"],
                                 "titular_sin_obligacion", "Juan", EARLY)
    async with pool.acquire() as c:
        return pid, closed, await repo.get_snapshot(c, pid)


async def test_the_copy_holds_what_reproduces_the_verdict(pool):
    _, _, snapshot = await _closed_with_split(pool)
    assert snapshot["judged_at"] == EARLY.isoformat()
    assert snapshot["sheets"][0]["history"] == []
    split = snapshot["split_findings"]
    assert {f["rule_id"] for f in split} >= {"FAST-split-total_below_n_min"}
    assert all(f["rule_id"].startswith("FAST-split-") and f["sheet_key"] == "wheat"
               for f in split)


async def test_the_copy_keeps_the_history_the_rules_saw(pool, monkeypatch):
    seen = ({"campaign": 2026, "p2o5_planned_kg_ha": 30.0, "p2o5_calculated_kg_ha": 40.0,
             "k2o_planned_kg_ha": 20.0, "k2o_calculated_kg_ha": 25.0},)
    monkeypatch.setattr(service, "_history", lambda parcels, snapshots: seen)
    pid, plan = await ready(pool)
    await signing.close(pool, FARMER, pid, plan["row_version"], "titular_sin_obligacion",
                        "Juan", EARLY)
    async with pool.acquire() as c:
        snapshot = await repo.get_snapshot(c, pid)
    assert snapshot["sheets"][0]["history"] == list(seen)


async def test_a_signed_plan_shows_its_sealed_verdict(pool, monkeypatch):
    pid, closed, snapshot = await _closed_with_split(pool)
    monkeypatch.setattr(service, "RULES_VERSION", "es-later")
    view = await service.get(pool, FARMER, pid)
    assert view["rules_version"] == snapshot["versions"]["rules"] != "es-later"
    rules = [{"rule_id": f["rule_id"], "severity": f["severity"],
              "params": {**f["params"], "citation": f["citation"]}, "sheet_key": f["sheet_key"]}
             for f in snapshot["findings"]]
    assert view["findings"] == snapshot["split_findings"] + rules
    assert any(f["rule_id"].startswith("FAST-split-") for f in view["findings"])
    assert all("citation" in f["params"] for f in view["findings"] if f not in
               snapshot["split_findings"])
    new = await signing.revise(pool, FARMER, pid, closed["row_version"])
    old = await service.get(pool, FARMER, pid)
    assert old["state"] == "signed" and old["findings"] == view["findings"]
    assert new["rules_version"] == "es-later"


async def test_the_generic_transition_cannot_sign_close_or_revise(pool):
    pid, plan = await ready(pool)
    for action in (service.Action.SIGN, service.Action.CLOSE, service.Action.REVISE):
        with pytest.raises(TransitionError) as err:
            await service.transition(pool, TECH, pid, plan["row_version"], action)
        assert err.value.code == "not_allowed"
    after = await service.get(pool, FARMER, pid)
    assert after["state"] == plan["state"] and after["row_version"] == plan["row_version"]


async def test_the_seal_is_taken_over_what_jsonb_stores(pool, monkeypatch):
    from app.calc.snapshot import sha256_of
    real = signing._freeze

    async def odd(*args):                # the engine does produce -0.0; jsonb stores 0.0
        return {**await real(*args), "odd": {"zero": -0.0, "big": 1e20}}

    monkeypatch.setattr(signing, "_freeze", odd)
    pid, plan = await ready(pool)
    closed = await signing.close(pool, FARMER, pid, plan["row_version"],
                                 "titular_sin_obligacion", "Juan", EARLY)
    async with pool.acquire() as c:
        stored = await repo.get_snapshot(c, pid)
    assert sha256_of(stored) == closed["snapshot_sha256"]
