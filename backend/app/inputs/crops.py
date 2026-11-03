"""Crop and preceding crop of a sheet: the parcel's crop cycles, or what the user declares."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from .provenance import DECLARED, MEASURED, MissingInput, Notice, Sourced, missing

EPPO = re.compile(r"^[A-Z0-9]{5,6}$")
FALLOW = "fallow"
MAIN_ROLE = "main_crop"   # the platform's crop-cycle vocabulary; "cover_crop" is the other one
_SOURCE = "broker:crop-cycles"


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


def _flag_species(cycle: dict | None, notices: list[Notice]) -> None:
    """A cycle that would have been the crop but whose species is not an EPPO code."""
    if cycle is not None and not _species(cycle):
        notices.append(Notice("cycle_species_not_eppo", {
            "species": cycle.get("species"), "crop_id": cycle.get("crop_id")}))


def _is_pending(cycle: dict | None) -> bool:
    """A planned cycle whose start is past, with no sowing fact and not closed: never confirmed."""
    return cycle is not None and cycle.get("pending") is True


def _flag_pending(cycle: dict, notices: list[Notice]) -> None:
    notices.append(Notice("previous_cycle_pending", {
        "crop_id": cycle.get("crop_id"), "campaign": cycle.get("campaign_label")}))


def _mains(cycles: list[dict]) -> list[dict]:
    return sorted((c for c in cycles if is_main(c)), key=lambda c: _date(c, "start") or date.min)


def _in_campaign(cycle: dict, campaign: int) -> bool:
    """Whether the cycle is a crop of the campaign: a perennial is, from its planting year until
    the year it ends (open end = still living); any other cycle by its campaign label.
    A perennial with no start date (declared only) falls back to its campaign label.
    Mirrors nkz_platform_sdk.crop_cycles.CropCycle.in_campaign over to_dict output;
    keep it in step with that method."""
    if cycle.get("lifecycle") != "perennial":
        return cycle.get("campaign_label") == campaign
    start = _date(cycle, "start")
    if start is None:
        return cycle.get("campaign_label") == campaign
    if start.year > campaign:
        return False
    end = _date(cycle, "end")
    return end is None or end.year >= campaign


def _is_declared_only(cycle: dict) -> bool:
    """A past crop the farmer declared by campaign alone: no start, no end, a declared campaign."""
    return (cycle.get("declared_campaign") is not None
            and _date(cycle, "start") is None and _date(cycle, "end") is None)


def campaign_main_cycles(cycles: list[dict], campaign: int) -> list[dict]:
    """Main-crop cycles of a campaign, ordered by start.

    A declared-only cycle is history: it is never the crop of the campaign being computed.
    """
    return [c for c in _mains(cycles) if _in_campaign(c, campaign) and not _is_declared_only(c)]


def _declared_previous(mains: list[dict], campaign: int) -> dict | None:
    """The declared-only main cycle of the campaign right before, when the dated rule finds none."""
    return next((c for c in mains if _is_declared_only(c)
                 and c.get("campaign_label") == campaign - 1), None)


def cycle_view(cycle: dict | None) -> dict | None:
    """The chosen cycle as the UI needs it: id, start with provenance, pending, status."""
    if cycle is None:
        return None
    start = cycle.get("start") or {}
    return {"crop_id": cycle.get("crop_id"),
            "start": {"date": start.get("date"), "provenance": start.get("provenance")},
            "pending": cycle.get("pending") is True,
            "status": cycle.get("status")}


def crops_for_campaign(cycles: list[dict], campaign: int, cycle_index: int = 0,
                       declared_crop: str | None = None,
                       declared_previous: str | None = None) -> CropChoice:
    notices: list[Notice] = []
    absent: list[MissingInput] = []
    mains = _mains(cycles)
    of_campaign = campaign_main_cycles(cycles, campaign)
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
        _flag_species(current, notices)

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
        if _is_pending(last):
            _flag_pending(last, notices)
            last = None
        if _species(last):
            previous = Sourced(_species(last), MEASURED, f"{_SOURCE}:{last.get('crop_id')}")
            previous_campaign = last.get("campaign_label")
        else:
            previous = missing(_SOURCE)
            previous_campaign = None
            absent.append(MissingInput("previous_crop", "plan", {"campaign": campaign}))
            _flag_species(last, notices)
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
        declared_before = _declared_previous(mains, campaign)
        if declared_before is not None and (
                last is None or not isinstance(last.get("campaign_label"), int)
                or last["campaign_label"] < campaign - 1):
            last = declared_before   # the declared cycle wins only when strictly later
        if _is_pending(last):
            # A planned cycle never confirmed is not a crop that was grown: never fall back to the
            # older confirmed cycle behind it, the previous crop is the one the user declares.
            _flag_pending(last, notices)
            last = None
        if _species(last):
            previous = Sourced(_species(last), MEASURED, f"{_SOURCE}:{last.get('crop_id')}")
            previous_campaign = last.get("campaign_label")
        else:
            previous = missing(_SOURCE)
            previous_campaign = None
            absent.append(MissingInput("previous_crop", "plan", {"campaign": campaign}))
            _flag_species(last, notices)
    return CropChoice(crop, previous, previous_campaign, tuple(notices), tuple(absent))


def cover_before(cycles: list[dict], campaign: int) -> str | None:
    """EPPO of the cover crop grown right before the campaign's main crop, as a hint only.

    The cover crop must end by the main crop's start and after the previous main crop's end;
    the engine does not model it (no N credit), so it never changes the previous crop.
    """
    of_campaign = campaign_main_cycles(cycles, campaign)
    start = _date(of_campaign[0], "start") if of_campaign else None
    if start is None:
        return None
    floor = max((e for c in _mains(cycles) if c is not of_campaign[0]
                 and (e := _date(c, "end")) and e <= start), default=date.min)
    covers = [c for c in cycles if not is_main(c) and _species(c)
              and (end := _date(c, "end")) and floor < end <= start]
    last = max(covers, key=lambda c: _date(c, "end"), default=None)
    return _species(last)
