"""RD 1051/2022 (consolidated text, BOE-A-2022-23052): content, products and data of the plan."""
from __future__ import annotations

from datetime import date

from app.rules import BLOCK, INFO, WARN, Rule
from app.rules.context import PlanContext, area_known, plan_area, sheet_area

IN_FORCE = date(2023, 1, 1)
EXEMPT_RAINFED_HA = 10.0          # art. 4.2.b
POINT_REGION = "table:natural_earth_province"
_ORGANIC_KINDS = ("organic", "organo_mineral")
_UREA_KINDS = ("urea", "urea_solution")
EXEMPT_ANALYSIS_UNIT_HA = 20.0    # RD 1311/2012 annex III I.C.i.d: unit of at most 20 ha...
EXEMPT_ANALYSIS_SHEET_HA = 5.0    # ...whose sheet cannot be grouped into 5 ha
SOIL_FIELDS = ("soil.ph", "soil.organic_matter_pct", "soil.p_olsen_mg_kg", "soil.k_mg_kg")
MAX_AGE_IRRIGATED, MAX_AGE_RAINFED = 5, 10      # years, annex III I.C.i


def _scope(ctx: PlanContext):
    area, rainfed = plan_area(ctx)
    if area_known(ctx) and area > 0 and rainfed and area <= EXEMPT_RAINFED_HA:
        return [({"total_area_ha": round(area, 4)}, None)]
    return []


def _recinto(ctx: PlanContext):
    hits = []
    for sheet in ctx.sheets:
        for parcel in sheet.parcels:
            if not parcel.get("sigpac") and not sheet.value(f"parcel.{parcel['urn']}.identifier"):
                hits.append(({"parcel": parcel["urn"]}, sheet.key))
    return hits


def _add_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:                      # 29 February
        return day.replace(year=day.year + years, day=28)


def _soil_exempt(ctx: PlanContext, sheet) -> dict | None:
    """Annex III I.C.i.d: sheet < 5 ha in a unit of at most 20 ha. Unknown area: not exempt."""
    if not area_known(ctx):
        return None
    unit, _ = plan_area(ctx)
    own = sheet_area(sheet)
    if own is not None and unit <= EXEMPT_ANALYSIS_UNIT_HA and own < EXEMPT_ANALYSIS_SHEET_HA:
        return {"sheet_area_ha": round(own, 4), "unit_area_ha": round(unit, 4)}
    return None


def _soil_findings(ctx: PlanContext):
    """Art. 6.2 + RD 1311/2012 annex III I.C.i: a recent analysis with pH, organic matter,
    assimilable P and K, measured. Total N is not checked: FaST holds no total-N value."""
    blocks, exempt = [], []
    for sheet in ctx.sheets:
        spared = _soil_exempt(ctx, sheet)
        if spared is not None:
            exempt.append((spared, sheet.key))
            continue
        params: dict = {"reasons": []}
        analysis = sheet._item("soil.analysis_id")
        if not analysis.get("value"):
            params["reasons"].append("no_analysis")
        else:
            years = MAX_AGE_IRRIGATED if sheet.inputs.get("irrigated") else MAX_AGE_RAINFED
            raw = analysis.get("sampling_date")
            try:
                sampled = date.fromisoformat(str(raw)[:10])
            except ValueError:
                sampled = None
            if sampled is None:
                params["reasons"].append("no_sampling_date")
                params["max_age_years"] = years
            elif _add_years(sampled, years) < ctx.at:
                params["reasons"].append("too_old")
                params["sampling_date"] = sampled.isoformat()
                params["max_age_years"] = years
        bad = [f for f in SOIL_FIELDS if sheet.provenance(f) not in ("measured", "entered")]
        if bad:
            params["reasons"].append("not_measured")
            params["fields"] = bad
        if params["reasons"]:
            blocks.append((params, sheet.key))
    return blocks, exempt


# RD 1311/2012 annex III part I C.i (as amended by RD 1051/2022): soil data are not mandatory
# until one year after the MAPA publishes its soil sampling and analysis guides. Not published
# as of 2026-10-13 (owner): when they are, set publication + 1 year in a new rules version.
# Sewage sludge (always analysed) is not a material FaST plans.
SOIL_DATA_MANDATORY_FROM: date | None = None


def soil_data_mandatory(at: date) -> bool:
    return SOIL_DATA_MANDATORY_FROM is not None and at >= SOIL_DATA_MANDATORY_FROM


def _soil(ctx: PlanContext):
    return _soil_findings(ctx)[0] if soil_data_mandatory(ctx.at) else []


def _soil_transitional(ctx: PlanContext):
    return [] if soil_data_mandatory(ctx.at) else _soil_findings(ctx)[0]


def _soil_exempt_info(ctx: PlanContext):
    return _soil_findings(ctx)[1]


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
    """Art. 6.4: a requirement needs applications, and so does every organic input credited in
    the calculation (spreading manure is a fertilization whatever the requirement)."""
    hits = [({}, s.key) for s in ctx.sheets if _requirement(s.result) and not s.applications]
    for s in ctx.sheets:
        planned = {a.get("organic_index") for a in s.applications}
        hits += [({"organic": i}, s.key)
                 for i in range(len(s.inputs.get("organic") or [])) if i not in planned]
    return hits


def _measures(app: dict, part: str) -> bool:
    return any(code.startswith(f"{part}.") for code in app.get("annex_v") or [])


def _annex_v(ctx: PlanContext):
    return [({"application": i, "kind": a.get("kind")}, s.key)
            for s in ctx.sheets for i, a in enumerate(s.applications)
            if a.get("kind") in _ORGANIC_KINDS and not _measures(a, "A")
            and not (a.get("other_measure") or "").strip()]


def _ammonium_carbonate(ctx: PlanContext):
    return [({"application": i}, s.key) for s in ctx.sheets
            for i, a in enumerate(s.applications) if a.get("kind") == "ammonium_carbonate"]


def _is_ureic(app: dict) -> bool:
    """Art. 12.3 "urea o soluciones nitrogenadas ureicas": urea products, and any non-organic
    product whose label declares ureic N."""
    if app.get("kind") in _UREA_KINDS:
        return True
    return app.get("kind") in ("mineral", "organo_mineral") and (
        app.get("n_form") == "ureic" or (app.get("n_ureic_pct") or 0) > 0)


def _urea(ctx: PlanContext):
    if ctx.voluntary_digital_notebook:
        return []
    return [({"application": i, "kind": a.get("kind")}, s.key)
            for s in ctx.sheets for i, a in enumerate(s.applications)
            if _is_ureic(a) and not _measures(a, "B")
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
    Rule("ES-RD1051-6.2-soil-transitional",
         f"{C}, art. 6.2; RD 1311/2012, annex III part I C.i (soil data not yet mandatory: "
         "MAPA sampling guides not published)", WARN, IN_FORCE, None, _soil_transitional),
    Rule("ES-RD1051-6.2-analysis-exempt",
         "RD 1311/2012, annex III part I C.i.d (RD 1051/2022)", INFO, IN_FORCE, None,
         _soil_exempt_info),
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
