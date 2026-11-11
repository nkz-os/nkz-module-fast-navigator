"""Nitrogen dose per zone by relative vigor (pure arithmetic, no I/O; contract §5).

The factor of a zone is its relative vigor (`potential`) or the mirror 2 - vigor (`compensate`),
scaled by the one number that keeps the area-weighted mean factor at 1 once every factor is
clipped to [1 - cap, 1 + cap]: the dose of the parcel is shared, not changed. Zones without a vegetation value take the target dose and
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


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(x, hi))


def _share(raw: list[float], area: list[float], lo: float, hi: float
           ) -> tuple[list[float], list[bool], bool]:
    """Factors clip(raw * s, lo, hi) with the one scale s that makes the area-weighted mean 1.

    The weighted mean of clip(raw * s) grows monotonically with s, from lo (s = 0) to at least 1
    (every zone with raw > 0 on hi): with lo < 1 < hi it always crosses 1, so the mean is always
    kept. A bisection finds s; the zones it leaves strictly inside the bounds then get s solved
    exactly, so the returned mean is 1 to rounding. A zone is capped when raw * s passes a bound.
    The third value is True only if the mean could not be reached (never expected; reported).
    """
    total = sum(area)

    def mean(scale: float) -> float:
        return sum(a * _clip(r * scale, lo, hi) for a, r in zip(area, raw)) / total

    positive = [r for r in raw if r > 0]
    s_lo, s_hi = 0.0, hi / min(positive)        # at s_hi every positive raw is on hi
    if mean(s_hi) < 1.0 - 1e-12:
        out = [_clip(r * s_hi, lo, hi) for r in raw]
        return out, [r * s_hi > hi + _EPS or r * s_hi < lo - _EPS for r in raw], True
    for _ in range(200):
        mid = (s_lo + s_hi) / 2
        if mean(mid) < 1.0:
            s_lo = mid
        else:
            s_hi = mid
    scale = (s_lo + s_hi) / 2
    free = [i for i, r in enumerate(raw) if lo + _EPS < r * scale < hi - _EPS]
    if free:
        pinned_part = sum(area[i] * _clip(raw[i] * scale, lo, hi)
                          for i in range(len(raw)) if i not in free)
        exact = (total - pinned_part) / sum(area[i] * raw[i] for i in free)
        if all(lo <= raw[i] * exact <= hi for i in free):
            scale = exact
    out = [_clip(r * scale, lo, hi) for r in raw]
    capped = [r * scale > hi + 1e-9 or r * scale < lo - 1e-9 for r in raw]
    reached = abs(sum(a * f for a, f in zip(area, out)) / total - 1.0) <= 1e-9
    return out, capped, not reached


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
