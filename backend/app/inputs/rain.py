"""Normal rainfall of the parcel and its distribution over the year (art. 6.3)."""
from __future__ import annotations

import calendar
import statistics
from dataclasses import dataclass

from .provenance import Notice

RAIN_YEARS = 10


def rain_years(campaign: int) -> list[int]:
    """The ten calendar years before the year the plan is written in (campaign − 1)."""
    return list(range(campaign - 1 - RAIN_YEARS, campaign - 1))


@dataclass(frozen=True)
class RainNormal:
    years: tuple[int, ...]
    annual_mm: float | None
    monthly_mm: tuple[float, ...]
    sources: tuple[str, ...]
    notices: tuple[Notice, ...]

    def to_dict(self) -> dict:
        return {"years": list(self.years), "annual_mm": self.annual_mm,
                "monthly_mm": list(self.monthly_mm), "sources": list(self.sources),
                "notices": [n.to_dict() for n in self.notices]}


def rain_normal(days_by_year: dict[int, list[dict]]) -> RainNormal:
    complete: dict[int, list[float]] = {}
    incomplete: list[int] = []
    sources: set[str] = set()
    for year, days in sorted(days_by_year.items()):
        monthly = [0.0] * 12
        seen: set[str] = set()
        for d in days:
            mm, day = d.get("precip_mm"), d.get("date")
            if isinstance(mm, bool) or not isinstance(mm, (int, float)) or not isinstance(day, str):
                continue
            if not day.startswith(f"{year}-") or day in seen:
                continue
            seen.add(day)
            monthly[int(day[5:7]) - 1] += float(mm)
            if d.get("source"):
                sources.add(str(d["source"]))
        if len(seen) == (366 if calendar.isleap(year) else 365):
            complete[year] = monthly
        else:
            incomplete.append(year)
    notices: list[Notice] = []
    if incomplete:
        notices.append(Notice("rain_years_incomplete", {"years": incomplete}))
    if len(complete) < RAIN_YEARS:
        notices.append(Notice("rain_normal_short_series", {"years": len(complete)}))
    if not complete:
        return RainNormal((), None, (), tuple(sorted(sources)), tuple(notices))
    monthly_mean = tuple(statistics.fmean(m[i] for m in complete.values()) for i in range(12))
    return RainNormal(tuple(complete), sum(monthly_mean), monthly_mean, tuple(sorted(sources)),
                      tuple(notices))
