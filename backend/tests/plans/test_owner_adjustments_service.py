import copy
import uuid
from datetime import date

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.plans import repo, service, signing
from app.plans.states import TransitionError
from tests.fakes import URN, FakeSources, complete_data
from tests.plans.test_signing import (
    APP,
    EARLY,
    FARMER,
    OTHER,
    TECH,
    blocking,
    good_sheet,
    ready,
    sources,
)

ADJ = {"basis": "foliar_analysis", "date": "2026-10-01", "reference": "LAB-77",
       "description": "N deficiency", "justified_n_kg_ha": 400.0}


async def _closed(pool):
    pid, plan = await ready(pool)
    plan = await signing.close(pool, FARMER, pid, plan["row_version"], "titular_sin_obligacion",
                               "Juan", EARLY)
    return pid, plan


async def test_the_signed_version_stays_in_force_while_a_revision_is_drafted(pool):
    pid, plan = await _closed(pool)
    new = await signing.revise(pool, FARMER, pid, plan["row_version"])
    assert (await service.get(pool, FARMER, pid))["state"] == "signed"
    assert (await signing.summary(pool, "tenant-a", URN, 2027))["plan_id"] == str(pid)
    nid = uuid.UUID(new["id"])
    new = await service.calculate_plan(pool, sources(), FARMER, nid, new["row_version"], EARLY)
    new = await signing.close(pool, FARMER, nid, new["row_version"], "titular_sin_obligacion",
                              "Juan", EARLY)
    assert new["state"] == "signed"
    assert (await service.get(pool, FARMER, pid))["state"] == "superseded"
    assert (await signing.summary(pool, "tenant-a", URN, 2027))["plan_id"] == str(nid)
    async with pool.acquire() as c:
        snap = await repo.get_snapshot(c, nid)
    assert snap["plan"]["supersedes"] == str(pid)


async def test_only_one_revision_at_a_time(pool):
    pid, plan = await _closed(pool)
    await signing.revise(pool, FARMER, pid, plan["row_version"])
    again = await service.get(pool, FARMER, pid)
    with pytest.raises(service.Conflict):
        await signing.revise(pool, FARMER, pid, again["row_version"])


async def test_n_adjustment_is_technician_only_and_validated(pool):
    pid, plan = await ready(pool)
    with pytest.raises(TransitionError):
        await service.set_n_adjustment(pool, FARMER, pid, plan["row_version"], "wheat", ADJ)
    with pytest.raises(service.Invalid):
        await service.set_n_adjustment(pool, TECH, pid, plan["row_version"], "wheat",
                                       {**ADJ, "date": "2999-01-01"})
    done = await service.set_n_adjustment(pool, TECH, pid, plan["row_version"], "wheat", ADJ)
    (sheet,) = done["sheets"]
    assert sheet["n_adjustment"]["justified_n_kg_ha"] == 400.0
    assert sheet["n_adjustment"]["user"] == "u-tech"
    assert done["calc_fresh"] is False
    gone = await service.set_n_adjustment(pool, TECH, pid, done["row_version"], "wheat", None)
    assert gone["sheets"][0]["n_adjustment"] is None


async def test_qualified_holder_needs_a_recorded_qualification(pool):
    pid, plan = await ready(pool)
    with pytest.raises(service.Invalid):
        await signing.close(pool, FARMER, pid, plan["row_version"], "titular_cualificado",
                            "Juan", EARLY)
    with pytest.raises(TransitionError):
        await signing.put_holder_qualification(pool, FARMER, "Juan", "Ing. Agrónomo", "COIA 1")
    await signing.put_holder_qualification(pool, TECH, "Juan Pérez", "Ingeniero Agrónomo",
                                           "COIA 123")
    assert (await signing.get_holder_qualification(pool, FARMER))["reference"] == "COIA 123"
    closed = await signing.close(pool, FARMER, pid, plan["row_version"], "titular_cualificado",
                                 "Juan Pérez", EARLY)
    q = closed["signature"]["qualification"]
    assert {k: q[k] for k in ("holder_name", "qualification", "reference")} == {
        "holder_name": "Juan Pérez", "qualification": "Ingeniero Agrónomo",
        "reference": "COIA 123"}
    assert q["updated_by"] == "u-tech" and q["updated_at"]


async def test_a_2028_plan_closed_before_the_deadline_still_needs_advice(pool):
    # Owner 2026-10-13 (decision 2): the period of application counts.
    p = await service.create(pool, FARMER, 2028, "tenant")
    nid = uuid.UUID(p["id"])
    sheet = good_sheet()
    sheet = repo.SheetData(sheet.key, {**sheet.inputs, "campaign": 2028, "crop_eppo": "TRZAX"},
                           sheet.parcels, sheet.applications)
    p = await service.edit_sheets(pool, FARMER, nid, p["row_version"], [sheet])
    async with pool.acquire() as c:
        await repo.set_rain(c, nid, {"annual_mm": 600.0, "years": [2016]})
    p = await service.get(pool, FARMER, nid)
    p = await service.calculate_plan(pool, sources(), FARMER, nid, p["row_version"], EARLY)
    with pytest.raises(TransitionError) as err:
        await signing.close(pool, FARMER, nid, p["row_version"], "titular_sin_obligacion",
                            "Juan", date(2027, 8, 31))
    assert err.value.code == "advice_required"


async def test_n_adjustment_stores_only_the_known_fields(pool):
    pid, plan = await ready(pool)
    with pytest.raises(service.Invalid):
        await service.set_n_adjustment(pool, TECH, pid, plan["row_version"], "wheat", [ADJ])
    done = await service.set_n_adjustment(pool, TECH, pid, plan["row_version"], "wheat",
                                          {**ADJ, "extra": "x", "user": "spoof"})
    stored = done["sheets"][0]["n_adjustment"]
    assert set(stored) == {"basis", "date", "reference", "description", "justified_n_kg_ha",
                           "scope", "user", "at"}
    assert stored["scope"]["parcels"] == [URN]
    assert stored["user"] == "u-tech"


async def test_the_signer_must_be_the_recorded_qualified_holder(pool):
    pid, plan = await ready(pool)
    await signing.put_holder_qualification(pool, TECH, "Juan  Pérez", "Ingeniero Agrónomo",
                                           "COIA 123")
    before = (await service.get(pool, FARMER, pid))["row_version"]
    with pytest.raises(service.Invalid):
        await signing.close(pool, FARMER, pid, plan["row_version"], "titular_cualificado",
                            "Pedro Gómez", EARLY)
    assert (await service.get(pool, FARMER, pid))["row_version"] == before
    closed = await signing.close(pool, FARMER, pid, plan["row_version"], "titular_cualificado",
                                 " juan pérez ", EARLY)
    assert closed["state"] == "signed"


def test_a_deadlock_is_a_409_conflict():
    app = create_app()

    @app.get("/boom")
    async def boom():
        raise asyncpg.exceptions.DeadlockDetectedError("deadlock detected")

    r = TestClient(app).get("/boom", headers={"X-Tenant-ID": "tenant-a"})
    assert r.status_code == 409
    assert r.json() == {"error": "conflict", "detail": "concurrent change, retry"}


URN2 = "urn:ngsi-ld:AgriParcel:p2"
HEAVY = {**APP, "n_pct": 27, "n_form": "nitric", "product_rate_kg_ha": 1500}   # far over the limit


def two_parcel_sources():
    data = complete_data()
    data["parcels"][URN]["area"] = 12.0
    data["parcels"][URN2] = {**copy.deepcopy(data["parcels"][URN]), "id": URN2}
    data["timelines"][URN2] = copy.deepcopy(data["timelines"][URN])
    data["analyses"][URN2] = copy.deepcopy(data["analyses"][URN])
    return FakeSources(**data)


def sheet_of(parcels, apps=(HEAVY,)):
    base = good_sheet(apps)
    return repo.SheetData(base.key, base.inputs, tuple((u, "31201A00100123") for u in parcels),
                          base.applications)


async def _recalc(pool, pid, src):
    cur = await service.get(pool, FARMER, pid)
    return await service.calculate_plan(pool, src, FARMER, pid, cur["row_version"], EARLY)


async def _over_limit_plan(pool, parcels=(URN,)):
    plan = await service.create(pool, FARMER, 2027, "tenant")
    pid = uuid.UUID(plan["id"])
    await service.edit_sheets(pool, FARMER, pid, plan["row_version"], [sheet_of(parcels)])
    async with pool.acquire() as c:
        await repo.set_rain(c, pid, {"annual_mm": 600.0, "years": [2016]})
    return pid, await _recalc(pool, pid, two_parcel_sources())


async def test_an_adjustment_does_not_follow_a_rewritten_sheet(pool):
    pid, plan = await _over_limit_plan(pool)
    assert "ES-RD1051-AIII-3-N" in blocking(plan)
    huge = {**ADJ, "justified_n_kg_ha": 5000.0}
    plan = await service.set_n_adjustment(pool, TECH, pid, plan["row_version"], "wheat", huge)
    assert plan["sheets"][0]["n_adjustment"]["scope"]["parcels"] == [URN]
    plan = await _recalc(pool, pid, two_parcel_sources())
    assert "ES-RD1051-AIII-3-N" not in blocking(plan)
    assert any(f["rule_id"] == "ES-RD1051-AIII-3-N-adjusted" for f in plan["findings"])
    # the farmer adds a parcel the technician never saw: the justification no longer counts
    plan = await service.edit_sheets(pool, FARMER, pid, plan["row_version"],
                                     [sheet_of((URN, URN2))])
    assert plan["sheets"][0]["n_adjustment"] is not None        # kept in storage…
    plan = await _recalc(pool, pid, two_parcel_sources())
    assert "ES-RD1051-AIII-3-N" in blocking(plan)               # …but the rule ignores it
    assert all(f["rule_id"] != "ES-RD1051-AIII-3-N-adjusted" for f in plan["findings"])


async def test_an_adjustment_needs_a_calculated_sheet(pool):
    plan = await service.create(pool, FARMER, 2027, "tenant")
    pid = uuid.UUID(plan["id"])
    plan = await service.edit_sheets(pool, FARMER, pid, plan["row_version"], [sheet_of((URN,))])
    with pytest.raises(service.Invalid, match="calculate the plan"):
        await service.set_n_adjustment(pool, TECH, pid, plan["row_version"], "wheat", ADJ)


async def test_an_adjustment_from_another_campaign_is_refused(pool):
    pid, plan = await ready(pool)
    with pytest.raises(service.Invalid):
        await service.set_n_adjustment(pool, TECH, pid, plan["row_version"], "wheat",
                                       {**ADJ, "date": "2019-05-01"})


async def test_removing_a_missing_adjustment_is_not_found_and_writes_nothing(pool):
    pid, plan = await ready(pool)
    with pytest.raises(service.NotFound, match="no N adjustment on sheet wheat"):
        await service.set_n_adjustment(pool, TECH, pid, plan["row_version"], "wheat", None)
    after = await service.get(pool, FARMER, pid)
    assert after["row_version"] == plan["row_version"]


async def test_another_tenants_technician_cannot_adjust(pool):
    pid, plan = await ready(pool)
    stranger = service.Actor("tenant-b", "u-x", frozenset({"TechnicalConsultant"}))
    with pytest.raises(service.NotFound):
        await service.set_n_adjustment(pool, stranger, pid, plan["row_version"], "wheat", ADJ)
    assert OTHER.tenant_id == "tenant-b"


async def test_a_refused_close_of_a_revision_changes_nothing(pool):
    pid, _ = await _closed(pool)
    v1 = await service.get(pool, FARMER, pid)
    new = await signing.revise(pool, FARMER, pid, v1["row_version"])
    nid = uuid.UUID(new["id"])
    v1 = await service.get(pool, FARMER, pid)
    new = await service.get(pool, FARMER, nid)
    # an ureic application over 12.3's limit blocks the close
    bad = {**APP, "n_pct": 46, "n_ureic_pct": 46, "n_form": "ureic"}
    new = await service.edit_sheets(pool, FARMER, nid, new["row_version"],
                                    [good_sheet((bad,))])
    new = await service.calculate_plan(pool, sources(), FARMER, nid, new["row_version"], EARLY)
    assert blocking(new)
    with pytest.raises(TransitionError):
        await signing.close(pool, FARMER, nid, new["row_version"], "titular_sin_obligacion",
                            "Juan", EARLY)
    v1_after = await service.get(pool, FARMER, pid)
    new_after = await service.get(pool, FARMER, nid)
    assert v1_after["state"] == "signed" and v1_after["row_version"] == v1["row_version"]
    assert new_after["state"] == new["state"] and new_after["row_version"] == new["row_version"]


async def test_p_and_k_history_reads_the_signed_version_while_a_revision_is_open(pool):
    pid, plan = await _closed(pool)
    await signing.revise(pool, FARMER, pid, plan["row_version"])
    async with pool.acquire() as c:
        snaps = await repo.signed_snapshots(c, "tenant-a", "tenant", [2027])
    assert snaps[2027]["plan"]["id"] == str(pid)


async def test_a_revision_whose_base_is_no_longer_signed_is_a_conflict(pool):
    pid, plan = await _closed(pool)
    new = await signing.revise(pool, FARMER, pid, plan["row_version"])
    nid = uuid.UUID(new["id"])
    new = await service.calculate_plan(pool, sources(), FARMER, nid, new["row_version"], EARLY)
    async with pool.acquire() as c:
        await c.execute("UPDATE fast.plans SET state = 'superseded' WHERE id = $1", pid)
    with pytest.raises(service.Conflict):
        await signing.close(pool, FARMER, nid, new["row_version"], "titular_sin_obligacion",
                            "Juan", EARLY)
