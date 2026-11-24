"""EU Nitrates Directive (91/676/EEC, Annex III.2): 170 kg total organic N / ha·year in NVZ.

Applies across the entire European Union (including every Spanish autonomous community)
as the baseline layer beneath national (es) and regional (es_na, ...) rulesets.
"""
from __future__ import annotations

from datetime import date

from app.rules import BLOCK, WARN, Rule
from app.rules.context import PlanContext

IN_FORCE = date(1991, 12, 19)
NVZ_ORGANIC_N_LIMIT_KG_HA = 170.0
_EPS = 1e-6


def _organic_n_total(sheet) -> float | None:
    """Total organic N (kg/ha) on the sheet: max of planned applications summary and declared organic inputs."""
    candidates: list[float] = []
    if sheet.summary and sheet.summary.get("organic_n_total_kg_ha") is not None:
        candidates.append(float(sheet.summary["organic_n_total_kg_ha"]))
    organics = (sheet.inputs or {}).get("organic") or []
    if organics:
        from_inputs = 0.0
        for item in organics:
            if not isinstance(item, dict):
                continue
            rate = item.get("rate_t_ha")
            n_pct = item.get("n_pct")
            if isinstance(rate, (int, float)) and isinstance(n_pct, (int, float)):
                from_inputs += float(rate) * 1000.0 * float(n_pct) / 100.0
        candidates.append(from_inputs)
    return max(candidates) if candidates else None


def _nvz_limit_block(ctx: PlanContext):
    """Block signing when declared in a Nitrate Vulnerable Zone and planned organic N > 170 kg/ha."""
    if ctx.vulnerable_zone is not True:
        return []
    hits = []
    for sheet in ctx.sheets:
        total = _organic_n_total(sheet)
        if total is not None and total > NVZ_ORGANIC_N_LIMIT_KG_HA + _EPS:
            hits.append((
                {"organic_n_total_kg_ha": round(total, 1), "limit_kg_ha": NVZ_ORGANIC_N_LIMIT_KG_HA},
                sheet.key,
            ))
    return hits


def _nvz_limit_undeclared(ctx: PlanContext):
    """Warn when NVZ status is undeclared and planned organic N > 170 kg/ha."""
    if ctx.vulnerable_zone is not None:
        return []
    hits = []
    for sheet in ctx.sheets:
        total = _organic_n_total(sheet)
        if total is not None and total > NVZ_ORGANIC_N_LIMIT_KG_HA + _EPS:
            hits.append((
                {"organic_n_total_kg_ha": round(total, 1), "limit_kg_ha": NVZ_ORGANIC_N_LIMIT_KG_HA},
                sheet.key,
            ))
    return hits


RULES = [
    Rule(
        "EU-91-676-NVZ-170-N",
        "Directive 91/676/EEC, Annex III.2 (170 kg organic N/ha·year in NVZ)",
        BLOCK,
        IN_FORCE,
        None,
        _nvz_limit_block,
    ),
    Rule(
        "EU-91-676-NVZ-170-N-undeclared",
        "Directive 91/676/EEC, Annex III.2 (confirm NVZ status: organic N > 170 kg/ha)",
        WARN,
        IN_FORCE,
        None,
        _nvz_limit_undeclared,
    ),
]
