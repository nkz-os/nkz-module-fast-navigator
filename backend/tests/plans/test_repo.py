import uuid

import pytest

from app.plans import repo

T = "tenant-a"


async def _plan(c, campaign=2027):
    return await repo.create_plan(c, tenant_id=T, farm="tenant", campaign=campaign, user_id="u1")


def _sheet(key, organic=0, parcels=(("urn:ngsi-ld:AgriParcel:p1", None),), apps=()):
    inputs = {"campaign": 2027, "tillage": True, "irrigated": False, "rotation_years": 4,
              "organic": [{"material": "slurry", "rate_t_ha": 30, "n_pct": 0.5, "p2o5_pct": 0.2,
                           "k2o_pct": 0.6}] * organic}
    return repo.SheetData(key, inputs, tuple(parcels), tuple(apps))


async def test_create_and_read(pool):
    async with pool.acquire() as c:
        plan = await _plan(c)
        assert plan.state == "draft" and plan.version == 1 and plan.row_version == 1
        assert not plan.calc_fresh
        assert (await repo.get_plan(c, T, plan.id)) == plan
        assert await repo.get_plan(c, "tenant-b", plan.id) is None
        assert [p.id for p in await repo.list_plans(c, T, 2027)] == [plan.id]
        assert await repo.list_plans(c, T, 2026) == []


async def test_only_one_open_plan_per_campaign(pool):
    async with pool.acquire() as c:
        await _plan(c)
        with pytest.raises(repo.PlanExists):
            await _plan(c)


async def test_update_bumps_the_row_version_and_orders_timestamps(pool):
    async with pool.acquire() as c:
        plan = await _plan(c)
        edited = await repo.update_plan(c, plan.id, state="draft", inputs_changed=True)
        assert edited.row_version == 2 and not edited.calc_fresh
        calculated = await repo.update_plan(c, plan.id, state="calculated", calculated=True)
        assert calculated.row_version == 3 and calculated.calc_fresh
        stale = await repo.update_plan(c, plan.id, state="draft", inputs_changed=True)
        assert not stale.calc_fresh


async def test_sheets_round_trip_in_order(pool):
    async with pool.acquire() as c:
        plan = await _plan(c)
        apps = ({"kind": "mineral", "product_rate_kg_ha": 200},)
        await repo.replace_sheets(c, plan.id, [
            _sheet("b", parcels=(("urn:ngsi-ld:AgriParcel:p2", "31:201:0:0:1:123:1"),), apps=apps),
            _sheet("a")])
        sheets = await repo.get_sheets(c, plan.id)
        assert [s.key for s in sheets] == ["b", "a"] and [s.seq for s in sheets] == [0, 1]
        assert sheets[0].parcels == [{"urn": "urn:ngsi-ld:AgriParcel:p2",
                                      "sigpac": "31:201:0:0:1:123:1"}]
        assert sheets[0].applications == [{"kind": "mineral", "product_rate_kg_ha": 200}]
        assert sheets[1].overrides == []


async def test_replacing_keeps_overrides_of_kept_sheets_and_drops_orphans(pool):
    async with pool.acquire() as c:
        plan = await _plan(c)
        await repo.replace_sheets(c, plan.id, [_sheet("a", organic=2), _sheet("b")])
        a, _ = await repo.get_sheets(c, plan.id)
        await repo.set_overrides(c, a.id, [
            {"param": "soil.ph", "value": 7.2, "reason": "lab", "user": "t1", "at": "x"},
            {"param": "organic.1.availability", "value": 0.6, "reason": "own", "user": "u1",
             "at": "x"}])
        dropped = await repo.replace_sheets(c, plan.id, [_sheet("a", organic=1), _sheet("c")])
        assert dropped == ["a:organic.1.availability"]
        sheets = await repo.get_sheets(c, plan.id)
        assert [s.key for s in sheets] == ["a", "c"]
        assert sheets[0].id == a.id
        assert sheets[0].overrides == [{"param": "soil.ph", "value": 7.2, "reason": "lab",
                                        "user": "t1", "at": "x"}]


async def test_results_and_findings_replace_the_previous_ones(pool):
    async with pool.acquire() as c:
        plan = await _plan(c)
        await repo.replace_sheets(c, plan.id, [_sheet("a")])
        (a,) = await repo.get_sheets(c, plan.id)
        await repo.save_results(c, plan.id, [(a.id, {"status": "complete"}, {"mineral_n_kg_ha": 1})],
                                [{"rule_id": "X", "severity": "warn", "params": {}, "sheet_id": a.id}])
        await repo.save_results(c, plan.id, [(a.id, {"status": "incomplete"}, {"mineral_n_kg_ha": 2})],
                                [{"rule_id": "Y", "severity": "block", "params": {"k": 1}}])
        results = await repo.get_results(c, plan.id)
        assert results[a.id]["result"] == {"status": "incomplete"}
        assert results[a.id]["applications_summary"] == {"mineral_n_kg_ha": 2}
        assert [(f["rule_id"], f["severity"], f["sheet_key"]) for f in
                await repo.get_findings(c, plan.id)] == [("Y", "block", None)]


async def test_dropping_a_sheet_drops_its_results(pool):
    async with pool.acquire() as c:
        plan = await _plan(c)
        await repo.replace_sheets(c, plan.id, [_sheet("a")])
        (a,) = await repo.get_sheets(c, plan.id)
        await repo.save_results(c, plan.id, [(a.id, {}, {})], [])
        await repo.replace_sheets(c, plan.id, [_sheet("b")])
        assert await repo.get_results(c, plan.id) == {}


async def test_rain_and_audit(pool):
    async with pool.acquire() as c:
        plan = await _plan(c)
        stored = await repo.set_rain(c, plan.id, {"annual_mm": 600.0})
        assert stored.rain == {"annual_mm": 600.0} and stored.row_version == 2
        await repo.append_audit(c, plan.id, "u1", "create", {"campaign": 2027})
        await repo.append_audit(c, plan.id, "u2", "edit_sheets", {"sheets": ["a"]})
        log = await repo.get_audit(c, plan.id)
        assert [(e["user_id"], e["action"]) for e in log] == [("u1", "create"), ("u2", "edit_sheets")]
        assert log[1]["detail"] == {"sheets": ["a"]}


async def test_a_lock_can_be_taken(pool):
    async with pool.acquire() as c, c.transaction():
        plan = await _plan(c)
        assert (await repo.get_plan(c, T, plan.id, for_update=True)).id == plan.id
    assert isinstance(plan.id, uuid.UUID)
