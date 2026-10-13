"""RD 1051/2022 art. 6.6 as amended by RD 934/2025: technical advice is mandatory one year after
the plan obligation (art. 4.2, 1-Sep-2026) in vulnerable zones and two years after elsewhere;
units exempt from the plan are exempt from advice. Owner decision 2026-10-13: the farm declares
whether it is in a vulnerable zone; undeclared counts as vulnerable."""
from __future__ import annotations

from datetime import date

from app.rules import INFO, Rule
from app.rules.context import PlanContext, plan_area
from app.rules.es.rd1051 import EXEMPT_RAINFED_HA

ADVICE_VULNERABLE = date(2027, 9, 1)
ADVICE_OTHER = date(2028, 9, 1)


def advice_required_from(vulnerable: bool | None) -> date:
    return ADVICE_OTHER if vulnerable is False else ADVICE_VULNERABLE


def exempt(ctx: PlanContext) -> bool:
    area, rainfed = plan_area(ctx)
    return area > 0 and rainfed and area <= EXEMPT_RAINFED_HA


def advice_required(ctx: PlanContext) -> bool:
    return not exempt(ctx) and ctx.at >= advice_required_from(ctx.vulnerable_zone)


def _advice(ctx: PlanContext):
    return [({"required": advice_required(ctx),
              "required_from": advice_required_from(ctx.vulnerable_zone).isoformat(),
              "vulnerable_zone": ctx.vulnerable_zone,
              "assumed_vulnerable": ctx.vulnerable_zone is None,
              "exempt": exempt(ctx)}, None)]


RULES = [Rule("ES-RD1051-6.6-advice", "RD 1051/2022, art. 6.6 (RD 934/2025) and art. 21", INFO,
              date(2023, 1, 1), None, _advice)]
