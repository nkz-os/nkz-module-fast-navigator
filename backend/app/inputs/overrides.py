"""Which values a person may type over a source's, their ranges, and who may (spec §6, D11)."""
from __future__ import annotations

import math
import re

from app.engine.types import CROP_TYPES

FARMER_PARAMS = re.compile(r"organic\.(0|[1-9][0-9]*)\.availability")
_CROP = {"dm_product_pct": (0.01, 100.0), "harvest_index_pct": (0.01, 100.0),
         "residue_left_pct": (0.0, 100.0), "n_product_pct": (0.0, 10.0),
         "n_min_product_pct": (0.0, 10.0), "p_product_pct": (0.0, 10.0),
         "k_product_pct": (0.0, 10.0), "n_residue_pct": (0.0, 10.0),
         "p_residue_pct": (0.0, 10.0), "k_residue_pct": (0.0, 10.0)}
_YIELD = {"kg_ha": (1.0, 200_000.0), "cv_pct": (0.0, 100.0)}
_SOIL = {"sand_pct": (0.0, 100.0), "clay_pct": (0.0, 100.0), "ph": (0.0, 14.0),
         "organic_matter_pct": (0.0, 100.0), "p_olsen_mg_kg": (0.0, 500.0),
         "k_mg_kg": (0.0, 3000.0), "texture_class": (1.0, 6.0),
         "bulk_density_g_cm3": (0.1, 2.65)}


def farmer_may_override(param: str) -> bool:
    """Owner 2026-10-13: the non-technician editor sets the N availability of organic inputs;
    nothing else. Since 2026-10-31 that editor is the holder (TenantAdmin); Farmer only reads."""
    return bool(FARMER_PARAMS.fullmatch(param))


def check_override(param: str, value) -> None:
    head, _, tail = param.partition(".")
    if head in ("crop", "previous_crop") and tail == "crop_type":
        if value not in CROP_TYPES:
            raise ValueError(f"{param} must be one of {', '.join(CROP_TYPES)}")
        return
    if head in ("crop", "previous_crop") and tail == "n_fixing":
        if not isinstance(value, bool):
            raise ValueError(f"{param} must be true or false")
        return
    if head in ("crop", "previous_crop"):
        bounds = _CROP.get(tail)
    elif head in ("yield", "previous_yield"):
        bounds = _YIELD.get(tail)
    elif head == "soil":
        bounds = _SOIL.get(tail)
    elif param == "irrigation.uptake" or FARMER_PARAMS.fullmatch(param):
        bounds = (0.0, 1.0)
    else:
        bounds = None
    if bounds is None:
        raise ValueError(f"{param} cannot be overridden")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{param} must be a finite number")
    low, high = bounds
    if not low <= value <= high:
        raise ValueError(f"{param} must be within {low:g}-{high:g}")
    if tail == "texture_class" and int(value) != value:
        raise ValueError(f"{param} must be a whole class 1-6")
