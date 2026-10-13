"""What the rules read about a plan: its stored sheets, results and declarations (spec §7)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class SheetContext:
    key: str
    inputs: dict                    # the sheet's stored inputs (crop, management, water…)
    parcels: tuple[dict, ...]       # {"urn", "sigpac"}
    applications: tuple[dict, ...]  # stored ApplicationIn dicts
    result: dict | None             # SheetResult.to_dict(), None if not calculated
    summary: dict | None            # applications summary
    history: tuple[dict, ...] = ()  # previous campaigns of these parcels (P and K limits)
    n_adjustment: dict | None = None   # technician's justified N adjustment (annex III-I.3)

    def _item(self, name: str) -> dict:
        return ((self.result or {}).get("inputs") or {}).get(name) or {}

    def value(self, name: str):
        return self._item(name).get("value")

    def provenance(self, name: str) -> str | None:
        return self._item(name).get("provenance")


@dataclass(frozen=True)
class PlanContext:
    campaign: int
    sheets: tuple[SheetContext, ...]
    rain: dict | None
    vulnerable_zone: bool | None
    voluntary_digital_notebook: bool
    at: date                        # date the plan is judged at (signature date, or today)


def plan_area(ctx: PlanContext) -> tuple[float, bool]:
    """(total area in ha, each parcel once; whether every sheet is rainfed)."""
    areas: dict[str, float] = {}
    for sheet in ctx.sheets:
        for parcel in sheet.parcels:
            area = sheet.value(f"parcel.{parcel['urn']}.area_ha")
            if isinstance(area, (int, float)) and not isinstance(area, bool):
                areas.setdefault(parcel["urn"], float(area))
    rainfed = not any(sheet.inputs.get("irrigated") for sheet in ctx.sheets)
    return sum(areas.values()), rainfed


def _numeric(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def sheet_area(sheet: SheetContext) -> float | None:
    """Sum of the sheet's parcel areas in ha; None when any is unknown (never a silent 0)."""
    total = 0.0
    for parcel in sheet.parcels:
        area = sheet.value(f"parcel.{parcel['urn']}.area_ha")
        if not _numeric(area):
            return None
        total += float(area)
    return total


def area_known(ctx: PlanContext) -> bool:
    """True only when every sheet is calculated and every parcel has a numeric area."""
    return all(s.result is not None and sheet_area(s) is not None for s in ctx.sheets)
