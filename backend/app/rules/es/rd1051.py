"""RD 1051/2022 (consolidated text, BOE-A-2022-23052): content, products and data of the plan."""
from __future__ import annotations

from datetime import date

from app.rules import BLOCK, INFO, WARN, Rule
from app.rules.context import PlanContext, plan_area

IN_FORCE = date(2023, 1, 1)
EXEMPT_RAINFED_HA = 10.0          # art. 4.2.b
POINT_REGION = "table:natural_earth_province"
_ORGANIC_KINDS = ("organic", "organo_mineral")
_UREA_KINDS = ("urea", "urea_solution")


def _scope(ctx: PlanContext):
    area, rainfed = plan_area(ctx)
    if area > 0 and rainfed and area <= EXEMPT_RAINFED_HA:
        return [({"total_area_ha": round(area, 4)}, None)]
    return []


def _recinto(ctx: PlanContext):
    hits = []
    for sheet in ctx.sheets:
        for parcel in sheet.parcels:
            if not parcel.get("sigpac") and not sheet.value(f"parcel.{parcel['urn']}.identifier"):
                hits.append(({"parcel": parcel["urn"]}, sheet.key))
    return hits


def _soil(ctx: PlanContext):
    hits = []
    for sheet in ctx.sheets:
        provisional = bool((sheet.result or {}).get("provisional"))
        analysis = sheet.value("soil.analysis_id")
        if not analysis or provisional:
            hits.append(({"analysis_id": analysis, "provisional": provisional}, sheet.key))
    return hits


def _water(ctx: PlanContext):
    hits = []
    if not ctx.rain or ctx.rain.get("annual_mm") is None:
        hits.append(({"missing": "rain_normal"}, None))
    for sheet in ctx.sheets:
        if sheet.inputs.get("irrigated") and sheet.value("irrigation.water_m3_ha") is None:
            hits.append(({"missing": "irrigation_water"}, sheet.key))
    return hits


def _requirement(result: dict | None) -> bool:
    r = result or {}
    return any([((r.get("n") or {}).get("avg_kg_ha") or 0) > 0,
                ((r.get("p2o5") or {}).get("rate_kg_ha") or 0) > 0,
                ((r.get("k2o") or {}).get("rate_kg_ha") or 0) > 0])


def _content(ctx: PlanContext):
    return [({}, s.key) for s in ctx.sheets if _requirement(s.result) and not s.applications]


def _measures(app: dict, part: str) -> bool:
    return any(code.startswith(f"{part}.") for code in app.get("annex_v") or [])


def _annex_v(ctx: PlanContext):
    return [({"application": i, "kind": a.get("kind")}, s.key)
            for s in ctx.sheets for i, a in enumerate(s.applications)
            if a.get("kind") in _ORGANIC_KINDS and not _measures(a, "A")]


def _ammonium_carbonate(ctx: PlanContext):
    return [({"application": i}, s.key) for s in ctx.sheets
            for i, a in enumerate(s.applications) if a.get("kind") == "ammonium_carbonate"]


def _urea(ctx: PlanContext):
    if ctx.voluntary_digital_notebook:
        return []
    return [({"application": i, "kind": a.get("kind")}, s.key)
            for s in ctx.sheets for i, a in enumerate(s.applications)
            if a.get("kind") in _UREA_KINDS and not _measures(a, "B")
            and not (a.get("other_measure") or "").strip()]


def _strategy4(ctx: PlanContext):
    return [({}, s.key) for s in ctx.sheets if s.inputs.get("strategy") == 4]


def _incomplete(ctx: PlanContext):
    hits = []
    for sheet in ctx.sheets:
        if sheet.result is None:
            hits.append(({"reason": "not_calculated"}, sheet.key))
        elif sheet.result.get("status") != "complete":
            hits.append(({"missing": [m["field"] for m in sheet.result.get("missing") or []]},
                         sheet.key))
    return hits


def _region(ctx: PlanContext):
    hits = []
    for sheet in ctx.sheets:
        zone = "zone" in (sheet.value("yield.basis"), sheet.value("previous_yield.basis"))
        if zone and sheet.provenance("region.nuts") == POINT_REGION:
            hits.append(({"nuts": sheet.value("region.nuts")}, sheet.key))
    return hits


C = "RD 1051/2022"
RULES = [
    Rule("ES-RD1051-4.2-scope", f"{C}, art. 4.2", INFO, IN_FORCE, None, _scope),
    Rule("ES-RD1051-6.1-recinto", f"{C}, art. 6.1", BLOCK, IN_FORCE, None, _recinto),
    Rule("ES-RD1051-6.2-soil", f"{C}, art. 6.2", BLOCK, IN_FORCE, None, _soil),
    Rule("ES-RD1051-6.3-water", f"{C}, art. 6.3", BLOCK, IN_FORCE, None, _water),
    Rule("ES-RD1051-6.4-content", f"{C}, art. 6.4", BLOCK, IN_FORCE, None, _content),
    Rule("ES-RD1051-6.5-annexV", f"{C}, art. 6.5 and annex V-A", BLOCK, IN_FORCE, None,
         _annex_v),
    Rule("ES-RD1051-12.1", f"{C}, art. 12.1", BLOCK, IN_FORCE, None, _ammonium_carbonate),
    Rule("ES-RD1051-12.3", f"{C}, art. 12.3 and annex V-B", BLOCK, IN_FORCE, None, _urea),
    Rule("ES-RD1051-AIII-strategy4", f"{C}, annex III-I.4 and 5", WARN, IN_FORCE, None,
         _strategy4),
    Rule("FAST-sheet-incomplete", "FaST: every crop sheet calculated with all its inputs",
         BLOCK, IN_FORCE, None, _incomplete),
    Rule("FAST-region-unconfirmed", "FaST: zone yields need a confirmed NUTS 2 region",
         BLOCK, IN_FORCE, None, _region),
]
