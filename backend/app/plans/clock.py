"""The date a plan is judged at: deadlines of the norm are Spanish calendar dates."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

MADRID = ZoneInfo("Europe/Madrid")      # built at import: a missing zone database fails at start


def legal_today() -> date:
    return datetime.now(MADRID).date()
