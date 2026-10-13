"""Target yield of a sheet and its variability (spec §4: parcel history, declared, zone)."""
from __future__ import annotations

import statistics
from dataclasses import dataclass, replace
from datetime import date, timedelta

from .crops import is_main
from .provenance import (
    DECLARED,
    MEASURED,
    MISSING,
    MissingInput,
    Notice,
    Override,
    Sourced,
    missing,
    table,
)

WINDOW_YEARS = 5
MIN_YEARS_FOR_CV = 3
MAX_CV_PCT = 100.0        # the engine rejects a larger CV; the technician enters it instead
STALE_ZONE_YEARS = 5      # owner 2026-10-12: warn when the zone's latest year is older
HARVEST_GRACE_DAYS = 30   # a harvest booked shortly after the cycle's recorded end belongs to it
_HISTORY_SOURCE = "field-operations:harvests"
_ZONE_SOURCE = "bioorch:regional-yields"


@dataclass(frozen=True)
class YieldTarget:
    yield_kg_ha: Sourced
    cv_pct: Sourced
    basis: str
    years: tuple[int, ...]
    notices: tuple[Notice, ...]
    missing: tuple[MissingInput, ...]


def _day(raw) -> date | None:
    if isinstance(raw, dict):
        raw = raw.get("@value") or raw.get("value") or raw.get("date")
    if isinstance(raw, str) and len(raw) >= 10:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None
    return None


def _number(raw) -> float | None:
    if isinstance(raw, dict):
        raw = raw.get("value")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    return None


def history_yields(cycles: list[dict], harvests: list[dict], eppo: str, area_ha: float
                   ) -> tuple[dict[int, float], tuple[Notice, ...]]:
    """kg/ha per campaign from the harvests recorded inside this crop's past main cycles.

    Matching harvests to cycles keeps another crop of the rotation out of the history. A
    harvested weight of 0 is the notebook's blank field (known defect): ignored and reported.
    """
    if area_ha <= 0:
        raise ValueError("area_ha must be > 0")
    out: dict[int, float] = {}
    notices: list[Notice] = []
    for cy in cycles:
        if not is_main(cy) or cy.get("species") != eppo:
            continue
        end = _day((cy.get("end") or {}).get("date"))
        label = cy.get("campaign_label")
        if end is None or not isinstance(label, int):
            continue
        start = _day((cy.get("start") or {}).get("date")) or end - timedelta(days=365)
        total = 0.0
        for op in harvests:
            day = _day(op.get("endedAt")) or _day(op.get("startedAt"))
            if day is None or not start <= day <= end + timedelta(days=HARVEST_GRACE_DAYS):
                continue
            weight = _number(op.get("harvestedWeight"))
            if weight is None:
                continue
            if weight <= 0:
                notices.append(Notice("harvest_zero_ignored",
                                      {"operation": op.get("id"), "campaign": label}))
                continue
            total += weight
        if total > 0:
            out[label] = out.get(label, 0.0) + total / area_ha
    return out, tuple(notices)


def combine_histories(per_parcel: list[tuple[dict[int, float], float]]) -> dict[int, float]:
    """Area-weighted kg/ha per campaign over the parcels that have that campaign."""
    years = {y for history, _ in per_parcel for y in history}
    out: dict[int, float] = {}
    for year in years:
        pairs = [(history[year], area) for history, area in per_parcel if year in history]
        out[year] = sum(v * a for v, a in pairs) / sum(a for _, a in pairs)
    return out


def _window(campaign: int, by_year: dict[int, float]) -> dict[int, float]:
    return {y: v for y, v in by_year.items()
            if campaign - WINDOW_YEARS <= y < campaign and v > 0}


def _cv(values: list[float]) -> float | None:
    if len(values) < MIN_YEARS_FOR_CV:
        return None
    mean = statistics.fmean(values)
    return statistics.stdev(values) / mean * 100 if mean > 0 else None


def zone_needed(campaign: int, history: dict[int, float], declared: dict[int, float],
                overrides: dict[str, Override], prefix: str = "yield") -> bool:
    """Whether resolve_yield could use the zone series (for the yield or for its CV)."""
    if f"{prefix}.kg_ha" in overrides and f"{prefix}.cv_pct" in overrides:
        return False
    if len(_window(campaign, history)) >= MIN_YEARS_FOR_CV:
        return False
    return len(_window(campaign, declared)) < MIN_YEARS_FOR_CV


def _zone(zone: dict | None):
    """(kg/ha median, CV %, years, latest year, provenance) of a regional-yields answer."""
    if not zone or not isinstance(zone.get("recent_median_t_ha"), (int, float)):
        return None, None, (), None, None
    by_year = {r.get("year"): r.get("yield_t_ha") for r in zone.get("series") or []}
    years = tuple(zone.get("recent_years") or ())
    values = [by_year[y] * 1000 for y in years if isinstance(by_year.get(y), (int, float))]
    source_id = next((a.get("source_id") for a in zone.get("attributions") or []
                      if a.get("source_id")), "eurostat")
    return (zone["recent_median_t_ha"] * 1000, _cv(values), years, zone.get("latest_year"),
            table(source_id))


def resolve_yield(campaign: int, history: dict[int, float], declared: dict[int, float],
                  zone: dict | None, overrides: dict[str, Override], today: date,
                  prefix: str = "yield") -> YieldTarget:
    notices: list[Notice] = []
    hist = _window(campaign, history)
    decl = _window(campaign, declared)
    zone_kg, zone_cv, zone_years, latest, zone_prov = _zone(zone)
    zone_note = f"{(zone or {}).get('nuts')} {(zone or {}).get('humidity_basis')}"

    if len(hist) >= MIN_YEARS_FOR_CV:
        values = list(hist.values())
        y = Sourced(statistics.median(values), MEASURED, _HISTORY_SOURCE)
        cv = Sourced(_cv(values), MEASURED, _HISTORY_SOURCE)
        basis, years = "history", tuple(sorted(hist))
    elif decl:
        values = list(decl.values())
        y = Sourced(statistics.median(values), DECLARED, "plan:declared-yields")
        own_cv = _cv(values)
        if own_cv is not None:
            cv = Sourced(own_cv, DECLARED, "plan:declared-yields")
        elif zone_cv is not None:
            cv = Sourced(zone_cv, zone_prov, _ZONE_SOURCE, "cv_from_zone")
        else:
            cv = missing(_ZONE_SOURCE)
        basis, years = "declared", tuple(sorted(decl))
    elif zone_kg is not None:
        y = Sourced(zone_kg, zone_prov, _ZONE_SOURCE, zone_note)
        cv = Sourced(zone_cv, zone_prov, _ZONE_SOURCE) if zone_cv is not None else missing(_ZONE_SOURCE)
        basis, years = "zone", zone_years
        if isinstance(latest, int) and latest < today.year - STALE_ZONE_YEARS:
            notices.append(Notice("zone_yield_stale",
                                  {"latest_year": latest, "nuts": (zone or {}).get("nuts")}))
    else:
        y, cv, basis, years = missing(), missing(), "missing", ()

    if cv.known and cv.value > MAX_CV_PCT:
        notices.append(Notice("yield_cv_out_of_range",
                              {"cv_pct": round(cv.value, 1), "basis": basis}))
        cv = missing()

    ignored = sorted(y for y in declared if not campaign - WINDOW_YEARS <= y < campaign)
    if ignored:
        notices.append(Notice("declared_years_ignored", {"years": ignored}))
    if 0 < len(hist) < MIN_YEARS_FOR_CV:
        notices.append(Notice("history_too_short", {"years": sorted(hist)}))
    if f"{prefix}.kg_ha" in overrides:
        y = overrides[f"{prefix}.kg_ha"].as_sourced()
        basis = "entered"
    if f"{prefix}.cv_pct" in overrides:
        cv = overrides[f"{prefix}.cv_pct"].as_sourced()

    absent: list[MissingInput] = []
    if not y.known:
        absent.append(MissingInput(f"{prefix}.kg_ha", "plan", {"campaign": campaign}))
    if not cv.known:
        absent.append(MissingInput(f"{prefix}.cv_pct", "plan", {"campaign": campaign}))
    return YieldTarget(y, cv, basis, years, tuple(notices), tuple(absent))


def _own(campaign: int, by_year: dict[int, float]) -> float | None:
    value = by_year.get(campaign)
    return value if value is not None and value > 0 else None


def previous_zone_needed(campaign: int, history: dict[int, float], declared: dict[int, float],
                         overrides: dict[str, Override], prefix: str = "previous_yield") -> bool:
    """Whether resolve_previous_yield could use the zone series (the CV is never needed)."""
    if f"{prefix}.kg_ha" in overrides:
        return False
    if _own(campaign, history) is not None or _own(campaign, declared) is not None:
        return False
    return len(_window(campaign, history)) < MIN_YEARS_FOR_CV and not _window(campaign, declared)


def resolve_previous_yield(campaign: int, history: dict[int, float], declared: dict[int, float],
                           zone: dict | None, overrides: dict[str, Override], today: date,
                           prefix: str = "previous_yield") -> YieldTarget:
    """Yield of the preceding crop: its own campaign's harvest, else its declared value, else
    the usual rule (window median, then zone). Its CV is never read, so never reported missing."""
    no_cv = Sourced(None, MISSING)
    if f"{prefix}.kg_ha" not in overrides:
        measured, stated = _own(campaign, history), _own(campaign, declared)
        if measured is not None:
            return YieldTarget(Sourced(measured, MEASURED, _HISTORY_SOURCE), no_cv, "history",
                               (campaign,), (), ())
        if stated is not None:
            return YieldTarget(Sourced(stated, DECLARED, "plan:declared-yields"), no_cv,
                               "declared", (campaign,), (), ())
    fallback = resolve_yield(campaign, history, declared, zone, overrides, today, prefix)
    return replace(fallback, missing=tuple(m for m in fallback.missing
                                           if not m.field.endswith(".cv_pct")))
