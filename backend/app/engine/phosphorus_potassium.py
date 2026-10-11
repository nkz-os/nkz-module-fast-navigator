"""P and K requirements (strategies 1-4), ported from the reference script."""
from __future__ import annotations

from . import constants as C
from .types import CropSeason, Management, NutrientRate, SoilState


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
        return NutrientRate(exported, exported, 0.0, thres)
    bd = C.CLASS_BULK_DENSITY[soil.texture_class]
    buildup = max(10 * bd * C.SAMPLING_DEPTH_M * (thres - soil.p_olsen_mg_kg), 0.0)
    per_year = min(buildup / rotation_years, C.P_BUILDUP_MAX_KG_HA_YEAR)
    if mgmt.strategy == 1:
        rate = per_year
    elif soil.p_olsen_mg_kg < thres:
        rate = per_year + exported
    elif soil.p_olsen_mg_kg < 2 * thres:
        rate = exported
    else:
        rate = 0.5 * exported
    return NutrientRate(rate, exported, per_year, thres)


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
        return NutrientRate(exported, exported, 0.0, thres)
    bd = C.CLASS_BULK_DENSITY[cls]
    buildup = max(10 * bd * fk * C.SAMPLING_DEPTH_M * (thres - soil.k_mg_kg), 0.0)
    per_year = min(buildup / rotation_years, C.K_BUILDUP_MAX_KG_HA_YEAR)
    if mgmt.strategy == 1:
        rate = per_year
    elif soil.k_mg_kg < thres:
        rate = per_year + exported
    elif cls < 6:
        rate = exported if soil.k_mg_kg < 2 * thres else 0.5 * exported
    else:
        rate = exported if soil.k_mg_kg < 1.5 * thres else 0.0
    return NutrientRate(rate, exported, per_year, thres)
