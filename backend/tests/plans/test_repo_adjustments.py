import datetime

import asyncpg
import pytest

from app.plans import repo

T = "tenant-a"


def _now():
    return datetime.datetime.now(datetime.UTC)


async def _plan(c, state=None, version=1, supersedes=None):
    plan = await repo.create_plan(c, tenant_id=T, farm="tenant", campaign=2027, user_id="u",
                                  version=version, supersedes=supersedes)
    if state == "signed":
        await repo.sign_plan(c, plan.id, signature={"kind": "advisor"}, snapshot={"s": 1},
                             sha256="ab" * 32, signed_at=_now())
    return plan


async def test_one_open_and_one_signed_plan_per_campaign(pool):
    async with pool.acquire() as c:
        first = await _plan(c, state="signed")
        draft = await _plan(c, version=2, supersedes=first.id)       # revision while signed
        with pytest.raises(repo.PlanExists):
            await _plan(c, version=3, supersedes=first.id)           # a second open plan
        await repo.update_plan(c, draft.id, state="in_review")
        with pytest.raises(asyncpg.UniqueViolationError):            # two signed at once
            await repo.sign_plan(c, draft.id, signature={"kind": "advisor"}, snapshot={"s": 2},
                                 sha256="cd" * 32, signed_at=_now())


async def test_n_adjustment_is_stored_and_copied(pool):
    async with pool.acquire() as c:
        plan = await _plan(c)
        await repo.replace_sheets(c, plan.id, [repo.SheetData("wheat", {"organic": []}, (), ())])
        (s,) = await repo.get_sheets(c, plan.id)
        assert s.n_adjustment is None
        adj = {"basis": "foliar_analysis", "justified_n_kg_ha": 200.0}
        await repo.set_n_adjustment(c, s.id, adj)
        (s,) = await repo.get_sheets(c, plan.id)
        assert s.n_adjustment == adj
        await repo.replace_sheets(c, plan.id, [repo.SheetData("wheat", {"organic": []}, (), ())])
        assert (await repo.get_sheets(c, plan.id))[0].n_adjustment == adj   # kept with the key
        other = await repo.create_plan(c, tenant_id="tenant-b", farm="tenant", campaign=2027,
                                       user_id="u")
        await repo.copy_plan_inputs(c, plan.id, other.id)
        assert (await repo.get_sheets(c, other.id))[0].n_adjustment == adj
        await repo.set_n_adjustment(c, s.id, None)
        assert (await repo.get_sheets(c, plan.id))[0].n_adjustment is None


async def test_holder_qualification(pool):
    async with pool.acquire() as c:
        assert await repo.get_holder_qualification(c, T) is None
        await repo.put_holder_qualification(c, T, "Juan Pérez", "Ingeniero Agrónomo", "COIA 123",
                                            "u-tech")
        q = await repo.put_holder_qualification(c, T, "Juan Pérez", "Ingeniero Agrónomo",
                                                "COIA 124", "u-tech")
        assert q == {"holder_name": "Juan Pérez", "qualification": "Ingeniero Agrónomo",
                     "reference": "COIA 124"}
        assert await repo.get_holder_qualification(c, "tenant-b") is None
        got = await repo.get_holder_qualification(c, T)
        assert got["updated_by"] == "u-tech" and got["reference"] == "COIA 124"
        datetime.datetime.fromisoformat(got["updated_at"])         # an ISO string
