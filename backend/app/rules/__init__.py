"""Legal rules (spec §7): pure checks over a plan, each with its citation, severity and validity,
so an amendment of the norm is a new rule, not an edit of an old one."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from .context import PlanContext

BLOCK, WARN, INFO = "block", "warn", "info"


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: str
    citation: str
    params: dict = field(default_factory=dict)
    sheet_key: str | None = None

    def to_dict(self) -> dict:
        return {"rule_id": self.rule_id, "severity": self.severity, "citation": self.citation,
                "params": dict(self.params), "sheet_key": self.sheet_key}


@dataclass(frozen=True)
class Rule:
    id: str
    citation: str
    severity: str
    valid_from: date
    valid_to: date | None
    check: Callable[[PlanContext], list[tuple[dict, str | None]]]

    def applies(self, at: date) -> bool:
        return self.valid_from <= at and (self.valid_to is None or at <= self.valid_to)


def evaluate(rules: list[Rule], ctx: PlanContext) -> list[Finding]:
    found: list[Finding] = []
    for rule in rules:
        if rule.applies(ctx.at):
            found += [Finding(rule.id, rule.severity, rule.citation, params, key)
                      for params, key in rule.check(ctx)]
    return found


def count_blocking(findings: list[Finding]) -> int:
    return sum(1 for f in findings if f.severity == BLOCK)
