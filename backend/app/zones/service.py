"""Nitrogen dose per zone for one parcel of a plan sheet (stateless: nothing is stored).

Reads the stored plan (sheet, calculated result, planned applications) and, through the sources,
the parcel's zones from the broker. See the contract in the module's spec (route `zone-doses`).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, replace
from datetime import date

import asyncpg

from app.calc.assemble import assemble
from app.calc.sheet import calculate
from app.inputs.organic import OrganicApplication
from app.inputs.provenance import MEASURED, Sourced
from app.plans import repo
from app.plans.applications import ApplicationIn, nutrients
from app.plans.service import Actor, Invalid, NotFound, _area, _load, _request
from app.zones.doses import ZoneInput, distribute
from app.zones.read import ZoneRead, ZoningRead, attr, select_zoning, zonings_of
from app.zones.soil import ZoneSoil, assign_analyses, zone_soil

logger = logging.getLogger(__name__)

VERSION = "1.1.0"
IMAGE_MAX_AGE_DAYS = 30
INPUTS_TOLERANCE = 0.5          # kg/ha: P2O5/K2O drift beyond which the stored sheet is out of date
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
    if zoning.method == "vegetationIndex":
        image = zoning.date
    elif zoning.method == "vegetationIndexMultiDate":
        image = zoning.image_date
    else:
        return None
    if not image:
        return None
    try:
        days = (today - date.fromisoformat(image)).days
    except ValueError:
        return None
    return _notice("zoning_image_old", date=image, days=days) \
        if days > IMAGE_MAX_AGE_DAYS else None


def _ordered(zones: tuple[ZoneRead, ...]) -> list[ZoneRead]:
    return sorted(zones, key=lambda z: (z.rank is None, z.rank or 0, z.id))


class _AnalysesOnce:
    """The sources of one request, with the parcel's lab analyses already fetched: `assemble`
    must not ask the soil service again for what the zone assignment just read."""

    def __init__(self, sources, urn: str, analyses: list[dict]):
        self._sources, self._urn, self._analyses = sources, urn, analyses

    async def lab_analyses(self, urn: str) -> list[dict]:
        if urn == self._urn:
            return self._analyses
        return await self._sources.lab_analyses(urn)

    def __getattr__(self, name):
        return getattr(self._sources, name)


def _num(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _has_n_values(analysis: dict) -> bool:
    return any(h.get("nitrateN") is not None or h.get("ammoniumN") is not None
               for h in analysis.get("horizons") or [])


def _soil_view(zs: ZoneSoil, analyses: list[dict], nmin_used: bool) -> dict:
    """Which sample backs the zone. `id` is the first analysis behind P/K (the newest of those
    averaged), else the first one carrying the zone's mineral N on the sheet's date;
    `n_samples` also counts the mineral-N analyses when that is what the zone uses."""
    on_date = [a for a in analyses if nmin_used and zs.nmin_date
               and str(a.get("samplingDate") or "")[:10] == zs.nmin_date and _has_n_values(a)]
    first = zs.analysis_ids[0] if zs.analysis_ids else (on_date[0].get("id") if on_date else None)
    return {"id": first, "date": zs.date or (zs.nmin_date if nmin_used else None),
            "n_samples": max(zs.n_samples, len(on_date)),
            "p_date": zs.p_date, "k_date": zs.k_date}


def _zone_oxides(assembled, zone_soils: dict[str, ZoneSoil], protected: set[str],
                 failed: list[str], where: str) -> dict[str, tuple[float | None, float | None]]:
    """P2O5 and K2O kg/ha per zone with its own P or K: the sheet's calculation rerun over the
    sheet's own assembled inputs with only the Olsen P and/or the K replaced by the zone's.

    Everything else (texture, pH, crop, yield, organic credit...) stays the parcel's: the zone
    sample changes the fertility reading, not the rest of the sheet. A value the technician
    overrode on the sheet (`protected`) is not replaced.
    """
    out: dict[str, tuple[float | None, float | None]] = {}
    for zid, zs in zone_soils.items():
        values = dict(assembled.soil.values)
        source = "soil:lab-analysis:" + ",".join(zs.analysis_ids)
        own_p = zs.p_olsen_mg_kg is not None and "soil.p_olsen_mg_kg" not in protected
        own_k = zs.k_mg_kg is not None and "soil.k_mg_kg" not in protected
        if not (own_p or own_k):
            continue
        if own_p:
            values["p_olsen_mg_kg"] = Sourced(zs.p_olsen_mg_kg, MEASURED, source)
        if own_k:
            values["k_mg_kg"] = Sourced(zs.k_mg_kg, MEASURED, source)
        try:
            res = calculate(replace(assembled, soil=replace(assembled.soil, values=values)))
        except Exception:
            logger.exception("zone soil calculation failed zone=%s %s", zid, where)
            failed.append(zid)
            continue
        out[zid] = (res.p2o5["rate_kg_ha"] if own_p and res.p2o5 else None,
                    res.k2o["rate_kg_ha"] if own_k and res.k2o else None)
    return out


async def list_zonings(pool: asyncpg.Pool, sources, actor: Actor, plan_id: uuid.UUID,
                       sheet_key: str, *, parcel_urn: str) -> dict:
    """The zonings the parcel has in the broker, most recent first (needs no calculation)."""
    async with pool.acquire() as conn:
        plan = await _load(conn, actor, plan_id)
        sheets = await repo.get_sheets(conn, plan.id)
    sheet = next((s for s in sheets if s.key == sheet_key), None)
    if sheet is None:
        raise NotFound(f"sheet {sheet_key}")
    if parcel_urn not in {p["urn"] for p in sheet.parcels}:
        raise Invalid(f"parcel {parcel_urn} is not in sheet {sheet_key}")
    found = zonings_of(await sources.zone_entities(parcel_urn), parcel_urn)
    return {"zonings": [
        {"run_id": z.run_id, "method": z.method, "variable": z.variable, "date": z.date,
         "image_date": z.image_date, "zone_count": len(z.zones),
         "has_vegetation_value": sum(1 for q in z.zones if q.mean_value is not None) >= 2}
        for z in found]}


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

    # Zone soil: the parcel's analyses, read once, assigned to this zoning's zones. Zone soil only
    # refines the doses: if it cannot be had, the answer is the parcel's (today's), flagged.
    where = f"tenant={actor.tenant_id} plan={plan.id} sheet={sheet_key} parcel={parcel_urn}"
    soil_notices: list[dict] = []
    analyses: list[dict] = []
    by_zone: dict[str, list[dict]] = {}
    outside: list[dict] = []
    soil_ok = True
    try:
        analyses = await sources.lab_analyses(parcel_urn)
        # The analyses the sheet itself was calculated from are the PARCEL's reading: they are
        # not zone samples, however they were georeferenced.
        chosen = {i for i in (
            (inputs.get("soil.analysis_id") or {}).get("value"),
            (inputs.get("soil.nmin_analysis") or {}).get("value"),
            sheet.inputs.get("soil_analysis_id"), sheet.inputs.get("nmin_analysis_id")) if i}
        by_zone, outside = assign_analyses(
            [a for a in analyses if a.get("id") not in chosen], zoning)
    except Exception:
        logger.exception("zone soil unavailable (lab analyses) %s", where)
        soil_ok = False
    nmin_input = inputs.get("soil.nmin_analysis")
    nmin_date = (nmin_input or {}).get("sampling_date") if isinstance(nmin_input, dict) else None
    class_bd = _num((inputs.get("soil.bulk_density_g_cm3") or {}).get("value"))
    zone_soils: dict[str, ZoneSoil] = {z.id: zone_soil(z.id, by_zone[z.id], nmin_date=nmin_date,
                                                       class_bd=class_bd)
                                       for z in zones if z.id in by_zone}
    for zs in zone_soils.values():
        soil_notices.extend(zs.notices)
    own = {zid: zs for zid, zs in zone_soils.items()
           if zs.p_olsen_mg_kg is not None or zs.k_mg_kg is not None or zs.nmin_kg_ha is not None}
    mineral_source = str((inputs.get("soil.mineral_n_kg_ha") or {}).get("source") or "")
    if (nmin_input is None and mineral_source.startswith("soil:lab-analysis:")
            and any(_has_n_values(a) for rows_ in by_zone.values() for a in rows_)):
        # A result stored (with an Nmin analysis chosen) before that analysis' date was recorded.
        soil_notices.append(_notice("zone_nmin_needs_recalculation"))
    if own:
        gone = [z.label or z.id for z in zones if z.id not in own]
        if gone:
            soil_notices.append(_notice("zone_soil_missing", zones=gone))
    n_outside = sum(1 for a in outside if a.get("location") or attr(a, "hasAgriManagementZone"))
    if n_outside:
        soil_notices.append(_notice("zone_soil_outside", n=n_outside))

    # P2O5 and K2O: the parcel's from the stored result, the zones' with their own sample
    # from the sheet rerun once over a single assembly.
    parcel_p = _num((result.get("p2o5") or {}).get("rate_kg_ha"))
    parcel_k = _num((result.get("k2o") or {}).get("rate_kg_ha"))
    oxides: dict[str, tuple[float | None, float | None]] = {}
    if soil_ok and any(zs.p_olsen_mg_kg is not None or zs.k_mg_kg is not None
                       for zs in own.values()):
        try:
            assembled = await assemble(_request(plan.campaign, sheet),
                                       _AnalysesOnce(sources, parcel_urn, analyses), today)
        except Exception:
            logger.exception("zone soil unavailable (assembly) %s", where)
            soil_ok = False
        else:
            parcel_run = calculate(assembled)
            fresh = (_num((parcel_run.p2o5 or {}).get("rate_kg_ha")),
                     _num((parcel_run.k2o or {}).get("rate_kg_ha")))
            if any((a is None) != (b is None) or (a is not None and abs(a - b) > INPUTS_TOLERANCE)
                   for a, b in zip(fresh, (parcel_p, parcel_k))):
                soil_notices.append(_notice("zone_soil_inputs_changed"))
            failed: list[str] = []
            oxides = _zone_oxides(assembled, own, {o.get("param") for o in sheet.overrides},
                                  failed, where)
            soil_notices.extend(_notice("zone_soil_calc_failed", zone=zid) for zid in failed)
    if not soil_ok:
        zone_soils, own, soil_notices, outside = {}, {}, [_notice("zone_soil_unavailable")], []
    notices.extend(soil_notices)

    # Nitrogen. The sheet's N already nets the parcel's mineral N (Nmin_p) off. A zone with its own
    # Nmin credits only the difference: dose_z = share_z(N) - (Nmin_z - Nmin_p), floor 0. A zone
    # without one has Nmin_z = Nmin_p: exactly the share of today. The sharing (and its cap) is
    # the unchanged vigor distribution of the target; the measured difference is not capped.
    # Owner decision: the correction is for the FIRST N pass only (an Nmin measured before sowing
    # says nothing of later top-dressings).
    nmin_p = _num(((result.get("n") or {}).get("credits_kg_ha") or {}).get("soil_mineral_n"))
    zone_nmin = {zid: zs.nmin_kg_ha for zid, zs in own.items() if zs.nmin_kg_ha is not None}
    if zone_nmin and target.application_seq is not None:
        organic = [OrganicApplication(**o) for o in sheet.inputs.get("organic") or []]
        first_n = next((i for i, a in enumerate(sheet.applications)
                        if nutrients(ApplicationIn.model_validate(a), organic).n_kg_ha > 0), None)
        if target.application_seq != first_n:
            notices.append(_notice("zone_nmin_first_pass_only", applied=False))
            zone_nmin = {}
    elif zone_nmin and target.application_seq is None:
        # ASSUMPTION: a free dose given by the technician is treated as the first N pass.
        notices.append(_notice("zone_nmin_first_pass_only", applied=True))
    n_credit = bool(zone_nmin) and target_n is not None and nmin_p is not None
    if not n_credit:
        zone_nmin = {}

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
    if n_credit:
        lo, hi = target_n * (1 - cap_pct / 100.0), target_n * (1 + cap_pct / 100.0)
        for zid, nmin_z in zone_nmin.items():
            vigor, factor, capped, n = doses[zid]
            net = n - (nmin_z - nmin_p)
            if net < 0:
                notices.append(_notice("zone_dose_floored", zone=zid))
                net = 0.0
            outside_cap = net < lo - 1e-9 or net > hi + 1e-9
            doses[zid] = (vigor, factor, capped or outside_cap, net)

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
        zs = own.get(z.id)
        z_p, z_k = oxides.get(z.id, (None, None))
        uses = zs is not None and (z_p is not None or z_k is not None or z.id in zone_nmin)
        rows.append({
            "zone_id": z.id, "label": z.label, "rank": z.rank, "level": z.level, "area_ha": _round(z.area_ha, 4),
            "basis": "zone_soil" if uses else ("vigor" if shared else "sheet"),
            "relative_vigor": _round(vigor, 4), "factor": _round(factor, 4), "capped": capped,
            "n_kg_ha": _round(n, 2), "product_kg_ha": _round(product_rate(n), 2),
            "nmin_kg_ha": _round(zone_nmin.get(z.id), 2),
            "p2o5_kg_ha": _round(parcel_p if z_p is None else z_p, 2),
            "k2o_kg_ha": _round(parcel_k if z_k is None else z_k, 2),
            "soil_analysis": (_soil_view(zs, by_zone.get(z.id, []), z.id in zone_nmin)
                              if uses else None),
            "missing": missing})

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
            "product_kg_ha": _round(product_rate(target_n), 2),
            "p2o5_kg_ha": _round(parcel_p, 2), "k2o_kg_ha": _round(parcel_k, 2)}

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
                "reason=%s zones=%d zone_soil=%d outside=%d", actor.tenant_id, plan.id, sheet_key,
                parcel_urn, zoning_run_id, strategy, effective, reason, len(zones), len(own),
                len(outside))
    return {
        "plan": {"id": str(plan.id), "state": plan.state, "campaign": plan.campaign},
        "sheet": {"key": sheet.key,
                  "n_kg_ha": ({"min": n["min_kg_ha"], "avg": n["avg_kg_ha"],
                               "max": n["max_kg_ha"]} if n else None),
                  "crop": {"eppo": (inputs.get("crop.eppo") or {}).get("value"),
                           "n_fixing": n_fixing}},
        "zoning": {"run_id": zoning.run_id, "method": zoning.method,
                   "variable": zoning.variable, "date": zoning.date,
                   "image_date": zoning.image_date, "zone_count": len(zones)},
        "strategy": strategy, "strategy_unavailable": reason,
        "target": {"n_kg_ha": _round(target_n, 2), "source": target_source,
                   "product": ({"name": product.name, "n_pct": product.n_pct}
                               if product else None)},
        "cap": {"pct": cap_pct,
                "min_n_kg_ha": _round(None if target_n is None else target_n * (1 - cap), 2),
                "max_n_kg_ha": _round(None if target_n is None else target_n * (1 + cap), 2)},
        "zones": rows, "rest": rest, "totals": totals, "notices": notices,
        "units": {"n": "kg N/ha", "product": "kg/ha", "p2o5": "kg P2O5/ha",
                  "k2o": "kg K2O/ha"},
        "versions": {"zone_doses": VERSION,
                     **{k: result["versions"].get(k) for k in ("engine", "calc")
                        if k in (result.get("versions") or {})}},
    }
