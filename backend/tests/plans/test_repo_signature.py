from datetime import UTC, datetime

import asyncpg
import pytest

from app.plans import repo

T = "tenant-a"


async def _signed(c, campaign=2027, farm="tenant"):
    plan = await repo.create_plan(c, tenant_id=T, farm=farm, campaign=campaign, user_id="u1")
    await repo.replace_sheets(c, plan.id, [repo.SheetData(
        "wheat", {"campaign": campaign, "organic": []}, (("urn:ngsi-ld:AgriParcel:p1", None),),
        ({"kind": "mineral"},))])
    (sheet,) = await repo.get_sheets(c, plan.id)
    await repo.save_results(c, plan.id, [(sheet.id, {"status": "complete"}, {"n": 1},
                                          {"campaign": campaign})], [])
    return await repo.sign_plan(c, plan.id, signature={"kind": "advisor", "name": "A"},
                                snapshot={"campaign": campaign, "sheets": [{"key": "wheat"}]},
                                sha256="ab" * 32,
                                signed_at=datetime.now(UTC))


async def test_declarations_are_stored_and_mark_inputs_changed(pool):
    async with pool.acquire() as c:
        plan = await repo.create_plan(c, tenant_id=T, farm="tenant", campaign=2027, user_id="u1")
        assert plan.vulnerable_zone is None and plan.voluntary_digital_notebook is False
        calc = await repo.update_plan(c, plan.id, state="calculated", calculated=True)
        assert calc.calc_fresh
        d = await repo.set_declarations(c, plan.id, vulnerable_zone=False,
                                        vulnerable_zone_source="regional order 2023",
                                        voluntary_digital_notebook=True)
        assert (d.vulnerable_zone, d.vulnerable_zone_source, d.voluntary_digital_notebook) == (
            False, "regional order 2023", True)
        assert d.row_version == calc.row_version + 1 and not d.calc_fresh


async def test_results_keep_the_assembled_inputs(pool):
    async with pool.acquire() as c:
        plan = await repo.create_plan(c, tenant_id=T, farm="tenant", campaign=2027, user_id="u1")
        await repo.replace_sheets(c, plan.id, [repo.SheetData("a", {"organic": []}, (), ())])
        (s,) = await repo.get_sheets(c, plan.id)
        await repo.save_results(c, plan.id, [(s.id, {"r": 1}, {"s": 2}, {"campaign": 2027})], [])
        assert (await repo.get_results(c, plan.id))[s.id]["assembled"] == {"campaign": 2027}


async def test_signing_stores_the_copy_and_the_seal(pool):
    async with pool.acquire() as c:
        plan = await _signed(c)
        assert plan.state == "signed" and plan.signed_at is not None
        assert plan.signature == {"kind": "advisor", "name": "A"}
        assert plan.snapshot_sha256 == "ab" * 32
        assert (await repo.get_snapshot(c, plan.id))["sheets"] == [{"key": "wheat"}]


@pytest.mark.parametrize("sql", [
    "UPDATE fast.plans SET rain = '{}'::jsonb WHERE id = $1",
    "UPDATE fast.plans SET snapshot = '{}'::jsonb WHERE id = $1",
    "UPDATE fast.plans SET state = 'draft' WHERE id = $1",
    "UPDATE fast.plans SET created_by = 'x' WHERE id = $1",
    "UPDATE fast.plans SET state = 'superseded', created_by = 'x' WHERE id = $1",
    "UPDATE fast.plans SET state = 'superseded', created_at = now() WHERE id = $1",
    "UPDATE fast.plans SET state = 'superseded', id = gen_random_uuid() WHERE id = $1",
    "UPDATE fast.plans SET created_at = created_at + interval '1 day' WHERE id = $1",
    "UPDATE fast.crop_sheets SET inputs = '{}'::jsonb WHERE plan_id = $1",
    "DELETE FROM fast.crop_sheets WHERE plan_id = $1",
    "DELETE FROM fast.applications WHERE sheet_id IN (SELECT id FROM fast.crop_sheets WHERE plan_id = $1)",
    "UPDATE fast.results SET result = '{}'::jsonb WHERE sheet_id IN (SELECT id FROM fast.crop_sheets WHERE plan_id = $1)",
    "INSERT INTO fast.findings (plan_id, rule_id, severity) VALUES ($1, 'X', 'info')",
])
async def test_a_signed_plan_cannot_change(pool, sql):
    async with pool.acquire() as c:
        plan = await _signed(c)
        with pytest.raises(asyncpg.RaiseError):
            await c.execute(sql, plan.id)


async def test_content_cannot_be_moved_out_of_a_signed_plan(pool):
    async with pool.acquire() as c:
        signed = await _signed(c)
        draft = await repo.create_plan(c, tenant_id=T, farm="other", campaign=2027, user_id="u1")
        await repo.replace_sheets(c, draft.id, [repo.SheetData("w", {"organic": []}, (), ())])
        (draft_sheet,) = await repo.get_sheets(c, draft.id)
        (sheet,) = await repo.get_sheets(c, signed.id)
        for sql, args in [
            ("UPDATE fast.crop_sheets SET plan_id = $2 WHERE id = $1", (sheet.id, draft.id)),
            ("UPDATE fast.applications SET sheet_id = $2 WHERE sheet_id = $1",
             (sheet.id, draft_sheet.id)),
            ("UPDATE fast.sheet_parcels SET sheet_id = $2 WHERE sheet_id = $1",
             (sheet.id, draft_sheet.id)),
            ("UPDATE fast.results SET sheet_id = $2 WHERE sheet_id = $1",
             (sheet.id, draft_sheet.id)),
        ]:
            with pytest.raises(asyncpg.RaiseError):
                await c.execute(sql, *args)


async def test_a_signed_plan_can_only_be_superseded_and_then_never_changes(pool):
    async with pool.acquire() as c:
        plan = await _signed(c)
        gone = await repo.update_plan(c, plan.id, state="superseded")
        assert gone.state == "superseded"
        with pytest.raises(asyncpg.RaiseError):
            await repo.update_plan(c, plan.id, state="superseded")


async def test_copy_inputs_into_a_new_version(pool):
    async with pool.acquire() as c:
        plan = await _signed(c)
        await repo.update_plan(c, plan.id, state="superseded")
        new = await repo.create_plan(c, tenant_id=T, farm="tenant", campaign=2027, user_id="u2",
                                     version=2, supersedes=plan.id,
                                     declarations={"vulnerable_zone": True,
                                                   "vulnerable_zone_source": None,
                                                   "voluntary_digital_notebook": False},
                                     rain={"annual_mm": 600.0})
        await repo.copy_plan_inputs(c, plan.id, new.id)
        sheets = await repo.get_sheets(c, new.id)
        assert [s.key for s in sheets] == ["wheat"]
        assert sheets[0].applications == [{"kind": "mineral"}]
        assert await repo.get_results(c, new.id) == {}
        assert new.vulnerable_zone is True and new.rain == {"annual_mm": 600.0}


async def test_signed_history_and_campaign_lookup(pool):
    async with pool.acquire() as c:
        old = await _signed(c, campaign=2025)
        await _signed(c, campaign=2027)
        assert set(await repo.signed_snapshots(c, T, "tenant", [2024, 2025, 2026])) == {2025}
        assert (await repo.signed_snapshots(c, T, "tenant", [2025]))[2025]["campaign"] == 2025
        assert await repo.signed_snapshots(c, "tenant-b", "tenant", [2025]) == {}
        found = await repo.signed_plans_for_campaign(c, T, 2025)
        assert [p.id for p, _ in found] == [old.id]


async def test_advisor_profile(pool):
    async with pool.acquire() as c:
        assert await repo.get_advisor(c, T, "u-tech") is None
        await repo.put_advisor(c, T, "u-tech", "Ana", "NA-123")
        assert await repo.put_advisor(c, T, "u-tech", "Ana Pérez", "NA-123") == {
            "name": "Ana Pérez", "registration_number": "NA-123"}
        assert await repo.get_advisor(c, "tenant-b", "u-tech") is None


async def test_a_frozen_state_needs_the_signature_the_copy_and_the_seal(pool):
    async with pool.acquire() as c:
        plan = await repo.create_plan(c, tenant_id=T, farm="tenant", campaign=2027, user_id="u1")
        for state in ("signed", "superseded"):
            with pytest.raises(asyncpg.CheckViolationError):
                await c.execute("UPDATE fast.plans SET state = $2 WHERE id = $1", plan.id, state)
        with pytest.raises(asyncpg.CheckViolationError):         # one column missing
            await c.execute(
                "UPDATE fast.plans SET state = 'signed', signature = '{}', snapshot = '{}', "
                "snapshot_sha256 = 'x' WHERE id = $1", plan.id)
        await c.execute(
            "UPDATE fast.plans SET state = 'signed', signature = '{}', snapshot = '{}', "
            "snapshot_sha256 = 'x', signed_at = now() WHERE id = $1", plan.id)


async def test_a_plan_is_never_deleted(pool):
    async with pool.acquire() as c:
        plan = await repo.create_plan(c, tenant_id=T, farm="tenant", campaign=2027, user_id="u1")
        with pytest.raises(asyncpg.RaiseError, match="never deleted"):
            await c.execute("DELETE FROM fast.plans WHERE id = $1", plan.id)
        assert await repo.get_plan(c, T, plan.id) is not None


async def test_the_content_guard_waits_for_a_racing_signature(pool):
    async with pool.acquire() as c:
        source = await c.fetchval(
            "SELECT pg_get_functiondef('fast.guard_signed_content'::regproc)")
    assert "FOR SHARE" in source
