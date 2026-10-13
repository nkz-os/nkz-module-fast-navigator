import uuid
from datetime import date

import pytest

from app.calc.assemble import ParcelNotFound
from app.plans import repo, service
from app.plans.states import Action, TransitionError
from app.sources.errors import SourceUnavailable
from tests.fakes import URN, FakeSources, complete_data

FARMER = service.Actor("tenant-a", "u-farmer", frozenset({"Farmer"}))
TECH = service.Actor("tenant-a", "u-tech", frozenset({"TechnicalConsultant"}))
OTHER = service.Actor("tenant-b", "u-other", frozenset({"Farmer"}))
TODAY = date(2026, 10, 13)


def sheet(key="wheat", organic=(), apps=()):
    inputs = {"campaign": 2027, "tillage": True, "irrigated": False, "rotation_years": 4,
              "strategy": 2, "previous_residues_burned": False, "crop_eppo": None,
              "previous_crop_eppo": None, "cycle_index": 0, "soil_analysis_id": None,
              "nmin_analysis_id": None, "declared_yields": {}, "previous_declared_yields": {},
              "organic": list(organic), "water_m3_ha": None, "water_quality_id": None,
              "no3_mg_l": None, "nuts": None}
    return repo.SheetData(key, inputs, ((URN, None),), tuple(apps))


SLURRY = {"material": "slurry", "rate_t_ha": 30.0, "n_pct": 0.5, "p2o5_pct": 0.2, "k2o_pct": 0.6}


async def _ready(pool, sheets=None):
    plan = await service.create(pool, FARMER, 2027, "tenant")
    return await service.edit_sheets(pool, FARMER, uuid.UUID(plan["id"]), plan["row_version"],
                                     sheets or [sheet()])


async def test_create_list_get(pool):
    plan = await service.create(pool, FARMER, 2027, "tenant")
    assert plan["state"] == "draft" and plan["sheets"] == [] and not plan["calc_fresh"]
    assert [p["id"] for p in await service.list_(pool, FARMER, 2027)] == [plan["id"]]
    assert (await service.get(pool, FARMER, uuid.UUID(plan["id"])))["id"] == plan["id"]


async def test_another_tenant_never_sees_the_plan(pool):
    plan = await service.create(pool, FARMER, 2027, "tenant")
    with pytest.raises(service.NotFound):
        await service.get(pool, OTHER, uuid.UUID(plan["id"]))
    assert await service.list_(pool, OTHER, None) == []


async def test_a_second_open_plan_is_a_conflict(pool):
    await service.create(pool, FARMER, 2027, "tenant")
    with pytest.raises(service.Conflict):
        await service.create(pool, TECH, 2027, "tenant")


async def test_calculate_then_edit_goes_back_to_draft(pool):
    plan = await _ready(pool)
    pid = uuid.UUID(plan["id"])
    calc = await service.calculate_plan(pool, FakeSources(**complete_data()), FARMER, pid,
                                        plan["row_version"], TODAY)
    assert calc["state"] == "calculated" and calc["calc_fresh"]
    assert calc["sheets"][0]["result"]["status"] == "complete"
    assert calc["sheets"][0]["applications_summary"]["mineral_n_kg_ha"] == 0
    edited = await service.edit_sheets(pool, FARMER, pid, calc["row_version"], [sheet()])
    assert edited["state"] == "draft" and not edited["calc_fresh"]


async def test_a_stale_row_version_is_refused(pool):
    plan = await _ready(pool)
    pid = uuid.UUID(plan["id"])
    with pytest.raises(service.Conflict):
        await service.edit_sheets(pool, TECH, pid, plan["row_version"] - 1, [sheet()])


async def test_an_edit_during_the_calculation_wins(pool, monkeypatch):
    plan = await _ready(pool)
    pid = uuid.UUID(plan["id"])
    from app.plans import service as svc

    real = svc.assemble

    async def slow_assemble(req, sources, today):
        await service.edit_sheets(pool, TECH, pid, plan["row_version"], [sheet()])
        return await real(req, sources, today)

    monkeypatch.setattr(svc, "assemble", slow_assemble)
    with pytest.raises(service.Conflict):
        await service.calculate_plan(pool, FakeSources(**complete_data()), FARMER, pid,
                                     plan["row_version"], TODAY)
    after = await service.get(pool, FARMER, pid)
    assert after["state"] == "draft" and after["sheets"][0]["result"] is None


async def test_a_failing_source_leaves_the_plan_untouched(pool):
    plan = await _ready(pool)
    pid = uuid.UUID(plan["id"])
    data = complete_data()
    data["fail"] = {"lab_analyses": SourceUnavailable("soil", "answered 500")}
    with pytest.raises(SourceUnavailable):
        await service.calculate_plan(pool, FakeSources(**data), FARMER, pid, plan["row_version"],
                                     TODAY)
    after = await service.get(pool, FARMER, pid)
    assert after["row_version"] == plan["row_version"] and after["state"] == "draft"


async def test_an_unknown_parcel_leaves_the_plan_untouched(pool):
    bad = repo.SheetData("x", sheet().inputs, (("urn:ngsi-ld:AgriParcel:nope", None),), ())
    plan = await _ready(pool, [bad])
    with pytest.raises(ParcelNotFound):
        await service.calculate_plan(pool, FakeSources(**complete_data()), FARMER,
                                     uuid.UUID(plan["id"]), plan["row_version"], TODAY)


async def test_a_plan_without_sheets_is_not_calculated(pool):
    plan = await service.create(pool, FARMER, 2027, "tenant")
    with pytest.raises(service.Invalid):
        await service.calculate_plan(pool, FakeSources(**complete_data()), FARMER,
                                     uuid.UUID(plan["id"]), plan["row_version"], TODAY)


async def test_overrides_keep_their_author(pool):
    plan = await _ready(pool, [sheet(organic=[SLURRY])])
    pid = uuid.UUID(plan["id"])
    plan = await service.set_override(pool, TECH, pid, plan["row_version"], "wheat", "soil.ph",
                                      7.2, "new lab sheet")
    plan = await service.set_override(pool, FARMER, pid, plan["row_version"], "wheat",
                                      "organic.0.availability", 0.6, "own analysis")
    by_param = {o["param"]: o for o in plan["sheets"][0]["overrides"]}
    assert by_param["soil.ph"]["user"] == "u-tech"
    assert by_param["organic.0.availability"]["user"] == "u-farmer"
    plan = await service.edit_sheets(pool, FARMER, pid, plan["row_version"], [sheet()])
    assert [o["param"] for o in plan["sheets"][0]["overrides"]] == ["soil.ph"]
    log = await service.audit(pool, FARMER, pid)
    assert log[-1]["detail"]["dropped_overrides"] == [
        {"sheet": "wheat", "param": "organic.0.availability", "value": 0.6, "user": "u-farmer"}]


COMPOST = {"material": "compost", "rate_t_ha": 20.0, "n_pct": 1.2, "p2o5_pct": 0.5,
           "k2o_pct": 0.8}


async def _two_organics_with_overrides(pool):
    plan = await _ready(pool, [sheet(organic=[SLURRY, COMPOST])])
    pid = uuid.UUID(plan["id"])
    plan = await service.set_override(pool, FARMER, pid, plan["row_version"], "wheat",
                                      "organic.0.availability", 0.1, "slurry analysis")
    plan = await service.set_override(pool, TECH, pid, plan["row_version"], "wheat",
                                      "organic.1.availability", 0.6, "compost analysis")
    return pid, plan


def _by_param(plan):
    return {o["param"]: (o["value"], o["user"], o["reason"]) for o in plan["sheets"][0]["overrides"]}


async def test_removing_an_organic_input_moves_the_other_override_with_its_input(pool):
    pid, plan = await _two_organics_with_overrides(pool)
    plan = await service.edit_sheets(pool, FARMER, pid, plan["row_version"],
                                     [sheet(organic=[COMPOST])])
    assert _by_param(plan) == {"organic.0.availability": (0.6, "u-tech", "compost analysis")}
    detail = (await service.audit(pool, FARMER, pid))[-1]["detail"]
    assert detail["dropped_overrides"] == [
        {"sheet": "wheat", "param": "organic.0.availability", "value": 0.1, "user": "u-farmer"}]


async def test_reordering_organic_inputs_swaps_the_overrides(pool):
    pid, plan = await _two_organics_with_overrides(pool)
    plan = await service.edit_sheets(pool, FARMER, pid, plan["row_version"],
                                     [sheet(organic=[COMPOST, SLURRY])])
    assert _by_param(plan) == {"organic.1.availability": (0.1, "u-farmer", "slurry analysis"),
                               "organic.0.availability": (0.6, "u-tech", "compost analysis")}


async def test_changing_the_material_at_an_index_drops_its_override(pool):
    pid, plan = await _two_organics_with_overrides(pool)
    other = {**SLURRY, "material": "other"}
    plan = await service.edit_sheets(pool, FARMER, pid, plan["row_version"],
                                     [sheet(organic=[other, COMPOST])])
    assert list(_by_param(plan)) == ["organic.1.availability"]
    detail = (await service.audit(pool, FARMER, pid))[-1]["detail"]
    assert [d["param"] for d in detail["dropped_overrides"]] == ["organic.0.availability"]


async def test_changing_only_the_rate_keeps_the_override(pool):
    pid, plan = await _two_organics_with_overrides(pool)
    plan = await service.edit_sheets(pool, FARMER, pid, plan["row_version"],
                                     [sheet(organic=[{**SLURRY, "rate_t_ha": 50.0}, COMPOST])])
    assert set(_by_param(plan)) == {"organic.0.availability", "organic.1.availability"}
    assert (await service.audit(pool, FARMER, pid))[-1]["detail"]["dropped_overrides"] == []


async def test_override_permissions_and_values(pool):
    plan = await _ready(pool, [sheet(organic=[SLURRY])])
    pid = uuid.UUID(plan["id"])
    with pytest.raises(TransitionError) as err:
        await service.set_override(pool, FARMER, pid, plan["row_version"], "wheat",
                                   "irrigation.uptake", 0.5, "x")
    assert err.value.code == "forbidden"
    with pytest.raises(service.Invalid):
        await service.set_override(pool, TECH, pid, plan["row_version"], "wheat", "soil.ph",
                                   99.0, "typo")
    with pytest.raises(service.Invalid):
        await service.set_override(pool, FARMER, pid, plan["row_version"], "wheat",
                                   "organic.3.availability", 0.5, "x")
    with pytest.raises(service.NotFound):
        await service.set_override(pool, TECH, pid, plan["row_version"], "nope", "soil.ph",
                                   7.0, "x")


async def test_delete_an_override(pool):
    plan = await _ready(pool)
    pid = uuid.UUID(plan["id"])
    plan = await service.set_override(pool, TECH, pid, plan["row_version"], "wheat", "soil.ph",
                                      7.2, "lab")
    plan = await service.delete_override(pool, TECH, pid, plan["row_version"], "wheat", "soil.ph")
    assert plan["sheets"][0]["overrides"] == []


async def test_submit_return_and_review_edits(pool):
    plan = await _ready(pool)
    pid = uuid.UUID(plan["id"])
    plan = await service.calculate_plan(pool, FakeSources(**complete_data()), FARMER, pid,
                                        plan["row_version"], TODAY)
    plan = await service.transition(pool, FARMER, pid, plan["row_version"], Action.SUBMIT)
    assert plan["state"] == "in_review"
    with pytest.raises(TransitionError) as err:
        await service.edit_sheets(pool, FARMER, pid, plan["row_version"], [sheet()])
    assert err.value.code == "forbidden"
    plan = await service.edit_sheets(pool, TECH, pid, plan["row_version"], [sheet()])
    assert plan["state"] == "in_review" and not plan["calc_fresh"]
    with pytest.raises(service.Invalid):
        await service.transition(pool, TECH, pid, plan["row_version"], Action.RETURN)
    plan = await service.transition(pool, TECH, pid, plan["row_version"], Action.RETURN,
                                    comment="soil analysis missing")
    assert plan["state"] == "draft"
    actions = [e["action"] for e in await service.audit(pool, FARMER, pid)]
    assert actions == ["create", "edit_sheets", "calculate", "submit", "edit_sheets", "return"]


async def test_split_findings_are_stored(pool):
    big = {"stage": "pre_plant", "kind": "mineral", "product_name": "AN 27", "n_pct": 27,
           "n_form": "mixed", "product_rate_kg_ha": 1000, "method": "broadcast",
           "machine": "spreader"}
    plan = await _ready(pool, [sheet(apps=[big])])
    pid = uuid.UUID(plan["id"])
    plan = await service.calculate_plan(pool, FakeSources(**complete_data()), FARMER, pid,
                                        plan["row_version"], TODAY)
    assert {f["rule_id"] for f in plan["findings"]} >= {"FAST-split-pre_plant_above_n_min"}
    assert all(f["sheet_key"] == "wheat" for f in plan["findings"])


async def test_rain_normal_is_stored(pool):
    plan = await _ready(pool)
    pid = uuid.UUID(plan["id"])
    src = FakeSources(**complete_data())
    plan = await service.store_rain_normal(pool, src, FARMER, pid)
    assert plan["rain_normal"]["years"] == [] and plan["state"] == "draft"
    assert [c[1] for c in src.calls if c[0] == "daily"] == list(range(2016, 2026))


async def _in_review(pool):
    plan = await _ready(pool)
    pid = uuid.UUID(plan["id"])
    plan = await service.calculate_plan(pool, FakeSources(**complete_data()), FARMER, pid,
                                        plan["row_version"], TODAY)
    plan = await service.transition(pool, FARMER, pid, plan["row_version"], Action.SUBMIT)
    return pid, plan


async def test_in_review_only_the_technician_stores_the_rain_normal(pool):
    pid, plan = await _in_review(pool)
    with pytest.raises(TransitionError) as err:
        await service.store_rain_normal(pool, FakeSources(**complete_data()), FARMER, pid)
    assert err.value.code == "forbidden"
    stored = await service.store_rain_normal(pool, FakeSources(**complete_data()), TECH, pid)
    assert stored["rain_normal"] is not None and stored["state"] == "in_review"


async def test_storing_the_rain_normal_does_not_bump_the_row_version(pool):
    plan = await _ready(pool)
    pid = uuid.UUID(plan["id"])
    stored = await service.store_rain_normal(pool, FakeSources(**complete_data()), FARMER, pid)
    assert stored["rain_normal"] is not None
    assert stored["row_version"] == plan["row_version"]
    # the other user's next edit, made with the version they read, is not a conflict
    await service.edit_sheets(pool, TECH, pid, plan["row_version"], [sheet()])


async def test_rain_normal_is_not_stored_if_the_plan_is_signed_meanwhile(pool):
    plan = await _ready(pool)
    pid = uuid.UUID(plan["id"])

    class Signing(FakeSources):
        async def daily(self, *args, **kwargs):
            async with pool.acquire() as conn:
                await conn.execute("UPDATE plans SET state = 'signed' WHERE id = $1", pid)
            return await super().daily(*args, **kwargs)

    with pytest.raises(TransitionError) as err:
        await service.store_rain_normal(pool, Signing(**complete_data()), FARMER, pid)
    assert err.value.code == "not_allowed"
    async with pool.acquire() as conn:
        assert (await repo.get_plan(conn, "tenant-a", pid)).rain is None
