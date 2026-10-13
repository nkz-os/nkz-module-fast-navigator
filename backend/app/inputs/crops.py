"""Crop and preceding crop of a sheet: the parcel's crop cycles, or what the user declares."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from .provenance import DECLARED, MEASURED, MissingInput, Notice, Sourced, missing

EPPO = re.compile(r"^[A-Z0-9]{5,6}$")
FALLOW = "fallow"
MAIN_ROLE = "main_crop"   # the platform's crop-cycle vocabulary; "cover_crop" is the other one
_SOURCE = "entity-manager:crop-cycles"


@dataclass(frozen=True)
class CropChoice:
    crop: Sourced                    # EPPO code
    previous: Sourced                # EPPO code or FALLOW
    previous_campaign: int | None
    notices: tuple[Notice, ...]
    missing: tuple[MissingInput, ...]


def is_main(cycle: dict) -> bool:
    """A cycle without a role is a main crop (the platform's default)."""
    return (cycle.get("role") or MAIN_ROLE) == MAIN_ROLE


def _date(cycle: dict, key: str) -> date | None:
    raw = (cycle.get(key) or {}).get("date")
    try:
        return date.fromisoformat(raw) if isinstance(raw, str) else None
    except ValueError:
        return None


def _species(cycle: dict | None) -> str | None:
    s = (cycle or {}).get("species")
    return s if isinstance(s, str) and EPPO.match(s) else None


def crops_for_campaign(cycles: list[dict], campaign: int, cycle_index: int = 0,
                       declared_crop: str | None = None,
                       declared_previous: str | None = None) -> CropChoice:
    notices: list[Notice] = []
    absent: list[MissingInput] = []
    mains = sorted((c for c in cycles if is_main(c)),
                   key=lambda c: _date(c, "start") or date.min)
    of_campaign = [c for c in mains if c.get("campaign_label") == campaign]
    if len(of_campaign) > 1:
        notices.append(Notice("double_crop_campaign", {"campaign": campaign, "count": len(of_campaign)}))
    current = of_campaign[cycle_index] if cycle_index < len(of_campaign) else None

    if declared_crop:
        crop = Sourced(declared_crop, DECLARED, "plan")
        if _species(current) and _species(current) != declared_crop:
            notices.append(Notice("crop_differs_from_cycle",
                                  {"declared": declared_crop, "cycle": _species(current)}))
    elif _species(current):
        crop = Sourced(_species(current), MEASURED, f"{_SOURCE}:{current.get('crop_id')}")
    else:
        crop = missing(_SOURCE)
        absent.append(MissingInput("crop", "plan", {"campaign": campaign}))

    previous_campaign: int | None
    if declared_previous:
        previous = Sourced(declared_previous, DECLARED, "plan")
        previous_campaign = campaign - 1
    elif cycle_index > 0:
        # The crop before a later crop of the campaign is the campaign's own earlier cycle,
        # recorded or not the later one yet.
        last = of_campaign[cycle_index - 1] if len(of_campaign) >= cycle_index else None
        if last is None:
            notices.append(Notice("double_crop_first_cycle_unknown", {"campaign": campaign}))
        if _species(last):
            previous = Sourced(_species(last), MEASURED, f"{_SOURCE}:{last.get('crop_id')}")
            previous_campaign = last.get("campaign_label")
        else:
            previous = missing(_SOURCE)
            previous_campaign = None
            absent.append(MissingInput("previous_crop", "plan", {"campaign": campaign}))
    else:
        start = _date(current, "start") if current else None
        if start:
            before = [c for c in mains if c is not current and _date(c, "end")
                      and _date(c, "end") <= start]
        else:
            before = [c for c in mains if _date(c, "end")
                      and isinstance(c.get("campaign_label"), int)
                      and c["campaign_label"] < campaign]
        last = max(before, key=lambda c: _date(c, "end"), default=None)
        if _species(last):
            previous = Sourced(_species(last), MEASURED, f"{_SOURCE}:{last.get('crop_id')}")
            previous_campaign = last.get("campaign_label")
        else:
            previous = missing(_SOURCE)
            previous_campaign = None
            absent.append(MissingInput("previous_crop", "plan", {"campaign": campaign}))
    return CropChoice(crop, previous, previous_campaign, tuple(notices), tuple(absent))
