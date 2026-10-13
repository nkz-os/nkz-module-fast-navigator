"""Provenance of every plan input (spec §12): where a value comes from, never a silent default."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

MEASURED = "measured"
ESTIMATED = "estimated"
DECLARED = "declared"
ENTERED = "entered"
MISSING = "missing"


def table(source_id: str) -> str:
    """Provenance of a value read from a cited reference table."""
    return f"table:{source_id}"


@dataclass(frozen=True)
class Sourced:
    value: Any
    provenance: str
    source: str | None = None
    note: str | None = None

    @property
    def known(self) -> bool:
        return self.value is not None and self.provenance != MISSING

    def to_dict(self) -> dict:
        return {"value": self.value, "provenance": self.provenance, "source": self.source,
                "note": self.note}


def missing(source: str | None = None, note: str | None = None) -> Sourced:
    return Sourced(None, MISSING, source, note)


@dataclass(frozen=True)
class Notice:
    """Something the user must see; `code` is an i18n key and `params` its arguments."""
    code: str
    params: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"code": self.code, "params": dict(self.params)}


@dataclass(frozen=True)
class MissingInput:
    """An input the calculation needs and no source has; `owner` says where to fix it."""
    field: str
    owner: str
    params: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"field": self.field, "owner": self.owner, "params": dict(self.params)}


@dataclass(frozen=True)
class Override:
    """A value a person typed instead of the source's, with the reason (audited and printed)."""
    param: str
    value: float | str | bool
    reason: str
    user: str
    at: str

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError(f"override of {self.param} needs a reason")
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError(f"override of {self.param} must be a finite number")

    def as_sourced(self) -> Sourced:
        return Sourced(self.value, ENTERED, f"user:{self.user}@{self.at}", self.reason.strip())
