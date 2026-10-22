"""Planned versus realized (spec §11): realized fertilizations per crop sheet, weighted by area,
judged with the same annex III rules as the plan. Computed on request, never stored."""
from __future__ import annotations

import copy
from collections import defaultdict
from datetime import date

from app.compliance.realized import Realized
from app.rules import BLOCK, WARN, evaluate
from app.rules.context import PlanContext, SheetContext
from app.rules.es import annex3
from app.rules.es.advice import _planned_dates, fertilization_until

HISTORY_CAMPAIGNS = 4
_INCOMPLETE = ("undated", "no_rate", "unreadable_composition", "partial_composition",
               "organic_rate_suspect", "operation_not_completed")
_KEYS = ("mineral_n_kg_ha", "organic_n_total_kg_ha", "organic_n_available_kg_ha", "p2o5_kg_ha",
         "k2o_kg_ha")


def _season(campaign: int) -> tuple[date, date]:
    return date(campaign - 1, 9, 1), date(campaign, 8, 31)


def _area(sheet: dict, urn: str) -> float | None:
    item = ((sheet.get("result") or {}).get("inputs") or {}).get(f"parcel.{urn}.area_ha") or {}
    value = item.get("value")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) \
        and value > 0 else None


def _availability(sheet: dict) -> float | None:
    organic = (sheet.get("inputs") or {}).get("organic") or []
    if len(organic) != 1:
        return None
    item = ((sheet.get("result") or {}).get("inputs") or {}).get("organic.0.availability") or {}
    value = item.get("value")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _totals(sheet: dict, ops: list[tuple[str, Realized]], notices: set[str]) -> dict:
    """kg/ha over the sheet: Σ(per-ha amount × area) / sheet area. `ops` pairs the parcel URN the
    operation was fetched for with the operation. An unknown area gives unknown (None) amounts."""
    areas = {p["urn"]: _area(sheet, p["urn"]) for p in sheet["parcels"]}
    if any(a is None for a in areas.values()):
        notices.add("parcel_area_unknown")
        return dict.fromkeys(_KEYS)
    total_area = sum(areas.values())
    share = _availability(sheet)
    sums = defaultdict(float)
    for urn, op in ops:
        area = min(op.area_ha, areas[urn]) if op.area_ha else areas[urn]
        weight = area / total_area
        if op.n_kg_ha is not None:
            if op.organic:
                sums["organic_n_total_kg_ha"] += op.n_kg_ha * weight
                if share is None:
                    notices.add("organic_availability_assumed_full")
                else:
                    notices.add("organic_availability_from_plan")
                sums["organic_n_available_kg_ha"] += op.n_kg_ha * (
                    share if share is not None else 1.0) * weight
            else:
                sums["mineral_n_kg_ha"] += op.n_kg_ha * weight
        for key in ("p2o5_kg_ha", "k2o_kg_ha"):
            value = getattr(op, key)
            if value is not None:
                sums[key] += value * weight
    return {k: round(sums[k], 3) for k in _KEYS}


def _in(op: Realized, start: date, until: date) -> bool:
    return op.day is not None and start <= op.day <= until


_UNUSABLE = ("no_rate", "unreadable_composition", "partial_composition")


def _parcel_per_ha(ops: list[Realized], area: float, key: str) -> float:
    """kg/ha over one parcel from its operations (operation area capped by the parcel's)."""
    total = 0.0
    for op in ops:
        value = getattr(op, key)
        if value is None:
            continue
        covered = min(op.area_ha, area) if op.area_ha else area
        total += value * covered / area
    return total


def _history(sheet: dict, previous: dict[int, dict], realized: dict[str, list[Realized]],
             campaign: int, notices: set[str]) -> tuple[dict, ...]:
    """Per past campaign, per parcel of this sheet: calculated and applied P2O5/K2O summed over
    every old sheet holding that parcel; then the area-weighted mean over the parcels that had
    one. Realized operations of the season win over the signed plan; unusable data is flagged."""
    areas = {p["urn"]: _area(sheet, p["urn"]) for p in sheet["parcels"]}
    out = []
    for year in range(campaign - HISTORY_CAMPAIGNS, campaign):
        snapshot = previous.get(year)
        if not snapshot:
            continue
        old_by_parcel = {}
        for urn in areas:
            old_by_parcel[urn] = [s for s in snapshot.get("sheets") or []
                                  if urn in {p["urn"] for p in s.get("parcels") or []}]
        used = {u: o for u, o in old_by_parcel.items() if o}
        if not used:
            continue
        if any(s.get("applications_summary") is None or not s.get("result")
               for o in used.values() for s in o) or any(areas[u] is None for u in used):
            notices.add(f"history_incomplete:{year}")
            continue
        start, until = _season(year)
        ops = {u: [op for op in realized.get(u, []) if _in(op, start, until)] for u in used}
        if any(n in _UNUSABLE for o in ops.values() for op in o for n in op.notices) \
                or any(not op.completed for o in ops.values() for op in o):
            notices.add(f"history_incomplete:{year}")
            continue
        use_realized = any(ops.values())
        total_area = sum(areas[u] for u in used)
        acc = defaultdict(float)
        for urn, old in used.items():
            weight = areas[urn] / total_area
            for oxide in ("p2o5", "k2o"):
                acc[f"{oxide}_calculated_kg_ha"] += weight * sum(
                    ((s.get("result") or {}).get(oxide) or {}).get("before_organic_kg_ha") or 0
                    for s in old)
                applied = (_parcel_per_ha(ops[urn], areas[urn], f"{oxide}_kg_ha") if use_realized
                           else sum((s.get("applications_summary") or {}).get(f"{oxide}_kg_ha")
                                    or 0 for s in old))
                acc[f"{oxide}_planned_kg_ha"] += weight * applied
        out.append({"campaign": year, "source": "realized" if use_realized else "planned",
                    **{k: round(v, 3) for k, v in acc.items()}})
    return tuple(out)


def _op_row(urn: str, op: Realized) -> dict:
    return {"operation": op.operation, "parcel": urn, "status": op.status,
            "date": op.day.isoformat() if op.day else None, "product": op.product,
            "rate_kg_ha": op.rate_kg_ha, "area_ha": op.area_ha, "n_kg_ha": op.n_kg_ha,
            "p2o5_kg_ha": op.p2o5_kg_ha, "k2o_kg_ha": op.k2o_kg_ha, "organic": op.organic,
            "composition": op.composition, "notices": list(op.notices)}


def compliance(document: dict, previous: dict[int, dict], realized: dict[str, list[Realized]],
               at: date) -> dict:
    campaign = document["plan"]["campaign"]
    sheets = document["sheets"]
    declarations = document.get("declarations") or {}
    plan_ctx = PlanContext(
        campaign=campaign,
        sheets=tuple(SheetContext(s["key"], s.get("inputs") or {}, tuple(s["parcels"]),
                                  tuple(s.get("applications") or []), s.get("result"),
                                  s.get("applications_summary")) for s in sheets),
        rain=document.get("rain"), vulnerable_zone=declarations.get("vulnerable_zone"),
        voluntary_digital_notebook=bool(declarations.get("voluntary_digital_notebook")),
        at=at, irrigated_spring_2026=declarations.get("irrigated_spring_2026"))
    standard_start, standard_end = _season(campaign)
    start = min([standard_start, *_planned_dates(plan_ctx)])
    until = fertilization_until(plan_ctx)

    owners: dict[str, list[str]] = defaultdict(list)
    for s in sheets:
        for p in s["parcels"]:
            owners[p["urn"]].append(s["key"])
    unattributed, per_sheet = [], defaultdict(list)
    for urn, ops in realized.items():
        for op in ops:
            if op.day is not None and not _in(op, start, until):
                continue                                  # another campaign
            if len(owners.get(urn, [])) > 1:
                unattributed.append({"operation": op.operation, "parcel": urn,
                                     "date": op.day.isoformat() if op.day else None,
                                     "reason": "parcel_in_several_sheets"})
                continue
            if not owners.get(urn):
                unattributed.append({"operation": op.operation, "parcel": urn,
                                     "date": op.day.isoformat() if op.day else None,
                                     "reason": "parcel_not_in_plan"})
                continue
            if owners.get(urn):
                per_sheet[owners[urn][0]].append((urn, op))
    ambiguous = {k for u in unattributed for k in owners[u["parcel"]]}

    out_sheets = []
    for s in sheets:
        pairs = per_sheet.get(s["key"], [])
        ops = [op for _, op in pairs]
        notices = {n for op in ops for n in op.notices}
        if s["key"] in ambiguous:
            notices.add("parcel_in_several_sheets")
        if any(not op.completed for op in ops):
            notices.add("operation_not_completed")
        if any(op.day is not None and not _in(op, standard_start, standard_end) for op in ops):
            notices.add("operation_in_extended_window")
        # ASSUMPTION: the notebook rate is kg of product per ha for every product (keyValues drops unitCode)
        if any(op.organic and op.rate_kg_ha is not None and op.rate_kg_ha < 1000 for op in ops):
            notices.add("organic_rate_suspect")
        res = s.get("result") or {}
        if not (res.get("n") and res.get("p2o5") and res.get("k2o")):
            notices.add("no_result")
        counted = [(urn, op) for urn, op in pairs if op.day is not None and op.completed]
        totals = _totals(s, counted, notices)
        result = copy.deepcopy(s.get("result")) or {}
        if result.get("n"):
            result["n"].setdefault("credits_kg_ha", {})["organic_available_n"] = \
                totals["organic_n_available_kg_ha"]
        summary = {"mineral_n_kg_ha": totals["mineral_n_kg_ha"],
                   "p2o5_kg_ha": totals["p2o5_kg_ha"], "k2o_kg_ha": totals["k2o_kg_ha"]}
        history = _history(s, previous, realized, campaign, notices)
        ctx = PlanContext(
            campaign=campaign,
            sheets=(SheetContext(s["key"], s.get("inputs") or {}, tuple(s["parcels"]), (), result,
                                 summary, history, s.get("n_adjustment")),),
            rain=None, vulnerable_zone=None, voluntary_digital_notebook=False, at=at)
        findings = evaluate(annex3.RULES, ctx)
        planned = s.get("applications_summary") or {}
        warns = [f for f in findings if f.severity == WARN]
        if (any(f.severity == BLOCK for f in findings)
                or (warns and len(history) == HISTORY_CAMPAIGNS)):
            status = "exceeded"
        elif (notices & set(_INCOMPLETE)
              or notices & {"parcel_in_several_sheets", "parcel_area_unknown", "no_result"}
              or any(n.startswith("history_incomplete:") for n in notices)):
            status = "incomplete"
        elif warns:
            status = "at_risk"
        else:
            status = "ok"
        out_sheets.append({
            "key": s["key"], "status": status,
            "applications": [_op_row(urn, op) for urn, op in pairs],
            "realized": totals,
            "planned": {k: planned.get(k) for k in ("mineral_n_kg_ha", "organic_n_total_kg_ha",
                                                    "p2o5_kg_ha", "k2o_kg_ha")},
            "difference": {k: (round(totals[k] - planned[k], 3)
                               if totals[k] is not None and planned.get(k) is not None else None)
                           for k in ("mineral_n_kg_ha", "p2o5_kg_ha", "k2o_kg_ha")},
            "findings": [f.to_dict() for f in findings], "notices": sorted(notices)})
    return {"campaign": campaign, "live": bool(document.get("live")),
            "judged_at": at.isoformat(),
            "window": {"from": start.isoformat(), "until": until.isoformat()},
            "sheets": out_sheets, "unattributed": unattributed}
