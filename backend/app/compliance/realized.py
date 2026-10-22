"""Fertilizations recorded in the field notebook (AgriParcelOperation, "fertilization",
"completed") turned into nutrient amounts per hectare (spec §11). The rate is kg of product per
ha, the field notebook's form unit; keyValues drops unitCodes."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime

from app.plans.clock import MADRID

STRUCTURED, PARSED, UNREADABLE = "structured", "parsed", "unreadable"
_PCT = r"(\d{1,3}(?:[.,]\d+)?)"
NPK = re.compile(rf"^\s*{_PCT}\s*-\s*{_PCT}\s*-\s*{_PCT}\s*$")
_CONTENTS = ("nitrogenContent", "phosphorusPentoxideContent", "potassiumOxideContent")


def _number(raw) -> float | None:
    if isinstance(raw, dict):
        raw = raw.get("value")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    if isinstance(raw, int) and abs(raw) > 1e15:       # huge ints overflow float()
        return None
    if not math.isfinite(raw):
        return None
    return float(raw)


def _day(raw) -> date | None:
    if isinstance(raw, dict):
        raw = raw.get("@value", raw.get("value"))
    if not raw:
        return None
    text = str(raw)
    try:
        if len(text) > 10 and "T" in text:
            moment = datetime.fromisoformat(text)
            if moment.tzinfo is not None:              # the norm's dates are Spanish calendar dates
                return moment.astimezone(MADRID).date()
            return moment.date()
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _object(raw) -> str | None:
    if isinstance(raw, dict):
        raw = raw.get("object")
    return raw if isinstance(raw, str) and raw else None


@dataclass(frozen=True)
class Realized:
    operation: str
    parcel: str | None
    day: date | None
    product: str | None
    rate_kg_ha: float | None
    area_ha: float | None
    n_pct: float | None
    p2o5_pct: float | None
    k2o_pct: float | None
    n_form: str | None
    composition: str
    notices: tuple[str, ...] = ()
    organic_flag: bool = False
    status: str | None = None

    @property
    def organic(self) -> bool:
        """The notebook's nitrogen form or its "organic fertilizer" checkbox."""
        return self.n_form == "organic" or self.organic_flag

    @property
    def completed(self) -> bool:
        """An operation without a status is read as completed (the broker query asks for it)."""
        return self.status in (None, "completed")

    def _kg(self, pct: float | None) -> float | None:
        if self.rate_kg_ha is None or pct is None:
            return None
        return self.rate_kg_ha * pct / 100

    @property
    def n_kg_ha(self) -> float | None:
        return self._kg(self.n_pct)

    @property
    def p2o5_kg_ha(self) -> float | None:
        return self._kg(self.p2o5_pct)

    @property
    def k2o_kg_ha(self) -> float | None:
        return self._kg(self.k2o_pct)


def _grade(entity: dict) -> tuple[float, ...] | None:
    text = entity.get("fertilizerComposition")
    match = NPK.match(text) if isinstance(text, str) else None
    if match:
        parsed = tuple(float(g.replace(",", ".")) for g in match.groups())
        if sum(parsed) <= 100:
            return parsed
    return None


def _composition(entity: dict) -> tuple[str, tuple[float | None, ...], tuple[str, ...]]:
    """A blank structured content is "not recorded" (the notebook shows 8-?-?), never 0: it is
    filled from a strict grade that agrees with the recorded ones, else left unknown."""
    values = [_number(entity.get(f)) for f in _CONTENTS]
    grade = _grade(entity)
    if any(v is not None for v in values):
        if all(v is not None for v in values):
            return STRUCTURED, tuple(values), ()
        if grade is None:
            return STRUCTURED, tuple(values), ("partial_composition",)
        notices = ()
        if any(v is not None and abs(v - g) > 0.01 for v, g in zip(values, grade, strict=True)):
            notices = ("composition_mismatch",)
        return STRUCTURED, tuple(v if v is not None else g
                                 for v, g in zip(values, grade, strict=True)), notices
    if grade is not None:
        return PARSED, grade, ()
    return UNREADABLE, (None, None, None), ()


def parse_operation(entity: dict) -> Realized:
    kind, (n, p, k), composition_notices = _composition(entity)
    day = _day(entity.get("endedAt")) or _day(entity.get("startedAt"))
    rate = _number(entity.get("fertilizerRate"))
    if rate is not None and rate <= 0:
        rate = None
    area = _number(entity.get("areaCovered"))
    notices = []
    if day is None:
        notices.append("undated")
    if rate is None:
        notices.append("no_rate")
    if kind == UNREADABLE:
        notices.append("unreadable_composition")
    notices.extend(composition_notices)
    product = entity.get("fertilizerType") or entity.get("productName")
    return Realized(
        operation=str(entity.get("id")),
        parcel=_object(entity.get("hasAgriParcel")) or _object(entity.get("refAgriParcel")),
        day=day, product=product if isinstance(product, str) else None, rate_kg_ha=rate,
        area_ha=area if area is not None and area > 0 else None,
        n_pct=n, p2o5_pct=p, k2o_pct=k,
        n_form=entity.get("nitrogenForm") if isinstance(entity.get("nitrogenForm"), str) else None,
        composition=kind, notices=tuple(notices),
        organic_flag=entity.get("organicFertilizer") is True,
        status=entity.get("status") if isinstance(entity.get("status"), str) else None)
