"""Soil inputs to the engine: FertiliCalc texture class and Olsen-equivalent P."""
from __future__ import annotations

import math

from . import constants as C

# USDA texture class -> FertiliCalc class, by USDA texture group (Soil Survey Manual):
# coarse 1, moderately coarse 2, medium: loam 3 and silty 4, moderately fine 5, fine 6.
# The FertiliCalc classes are named sand, sandy loam, loam, silt loam, clay loam, clay
# (their sand/clay centres are the script's tables).
_USDA_TO_CLASS = {
    "sand": 1, "loamy sand": 1, "sandy loam": 2, "loam": 3, "silt loam": 4, "silt": 4,
    "sandy clay loam": 5, "clay loam": 5, "silty clay loam": 5,
    "sandy clay": 6, "silty clay": 6, "clay": 6,
}


def usda_texture(sand_pct: float, clay_pct: float) -> str:
    """USDA texture class (same rules as the platform soil module)."""
    silt = 100 - sand_pct - clay_pct
    sand, clay = sand_pct, clay_pct
    if clay >= 40 and silt >= 40:
        return "silty clay"
    if clay >= 40 and sand <= 45 and silt < 40:
        return "clay"
    if clay >= 35 and sand > 45:
        return "sandy clay"
    if 27 <= clay < 40 and sand <= 20:
        return "silty clay loam"
    if 27 <= clay < 40 and 20 < sand <= 45:
        return "clay loam"
    if 20 <= clay < 35 and silt < 28 and sand > 45:
        return "sandy clay loam"
    if silt >= 80 and clay < 12:
        return "silt"
    if (silt >= 50 and 12 <= clay < 27) or (50 <= silt < 80 and clay < 12):
        return "silt loam"
    if 7 <= clay < 27 and 28 <= silt < 50 and sand <= 52:
        return "loam"
    if ((7 <= clay < 20 and sand > 52 and silt + 2 * clay >= 30)
            or (clay < 7 and silt < 50 and silt + 2 * clay >= 30)):
        return "sandy loam"
    if silt + 1.5 * clay >= 15 and silt + 2 * clay < 30:
        return "loamy sand"
    if silt + 1.5 * clay < 15:
        return "sand"
    return "loam"  # boundary gaps of the triangle


def texture_class(sand_pct: float, clay_pct: float) -> int:
    """FertiliCalc class (1..6) of a measured texture, through its USDA class."""
    for v in (sand_pct, clay_pct):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError("sand and clay must be finite numbers")
    if not (0 <= sand_pct <= 100 and 0 <= clay_pct <= 100 and sand_pct + clay_pct <= 100):
        raise ValueError("sand and clay must be percentages summing to <= 100")
    return _USDA_TO_CLASS[usda_texture(sand_pct, clay_pct)]


def olsen_equivalent(value_mg_kg: float, method: str) -> float:
    """Convert a soil P test to its Olsen equivalent (Table 5)."""
    try:
        factor = C.OLSEN_FACTOR[method]
    except KeyError:
        raise ValueError(f"unknown soil P method {method!r}") from None
    if isinstance(value_mg_kg, bool) or not isinstance(value_mg_kg, (int, float)) \
            or not math.isfinite(value_mg_kg) or value_mg_kg < 0:
        raise ValueError("soil P must be a finite number >= 0")
    return value_mg_kg * factor
