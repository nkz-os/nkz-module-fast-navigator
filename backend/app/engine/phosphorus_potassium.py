"""P and K requirements (strategies 1-4), ported from the reference script."""
from __future__ import annotations

from . import constants as C
from .types import CropSeason, Management, NutrientRate, SoilState

SOIL_CLASSES = ("low", "medium", "high")
DOSE_BASES = ("buildup", "buildup_and_export", "export", "half_export", "none")


def _soil_class(value: float, threshold: float, high_from: float) -> str:
    """Soil class from the same comparisons that pick the dose."""
    if value < threshold:
        return "low"
    return "medium" if value < high_from else "high"


def _dm(season: CropSeason) -> tuple[float, float]:
    hi = season.crop.harvest_index_pct / 100
    y_dm = season.yield_kg_ha * season.crop.dm_product_pct / 100
    return y_dm, y_dm * (1 - hi) / hi


def _exported(season: CropSeason, product_pct: float, residue_pct: float) -> float:
    y_dm, r_dm = _dm(season)
    fres = season.crop.residue_left_pct / 100
    return y_dm * product_pct / 100 + r_dm * (1 - fres) * residue_pct / 100


def p_threshold(season: CropSeason, soil: SoilState, strategy: int) -> float:
    """Olsen P threshold, mg/kg. Uses the measured clay (spec §6)."""
    if season.crop.eppo == C.RICE_EPPO:
        return C.RICE_P_THRESHOLD
    thres = 49 - 0.016 * 10 * soil.clay_pct - 3.81 * soil.ph
    if season.crop.crop_type == "tuber_root":
        thres += 7
    elif strategy == 3:
        thres += 3
    return thres


def p_requirement(season: CropSeason, soil: SoilState, mgmt: Management,
                  rotation_years: int) -> NutrientRate:
    if rotation_years < 1:
        raise ValueError("rotation_years must be >= 1")
    exported = _exported(season, season.crop.p_product_pct, season.crop.p_residue_pct)
    thres = p_threshold(season, soil, mgmt.strategy)
    if mgmt.strategy == 4:
        return NutrientRate(exported, exported, 0.0, thres, None, None, "export")
    bd = C.CLASS_BULK_DENSITY[soil.texture_class]
    buildup = max(10 * bd * C.SAMPLING_DEPTH_M * (thres - soil.p_olsen_mg_kg), 0.0)
    per_year = min(buildup / rotation_years, C.P_BUILDUP_MAX_KG_HA_YEAR)
    high_from = 2 * thres
    cls = _soil_class(soil.p_olsen_mg_kg, thres, high_from)
    if mgmt.strategy == 1:
        rate, basis = per_year, "buildup"
    elif cls == "low":
        rate, basis = per_year + exported, "buildup_and_export"
    elif cls == "medium":
        rate, basis = exported, "export"
    else:
        rate, basis = 0.5 * exported, "half_export"
    return NutrientRate(rate, exported, per_year, thres, cls, high_from, basis)


def k_requirement(season: CropSeason, soil: SoilState, mgmt: Management,
                  rotation_years: int) -> NutrientRate:
    if rotation_years < 1:
        raise ValueError("rotation_years must be >= 1")
    exported = _exported(season, season.crop.k_product_pct, season.crop.k_residue_pct)
    cls = soil.texture_class
    if mgmt.strategy in (1, 2):
        thres, fk = C.K_THRESHOLD_LOW[cls], C.K_FIX_LOW[cls]
    else:
        thres, fk = C.K_THRESHOLD_HIGH[cls], C.K_FIX_HIGH[cls]
    if mgmt.strategy == 4:
        # The reference script returns the P export here (`k_rate = p_exported`), a bug.
        return NutrientRate(exported, exported, 0.0, thres, None, None, "export")
    bd = C.CLASS_BULK_DENSITY[cls]
    buildup = max(10 * bd * fk * C.SAMPLING_DEPTH_M * (thres - soil.k_mg_kg), 0.0)
    per_year = min(buildup / rotation_years, C.K_BUILDUP_MAX_KG_HA_YEAR)
    high_from = (2 if cls < 6 else 1.5) * thres
    soil_cls = _soil_class(soil.k_mg_kg, thres, high_from)
    if mgmt.strategy == 1:
        rate, basis = per_year, "buildup"
    elif soil_cls == "low":
        rate, basis = per_year + exported, "buildup_and_export"
    elif soil_cls == "medium":
        rate, basis = exported, "export"
    elif cls < 6:
        rate, basis = 0.5 * exported, "half_export"
    else:
        rate, basis = 0.0, "none"
    return NutrientRate(rate, exported, per_year, thres, soil_cls, high_from, basis)
