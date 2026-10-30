"""Read-only nutrient status of a parcel, for in-cluster consumers (no recalculation).

Reads what is already stored: the frozen snapshot of a signed plan, or the stored
`results` of an open plan whose calculation is fresh. Nothing is recomputed and no
value is defaulted: what the result does not carry comes out as null / "missing".
"""
from __future__ import annotations

import asyncpg

from app.plans import repo

UNITS = {"n": "kg N/ha", "p2o5": "kg P2O5/ha", "k2o": "kg K2O/ha",
         "p_olsen": "mg P/kg (Olsen eq.)", "k": "mg K/kg (NH4OAc)"}

_OPEN = ("calculated", "in_review", "draft")


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _sourced(inputs: dict, name: str) -> dict:
    item = inputs.get(name) or {}
    return {"value": item.get("value"), "provenance": item.get("provenance") or "missing",
            "source": item.get("source")}


def _sheet_view(key: str, result: dict | None) -> dict:
    """One sheet; `result: None` means the sheet has no usable stored calculation."""
    if result is None:
        return {"key": key, "result": None, "crop_eppo": None, "status": None,
                "provisional": None, "n_kg_ha": None, "p2o5_kg_ha": None, "k2o_kg_ha": None,
                "soil": None, "missing": []}
    inputs = result.get("inputs") or {}
    n = result.get("n")
    p2o5, k2o = result.get("p2o5"), result.get("k2o")
    analysis = inputs.get("soil.analysis_id") or {}
    return {
        "key": key,
        "crop_eppo": (inputs.get("crop.eppo") or {}).get("value"),
        "status": result.get("status"),
        "provisional": result.get("provisional"),
        "n_kg_ha": ({"min": n.get("min_kg_ha"), "avg": n.get("avg_kg_ha"),
                     "max": n.get("max_kg_ha")} if n else None),
        "p2o5_kg_ha": p2o5.get("rate_kg_ha") if p2o5 else None,
        "k2o_kg_ha": k2o.get("rate_kg_ha") if k2o else None,
        "soil": {"analysis_id": analysis.get("value"),
                 "sampling_date": analysis.get("sampling_date"),
                 "p_olsen_mg_kg": _sourced(inputs, "soil.p_olsen_mg_kg"),
                 "p_threshold_mg_kg": p2o5.get("threshold_mg_kg") if p2o5 else None,
                 "k_mg_kg": _sourced(inputs, "soil.k_mg_kg"),
                 "k_threshold_mg_kg": k2o.get("threshold_mg_kg") if k2o else None,
                 "mineral_n_kg_ha": _sourced(inputs, "soil.mineral_n_kg_ha")},
        "missing": [m.get("field") for m in result.get("missing") or []],
    }


def _response(parcel_urn: str, campaign: int, plan: repo.PlanRow | None,
              sheets: list[dict]) -> dict:
    versions = {"engine": None, "calc": None}
    for s in sheets:
        v = (s.pop("_versions", None) or {})
        if v.get("engine") is not None and versions["engine"] is None:
            versions = {"engine": v.get("engine"), "calc": v.get("calc")}
    return {
        "parcel_id": parcel_urn, "campaign": campaign,
        "plan": None if plan is None else {
            "id": str(plan.id), "version": plan.version, "state": plan.state,
            "calc_fresh": plan.calc_fresh, "calculated_at": _iso(plan.calculated_at),
            "signed_at": _iso(plan.signed_at)},
        "sheets": sheets, "units": UNITS, "versions": versions,
    }


async def _candidate_plans(conn: asyncpg.Connection, tenant_id: str, parcel_urn: str,
                           campaign: int) -> list[repo.PlanRow]:
    rows = await conn.fetch(
        f"SELECT {repo._PLAN_COLUMNS} FROM plans WHERE tenant_id = $1 AND campaign = $2 "
        "AND state = ANY($4::text[]) AND id IN (SELECT s.plan_id FROM crop_sheets s "
        "JOIN sheet_parcels sp ON sp.sheet_id = s.id WHERE sp.parcel_urn = $3) "
        "ORDER BY updated_at DESC, id", tenant_id, campaign, parcel_urn,
        ["signed", *_OPEN])
    return [repo._plan(r) for r in rows]


def _pick(plans: list[repo.PlanRow]) -> repo.PlanRow | None:
    for plan in plans:
        if plan.state == "signed":
            return plan
    for plan in plans:
        if plan.state in ("calculated", "in_review") and plan.calc_fresh:
            return plan
    return plans[0] if plans else None


async def nutrient_status(pool: asyncpg.Pool, tenant_id: str, parcel_urn: str,
                          campaign: int) -> dict:
    async with pool.acquire() as conn:
        plan = _pick(await _candidate_plans(conn, tenant_id, parcel_urn, campaign))
        if plan is None:
            return _response(parcel_urn, campaign, None, [])
        if plan.state == "signed":
            snapshot = await repo.get_snapshot(conn, plan.id) or {}
            raw = [(s["key"], s.get("result"), s.get("parcels") or [])
                   for s in snapshot.get("sheets") or []]
            raw = [(k, r, [p["urn"] for p in ps]) for k, r, ps in raw]
        else:
            sheets = await repo.get_sheets(conn, plan.id)
            stored = await repo.get_results(conn, plan.id) if plan.calc_fresh else {}
            raw = [(s.key, (stored.get(s.id) or {}).get("result"),
                    [p["urn"] for p in s.parcels]) for s in sheets]
    views = []
    for key, result, urns in raw:
        if parcel_urn not in urns:
            continue
        view = _sheet_view(key, result)
        view["_versions"] = (result or {}).get("versions")
        views.append(view)
    return _response(parcel_urn, campaign, plan, views)
