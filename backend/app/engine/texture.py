"""Soil inputs to the engine: FertiliCalc texture class and Olsen-equivalent P."""
from __future__ import annotations

from . import constants as C


def texture_class(sand_pct: float, clay_pct: float) -> int:
    """Nearest FertiliCalc class (1..6) by (sand, clay) distance to the class table.

    The script takes the class as a user choice; the class centres are its `sand`/`clay`
    tables. Ties go to the lower class.
    """
    if not (0 <= sand_pct <= 100 and 0 <= clay_pct <= 100 and sand_pct + clay_pct <= 100):
        raise ValueError("sand and clay must be percentages summing to <= 100")
    best, best_d = 1, float("inf")
    for cls in range(1, 7):
        d = (sand_pct - C.CLASS_SAND[cls]) ** 2 + (clay_pct - C.CLASS_CLAY[cls]) ** 2
        if d < best_d:
            best, best_d = cls, d
    return best


def olsen_equivalent(value_mg_kg: float, method: str) -> float:
    """Convert a soil P test to its Olsen equivalent (Table 5)."""
    try:
        factor = C.OLSEN_FACTOR[method]
    except KeyError:
        raise ValueError(f"unknown soil P method {method!r}") from None
    if value_mg_kg < 0:
        raise ValueError("soil P must be >= 0")
    return value_mg_kg * factor
