"""Every rule FaST evaluates, and the version stored with each plan."""
from __future__ import annotations

from app.rules import Rule

RULES_VERSION = "es-2026.10.2"


def all_rules() -> list[Rule]:
    from app.rules import es, es_na

    return [*es.RULES, *es_na.RULES]
