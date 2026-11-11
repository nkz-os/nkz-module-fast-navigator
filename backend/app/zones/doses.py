"""Nitrogen dose per zone by relative vigor (pure arithmetic, no I/O; contract §5).

The factor of a zone is its relative vigor (`potential`) or the mirror 2 - vigor (`compensate`),
clipped to [1 - cap, 1 + cap] and rescaled so that the area-weighted mean factor is 1: the dose
of the parcel is shared, not changed. Zones without a vegetation value take the target dose and
stay out of the share.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

STRATEGIES = ("uniform", "potential", "compensate")
MAX_CAP_PCT = 30.0
_EPS = 1e-12


@dataclass(frozen=True)
class ZoneInput:
    key: str
    area_ha: float
    mean_value: float | None      # mean of the vegetation index in the zone; None = unknown


@dataclass(frozen=True)
class ZoneDose:
    key: str
    relative_vigor: float | None
    factor: float | None          # None: the zone has no value, it takes the target as is
    capped: bool                  # pinned to a cap bound
    n_kg_ha: float


@dataclass(frozen=True)
class Distribution:
    zones: tuple[ZoneDose, ...]
    # True when every shared zone ended on a bound and the weighted mean factor is not 1.
    saturated: bool


def _positive(value: float | None) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value) and value > 0


def _validate(zones: list[ZoneInput], strategy: str, cap_pct: float, target_n: float) -> None:
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy {strategy!r}")
    if not zones:
        raise ValueError("no zones")
    if not (isinstance(cap_pct, (int, float)) and math.isfinite(cap_pct)
            and 0 <= cap_pct <= MAX_CAP_PCT):
        raise ValueError(f"cap_pct must lie in 0..{MAX_CAP_PCT:g}")
    if not (isinstance(target_n, (int, float)) and math.isfinite(target_n) and target_n >= 0):
        raise ValueError("target_n must be a finite number >= 0")
    for z in zones:
        if not _positive(z.area_ha):
            raise ValueError(f"zone {z.key}: area must be a finite number > 0")
        if z.mean_value is not None and not _positive(z.mean_value):
            raise ValueError(f"zone {z.key}: mean value must be a finite number > 0")


def _share(raw: list[float], area: list[float], lo: float, hi: float
           ) -> tuple[list[float], list[bool], bool]:
    """Clip `raw` (area-weighted mean 1) to [lo, hi] and rescale the free zones to mean 1.

    Zones outside the bounds are pinned on them and stay pinned; the free zones are multiplied by
    the one factor s that makes the weighted mean 1. Zones that s pushes outside the bounds are
    pinned in the next pass. Stops when stable. When no zone is free and the mean is not 1 the
    bounds are kept and the third value is True.
    """
    n = len(raw)
    total = sum(area)
    pinned: dict[int, float] = {}
    for i, f in enumerate(raw):
        if f > hi + _EPS:
            pinned[i] = hi
        elif f < lo - _EPS:
            pinned[i] = lo
    while True:
        free = [i for i in range(n) if i not in pinned]
        if not free:
            mean = sum(area[i] * pinned[i] for i in range(n)) / total
            return [pinned[i] for i in range(n)], [True] * n, abs(mean - 1.0) > 1e-9
        rest = total - sum(area[i] * pinned[i] for i in pinned)
        scale = rest / sum(area[i] * raw[i] for i in free)
        grew = False
        for i in free:
            f = raw[i] * scale
            if f > hi + _EPS:
                pinned[i], grew = hi, True
            elif f < lo - _EPS:
                pinned[i], grew = lo, True
        if not grew:
            out = [pinned[i] if i in pinned else raw[i] * scale for i in range(n)]
            return out, [i in pinned for i in range(n)], False


def distribute(zones: list[ZoneInput], strategy: str, cap_pct: float, target_n_kg_ha: float
               ) -> Distribution:
    """Dose per zone. Raises ValueError on invalid inputs (non-positive areas or values...)."""
    _validate(zones, strategy, cap_pct, target_n_kg_ha)
    valued = [z for z in zones if z.mean_value is not None]
    if strategy == "uniform" or not valued:
        return Distribution(tuple(ZoneDose(z.key, None, 1.0 if strategy == "uniform" else None,
                                           False, target_n_kg_ha) for z in zones), False)
    area = [z.area_ha for z in valued]
    mean = sum(z.area_ha * z.mean_value for z in valued) / sum(area)
    vigor = [z.mean_value / mean for z in valued]
    raw = vigor if strategy == "potential" else [2.0 - v for v in vigor]
    cap = cap_pct / 100.0
    if any(f <= 0 for f in raw):
        # compensate with a relative vigor >= 2: a factor <= 0 is clipped to the lower bound
        raw = [max(f, 0.0) for f in raw]
    factors, pinned, saturated = _share(raw, area, 1.0 - cap, 1.0 + cap) if cap > 0 else (
        [1.0] * len(raw), [abs(f - 1.0) > _EPS for f in raw], False)
    by_key = {z.key: (v, f, p) for z, v, f, p in zip(valued, vigor, factors, pinned)}
    out = []
    for z in zones:
        if z.key in by_key:
            v, f, p = by_key[z.key]
            out.append(ZoneDose(z.key, v, f, p, target_n_kg_ha * f))
        else:
            out.append(ZoneDose(z.key, None, None, False, target_n_kg_ha))
    return Distribution(tuple(out), saturated)
