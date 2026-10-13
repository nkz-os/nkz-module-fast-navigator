from app.plans import document, repo, signing
from tests.plans.test_signing import EARLY, FARMER, ready


async def test_live_and_signed_documents_have_the_same_shape(pool):
    pid, plan = await ready(pool)
    async with pool.acquire() as c:
        live = await document.plan_document(c, await repo.get_plan(c, "tenant-a", pid))
    assert live["live"] is True and live["state"] == "calculated"
    assert live["sheets"][0]["result"]["status"] == "complete"
    assert live["signature"] is None and live["signed_at"] is None
    assert not any(f["rule_id"].startswith("FAST-split-") for f in live["findings"])
    assert all("citation" in f for f in live["findings"])
    await signing.close(pool, FARMER, pid, plan["row_version"], "titular_sin_obligacion",
                        "Juan", EARLY)
    async with pool.acquire() as c:
        signed = await document.plan_document(c, await repo.get_plan(c, "tenant-a", pid))
    assert signed["live"] is False and signed["state"] == "signed"
    assert len(signed["snapshot_sha256"]) == 64 and signed["signed_at"]
    keys = {"plan", "declarations", "rain", "sheets", "findings", "versions", "signature"}
    assert keys <= set(live) and keys <= set(signed)
    assert set(live["sheets"][0]) >= {"key", "inputs", "parcels", "applications", "result",
                                      "applications_summary", "n_adjustment"}
    assert set(signed["sheets"][0]) >= set(live["sheets"][0]) - {"overrides"}
