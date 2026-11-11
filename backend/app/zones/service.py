"""Nitrogen dose per zone for one parcel of a plan sheet (stateless: nothing is stored).

Reads the stored plan (sheet, calculated result, planned applications) and, through the sources,
the parcel's zones from the broker. See the contract in the module's spec (route `zone-doses`).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date

import asyncpg

from app.inputs.organic import OrganicApplication
from app.plans import repo
from app.plans.applications import ApplicationIn, nutrients
from app.plans.service import Actor, Invalid, NotFound, _area, _load
from app.zones.doses import ZoneInput, distribute
from app.zones.read import ZoneRead, ZoningRead, select_zoning

logger = logging.getLogger(__name__)

VERSION = "1.0.0"
IMAGE_MAX_AGE_DAYS = 30
COVER_TOLERANCE = 0.01          # share of the parcel area below which a gap is not reported


@dataclass(frozen=True)
class Product:
    name: str
    n_pct: float


@dataclass(frozen=True)
class Target:
    """What the technician confirmed: a dose of N (optionally with its product), or the index
    (0-based, the order of the sheet's applications) of a planned application."""
    n_kg_ha: float | None = None
    product: Product | None = None
    application_seq: int | None = None


def _notice(code: str, **params) -> dict:
    return {"code": code, "params": params}


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def _resolve_target(sheet: repo.SheetRow, target: Target) -> tuple[float | None, str,
                                                                    Product | None]:
    """(N kg/ha or None when the application brings none, source, product)."""
    if target.application_seq is None:
        return target.n_kg_ha, "given", target.product
    seq = target.application_seq
    if not 0 <= seq < len(sheet.applications):
        raise Invalid(f"application_seq {seq} is not an application of sheet {sheet.key} "
                      f"(it has {len(sheet.applications)})")
    organic = [OrganicApplication(**o) for o in sheet.inputs.get("organic") or []]
    app = ApplicationIn.model_validate(sheet.applications[seq])
    n = nutrients(app, organic).n_kg_ha
    product = Product(app.product_name, app.n_pct) \
        if app.kind != "organic" and app.n_pct else None
    return (n if n > 0 else None), "application", product


def _unavailable(strategy: str, n_fixing: bool | None, target_n: float | None,
                 zones: tuple[ZoneRead, ...]) -> str | None:
    if strategy == "uniform":
        return None
    if n_fixing is True:
        return "n_fixing_crop"
    if n_fixing is None:
        return "n_fixing_unknown"
    if target_n is None:
        return "no_target_n"
    if len(zones) < 2:
        return "single_zone"
    if any(z.area_ha is None for z in zones):
        return "zone_without_area"
    if sum(1 for z in zones if z.mean_value is not None) < 2:
        return "zoning_without_vegetation_value"
    return None


def _age_notice(zoning: ZoningRead, today: date) -> dict | None:
    if zoning.method != "vegetationIndex" or not zoning.date:
        return None
    try:
        days = (today - date.fromisoformat(zoning.date)).days
    except ValueError:
        return None
    return _notice("zoning_image_old", date=zoning.date, days=days) \
        if days > IMAGE_MAX_AGE_DAYS else None


def _ordered(zones: tuple[ZoneRead, ...]) -> list[ZoneRead]:
    return sorted(zones, key=lambda z: (z.rank is None, z.rank or 0, z.id))


async def zone_doses(pool: asyncpg.Pool, sources, actor: Actor, plan_id: uuid.UUID,
                     sheet_key: str, *, parcel_urn: str, zoning_run_id: str, strategy: str,
                     cap_pct: float, target: Target, today: date) -> dict:
    async with pool.acquire() as conn:
        plan = await _load(conn, actor, plan_id)
        sheets = await repo.get_sheets(conn, plan.id)
        results = await repo.get_results(conn, plan.id)
    sheet = next((s for s in sheets if s.key == sheet_key), None)
    if sheet is None:
        raise NotFound(f"sheet {sheet_key}")
    if parcel_urn not in {p["urn"] for p in sheet.parcels}:
        raise Invalid(f"parcel {parcel_urn} is not in sheet {sheet_key}")
    stored = results.get(sheet.id)
    if stored is None:
        raise Invalid("calculate the plan before sharing a dose by zones")
    result = stored["result"]

    target_n, target_source, product = _resolve_target(sheet, target)

    zoning = select_zoning(await sources.zone_entities(parcel_urn), parcel_urn, zoning_run_id)
    if zoning is None:
        raise NotFound(f"zoning {zoning_run_id} of parcel {parcel_urn}")
    zones = _ordered(zoning.zones)

    inputs = result.get("inputs") or {}
    n_fixing = (inputs.get("crop.n_fixing") or {}).get("value")
    n_fixing = n_fixing if isinstance(n_fixing, bool) else None
    reason = _unavailable(strategy, n_fixing, target_n, tuple(zones))
    effective = "uniform" if reason else strategy

    notices: list[dict] = []
    if not plan.calc_fresh:
        notices.append(_notice("plan_calculation_stale"))
    doses: dict[str, tuple[float | None, float | None, bool, float | None]] = {}
    saturated = False
    if effective == "uniform":
        for z in zones:
            doses[z.id] = (None, 1.0, False, target_n)
    else:
        dist = distribute([ZoneInput(z.id, z.area_ha, z.mean_value) for z in zones], effective,
                          cap_pct, target_n)
        saturated = dist.saturated
        for d in dist.zones:
            doses[d.key] = (d.relative_vigor, d.factor, d.capped, d.n_kg_ha)
        age = _age_notice(zoning, today)
        if age:
            notices.append(age)
    if saturated:
        notices.append(_notice("cap_saturated", cap_pct=cap_pct))

    def product_rate(n: float | None) -> float | None:
        return None if n is None or product is None else n / (product.n_pct / 100.0)

    rows = []
    for z in zones:
        vigor, factor, capped, n = doses[z.id]
        missing = [p for p in z.problems if p == "area_ha" or strategy != "uniform"]
        if strategy != "uniform" and z.mean_value is None and "mean_value_invalid" not in missing:
            missing.append("mean_value")
        shared = effective != "uniform" and factor is not None
        rows.append({
            "zone_id": z.id, "label": z.label, "rank": z.rank, "area_ha": _round(z.area_ha, 4),
            "basis": "vigor" if shared else "sheet",
            "relative_vigor": _round(vigor, 4), "factor": _round(factor, 4), "capped": capped,
            "n_kg_ha": _round(n, 2), "product_kg_ha": _round(product_rate(n), 2),
            "soil_analysis": None, "missing": missing})

    areas = [z.area_ha for z in zones]
    parcel_area = _area(result, parcel_urn)
    all_areas = all(a is not None for a in areas)
    zones_area = sum(areas) if all_areas else None
    rest_area: float | None = None
    if parcel_area is None:
        notices.append(_notice("parcel_area_unknown"))
    elif zones_area is not None:
        gap = parcel_area - zones_area
        if gap > COVER_TOLERANCE * parcel_area:
            rest_area = gap
            notices.append(_notice("zones_do_not_cover_parcel", rest_ha=round(gap, 4),
                                   parcel_ha=round(parcel_area, 4)))
        else:
            rest_area = 0.0
            if -gap > COVER_TOLERANCE * parcel_area:
                notices.append(_notice("zones_exceed_parcel", zones_ha=round(zones_area, 4),
                                       parcel_ha=round(parcel_area, 4)))
    rest = {"area_ha": _round(rest_area, 4), "n_kg_ha": _round(target_n, 2),
            "product_kg_ha": _round(product_rate(target_n), 2)}

    totals = {"area_ha": None, "n_kg": None, "mean_n_kg_ha": None, "uniform_n_kg": None}
    if zones_area is not None:
        area = zones_area + (rest_area or 0.0)
        totals["area_ha"] = _round(area, 4)
        if target_n is not None:
            n_kg = sum(doses[z.id][3] * z.area_ha for z in zones) + target_n * (rest_area or 0.0)
            totals.update(n_kg=_round(n_kg, 2), mean_n_kg_ha=_round(n_kg / area, 2),
                          uniform_n_kg=_round(target_n * area, 2))
            if n_kg > target_n * area * (1 + 1e-9):
                notices.append(_notice("total_above_planned"))

    n = result.get("n")
    cap = cap_pct / 100.0
    logger.info("zone doses tenant=%s plan=%s sheet=%s parcel=%s run=%s strategy=%s effective=%s "
                "reason=%s zones=%d", actor.tenant_id, plan.id, sheet_key, parcel_urn,
                zoning_run_id, strategy, effective, reason, len(zones))
    return {
        "plan": {"id": str(plan.id), "state": plan.state, "campaign": plan.campaign},
        "sheet": {"key": sheet.key,
                  "n_kg_ha": ({"min": n["min_kg_ha"], "avg": n["avg_kg_ha"],
                               "max": n["max_kg_ha"]} if n else None),
                  "crop": {"eppo": (inputs.get("crop.eppo") or {}).get("value"),
                           "n_fixing": n_fixing}},
        "zoning": {"run_id": zoning.run_id, "method": zoning.method,
                   "variable": zoning.variable, "date": zoning.date, "zone_count": len(zones)},
        "strategy": strategy, "strategy_unavailable": reason,
        "target": {"n_kg_ha": _round(target_n, 2), "source": target_source,
                   "product": ({"name": product.name, "n_pct": product.n_pct}
                               if product else None)},
        "cap": {"pct": cap_pct,
                "min_n_kg_ha": _round(None if target_n is None else target_n * (1 - cap), 2),
                "max_n_kg_ha": _round(None if target_n is None else target_n * (1 + cap), 2)},
        "zones": rows, "rest": rest, "totals": totals, "notices": notices,
        "units": {"n": "kg N/ha", "product": "kg/ha"},
        "versions": {"zone_doses": VERSION,
                     **{k: result["versions"].get(k) for k in ("engine", "calc")
                        if k in (result.get("versions") or {})}},
    }
