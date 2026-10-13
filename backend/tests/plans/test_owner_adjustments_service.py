import uuid
from datetime import date

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.plans import repo, service, signing
from app.plans.states import TransitionError
from tests.fakes import URN
from tests.plans.test_signing import EARLY, FARMER, TECH, good_sheet, ready, sources

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
    assert closed["signature"]["qualification"] == {
        "holder_name": "Juan Pérez", "qualification": "Ingeniero Agrónomo",
        "reference": "COIA 123"}


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
                           "user", "at"}
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
