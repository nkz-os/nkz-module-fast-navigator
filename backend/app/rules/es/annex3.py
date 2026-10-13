"""RD 1051/2022 annex III-I.3-5: limits of the planned N (year) and P2O5, K2O (five years).

Owner decision 2026-10-13: the calculated N is the mean requirement (P50) after the soil
mineral N credit; the effective N is the planned mineral N plus the available organic N."""
from __future__ import annotations

import math
from datetime import date

from app.rules import BLOCK, INFO, WARN, Rule
from app.rules.context import PlanContext

IN_FORCE = date(2023, 1, 1)
N_FACTOR, P_FACTOR, K_FACTOR = 1.2, 1.3, 1.2
HISTORY_YEARS = 4
_EPS = 1e-6


def calculated_n(result: dict | None) -> float | None:
    """None when the sheet has no N result (FAST-sheet-incomplete already blocks it)."""
    n = (result or {}).get("n") or {}
    avg = (n.get("before_credits") or {}).get("avg_kg_ha")
    soil = (n.get("credits_kg_ha") or {}).get("soil_mineral_n")
    if avg is None or soil is None:
        return None
    return max(avg - soil, 0.0)


def effective_n(result: dict | None, summary: dict | None) -> float | None:
    n = (result or {}).get("n") or {}
    organic = (n.get("credits_kg_ha") or {}).get("organic_available_n")
    mineral = (summary or {}).get("mineral_n_kg_ha")
    if organic is None or mineral is None:
        return None
    return mineral + organic


ADJUSTMENT_BASES = ("foliar_analysis", "other_technique", "year_evolution")


def valid_adjustment(adj: dict | None, at: date, sheet=None, campaign: int | None = None
                     ) -> dict | None:
    """Annex III-I.3: N may exceed the limit when plant-need determinations (foliar analysis or
    another accepted technique) or the course of the agricultural year justify it. Incomplete,
    future-dated or unreferenced (except year evolution) justifications do not count.

    With a campaign, the justification must date from its agricultural year (from 1 September of
    the previous year). With a sheet, it counts only for the crop and parcels the technician
    justified (the scope stamped when it was recorded): a rewritten sheet is new content."""
    if not adj or adj.get("basis") not in ADJUSTMENT_BASES:
        return None
    try:
        day = date.fromisoformat(str(adj.get("date"))[:10])
    except ValueError:
        return None
    if day > at or not (adj.get("description") or "").strip():
        return None
    if campaign is not None and day < date(campaign - 1, 9, 1):
        return None
    if sheet is not None:
        scope = adj.get("scope")
        if (not isinstance(scope, dict)
                or scope.get("parcels") != sorted(p["urn"] for p in sheet.parcels)
                or scope.get("crop_eppo") != sheet.value("crop.eppo")):
            return None
    if adj["basis"] != "year_evolution" and not (adj.get("reference") or "").strip():
        return None
    n = adj.get("justified_n_kg_ha")
    if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or n <= 0:
        return None
    return adj


def _n_findings(ctx: PlanContext):
    blocks, adjusted = [], []
    for sheet in ctx.sheets:
        calc, eff = calculated_n(sheet.result), effective_n(sheet.result, sheet.summary)
        if calc is None or eff is None:
            continue
        limit = calc * N_FACTOR
        if eff <= limit + _EPS:
            continue
        params = {"effective_n_kg_ha": round(eff, 1), "calculated_n_kg_ha": round(calc, 1),
                  "limit_kg_ha": round(limit, 1)}
        adj = valid_adjustment(sheet.n_adjustment, ctx.at, sheet, ctx.campaign)
        if adj is not None and eff <= adj["justified_n_kg_ha"] + _EPS:
            adjusted.append(({**params, "justified_n_kg_ha": adj["justified_n_kg_ha"],
                              "basis": adj["basis"], "date": adj["date"],
                              "reference": adj.get("reference")}, sheet.key))
        else:
            if adj is not None:
                params = {**params, "justified_n_kg_ha": adj["justified_n_kg_ha"],
                          "basis": adj["basis"]}
            blocks.append((params, sheet.key))
    return blocks, adjusted


def _n_limit(ctx: PlanContext):
    return _n_findings(ctx)[0]


def _n_adjusted(ctx: PlanContext):
    return _n_findings(ctx)[1]


def _five_years(oxide: str, factor: float):
    def check(ctx: PlanContext):
        hits = []
        for sheet in ctx.sheets:
            planned = (sheet.summary or {}).get(f"{oxide}_kg_ha")
            calculated = ((sheet.result or {}).get(oxide) or {}).get("before_organic_kg_ha")
            if planned is None or calculated is None:
                continue          # no result: FAST-sheet-incomplete already blocks the sheet
            years = []
            for h in sheet.history:
                hp, hc = h.get(f"{oxide}_planned_kg_ha"), h.get(f"{oxide}_calculated_kg_ha")
                if hp is None or hc is None:
                    continue
                planned, calculated = planned + hp, calculated + hc
                years.append(h["campaign"])
            limit = calculated * factor
            if planned > limit + _EPS:
                hits.append(({"planned_kg_ha": round(planned, 1),
                              "calculated_kg_ha": round(calculated, 1),
                              "limit_kg_ha": round(limit, 1),
                              "years": sorted(years) + [ctx.campaign],
                              "history": "planned"}, sheet.key))
        return hits
    return check


def _history_short(ctx: PlanContext):
    hits = []
    for sheet in ctx.sheets:
        years = {h["campaign"] for h in sheet.history}
        if len(years) < HISTORY_YEARS:
            hits.append(({"years_available": len(years)}, sheet.key))
    return hits


C = "RD 1051/2022"
RULES = [
    Rule("ES-RD1051-AIII-3-N", f"{C}, annex III-I.3", BLOCK, IN_FORCE, None, _n_limit),
    Rule("ES-RD1051-AIII-3-N-adjusted", f"{C}, annex III-I.3 (justified adjustment)", INFO,
         IN_FORCE, None, _n_adjusted),
    Rule("ES-RD1051-AIII-4-P", f"{C}, annex III-I.4", WARN, IN_FORCE, None,
         _five_years("p2o5", P_FACTOR)),
    Rule("ES-RD1051-AIII-5-K", f"{C}, annex III-I.5", WARN, IN_FORCE, None,
         _five_years("k2o", K_FACTOR)),
    Rule("ES-RD1051-AIII-history-short", f"{C}, annex III-I.4 and 5 (years available)", INFO,
         IN_FORCE, None, _history_short),
]
