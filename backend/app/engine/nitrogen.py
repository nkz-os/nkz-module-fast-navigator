"""N requirement, Eq. 6 of Villalobos et al. (2020), ported from the reference script."""
from __future__ import annotations

import math

from . import constants as C
from .types import CropSeason, Management, NResult, NTerms, SoilState


def _nc_product(season: CropSeason, strategy: int) -> float:
    crop = season.crop
    pct = crop.n_min_product_pct if strategy in (1, 2) else crop.n_product_pct
    return pct / 100


def _dm(season: CropSeason, yield_kg_ha: float) -> tuple[float, float]:
    """(product DM, residue DM) in kg/ha for a fresh yield."""
    hi = season.crop.harvest_index_pct / 100
    y_dm = yield_kg_ha * season.crop.dm_product_pct / 100
    return y_dm, y_dm * (1 - hi) / hi


def _fixation_share(season: CropSeason, organic_matter_pct: float) -> float:
    if not season.crop.n_fixing:
        return 0.0
    low, high = (C.FIXATION_FORAGE_LEGUME if season.crop.crop_type == "forage_legume"
                 else C.FIXATION_GRAIN_LEGUME)
    return low if organic_matter_pct < C.FIXATION_SOM_THRESHOLD_PCT else high


def _tree_rate(season: CropSeason, previous: CropSeason | None, mgmt: Management,
               yield_kg_ha: float, nc_y: float) -> float:
    hi = season.crop.harvest_index_pct / 100
    y_dm, _ = _dm(season, yield_kg_ha)
    fres_prev = previous.crop.residue_left_pct / 100 if previous else 0.0
    best = fres_prev * (1 if mgmt.tillage else 0) == 1 \
        and not season.previous_residues_burned and mgmt.irrigated
    coef = 0.25 if best else 0.75
    return y_dm * (nc_y + C.TREE_BETA * (1 - hi) / hi * 0.01 * coef) / C.TREE_EFFICIENCY


def n_requirement(current: CropSeason, previous: CropSeason | None, soil: SoilState,
                  mgmt: Management, irrigation_n_kg_ha: float = 0.0) -> NResult:
    """N fertilizer requirement for 9 yield probability levels, before soil/organic credits.

    `previous` is the crop that precedes `current` (residue and root credits); None for
    fallow or no previous crop (both credits 0). `irrigation_n_kg_ha` is the N the crop takes
    from the irrigation water (corrections.irrigation_n): added to Nother in the balance and
    subtracted from the rate of trees, whose formula has no Nother term.
    """
    if isinstance(irrigation_n_kg_ha, bool) or not isinstance(irrigation_n_kg_ha, (int, float)) \
            or not math.isfinite(irrigation_n_kg_ha) or irrigation_n_kg_ha < 0:
        raise ValueError("irrigation_n_kg_ha must be a finite number >= 0")
    nc_y = _nc_product(current, mgmt.strategy)
    nr = current.crop.n_residue_pct / 100
    if previous is None:
        nc_yp = nrp = yp_dm = rp_dm = fres_p = 0.0
        kim = 0.0
    else:
        nc_yp = _nc_product(previous, mgmt.strategy)
        nrp = previous.crop.n_residue_pct / 100
        yp_dm, rp_dm = _dm(previous, previous.yield_kg_ha)
        kim = 0.5 + 0.2 * ((1 if previous.crop.n_fixing else 0) + (1 if mgmt.tillage else 0))
        fres_p = previous.crop.residue_left_pct / 100
    burn_p = 1 if current.previous_residues_burned else 0
    n_other = C.N_OTHER_KG_HA + irrigation_n_kg_ha
    divisor = 1 - C.N_LOSS_FRACTION
    fix_share = _fixation_share(current, soil.organic_matter_pct)

    levels: list[float] = []
    avg_terms: NTerms | None = None
    for i, t in enumerate(C.T_LEVELS):
        y_i = current.yield_kg_ha * (1 + current.yield_cv_pct / 100 * t)
        if current.crop.crop_type == "tree":
            # Trees: no balance, the whole demand goes under crop_uptake.
            demand = _tree_rate(current, previous, mgmt, y_i, nc_y)
            rate = demand - irrigation_n_kg_ha
            terms = NTerms(demand, 0.0, 0.0, 0.0, -irrigation_n_kg_ha, 0.0, 1.0)
        else:
            y_dm, r_dm = _dm(current, y_i)
            uptake = (1 + C.F_NR) * (y_dm * nc_y + r_dm * nr)
            prev_res = -(1 - burn_p) * kim * fres_p * rp_dm * nrp
            prev_roots = -C.F_NR * (yp_dm * nc_yp + rp_dm * nrp)
            fixation = -uptake * fix_share
            rate = (C.N_END_KG_HA + uptake + prev_res + prev_roots - n_other + fixation) / divisor
            terms = NTerms(uptake, C.N_END_KG_HA, prev_res, prev_roots, -n_other, fixation, divisor)
        levels.append(max(rate, 0.0))
        if i == C.LEVEL_AVG:
            avg_terms = terms
    return NResult(tuple(levels), levels[C.LEVEL_MIN], levels[C.LEVEL_AVG],
                   levels[C.LEVEL_MAX], avg_terms)
