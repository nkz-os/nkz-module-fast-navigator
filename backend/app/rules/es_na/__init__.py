"""Navarra (es-na): the regional order is not located yet (spec D9), so plans in Navarra get a
notice that its stricter rules were not checked."""
from __future__ import annotations

from datetime import date

from app.rules import INFO, Rule
from app.rules.context import PlanContext

NAVARRA_NUTS = "ES22"


def _not_checked(ctx: PlanContext):
    if any(s.value("region.nuts") == NAVARRA_NUTS for s in ctx.sheets):
        return [({"nuts": NAVARRA_NUTS}, None)]
    return []


def _region_unknown(ctx: PlanContext):
    """The region is resolved only when zone yields are needed; without it no regional rule
    (Navarra's included) can be said to have been checked."""
    keys = [s.key for s in ctx.sheets if s.value("region.nuts") is None]
    return [({"sheets": keys}, None)] if keys else []


RULES = [Rule("ES-NA-not-checked", "Navarra: regional rules not checked yet (spec D9)", INFO,
              date(2023, 1, 1), None, _not_checked),
         Rule("FAST-region-unknown",
              "FaST: regional rules cannot be checked without the NUTS 2 region (spec D9)", INFO,
              date(2023, 1, 1), None, _region_unknown)]
