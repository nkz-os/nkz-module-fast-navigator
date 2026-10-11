"""N credits applied after the balance (paper l. 255-265) and the irrigation-water N term."""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import constants as C
from .types import NAdjusted, NCredits, NResult

_N_PER_NO3 = 14.0 / 62.0


def _check_finite(*values: float) -> None:
    for v in values:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError("values must be finite numbers")


@dataclass(frozen=True)
class MineralNLayer:
    depth_from_cm: float
    depth_to_cm: float
    nitrate_n_mg_kg: float      # N as nitrate, mg N/kg
    ammonium_n_mg_kg: float     # N as ammonium, mg N/kg
    bulk_density_g_cm3: float


@dataclass(frozen=True)
class OrganicInput:
    total_n_kg_ha: float        # N applied with the material this campaign
    availability: float         # share available this campaign (0..1), from the rules data


def soil_mineral_n(layers: list[MineralNLayer]) -> float:
    """Measured soil mineral N credit, kg N/ha, already × the 0.9 efficiency."""
    total = 0.0
    for layer in layers:
        _check_finite(layer.depth_from_cm, layer.depth_to_cm, layer.nitrate_n_mg_kg,
                      layer.ammonium_n_mg_kg, layer.bulk_density_g_cm3)
        thickness = layer.depth_to_cm - layer.depth_from_cm
        if thickness <= 0:
            raise ValueError("depth_to_cm must be > depth_from_cm")
        if min(layer.nitrate_n_mg_kg, layer.ammonium_n_mg_kg) < 0:
            raise ValueError("mineral N must be >= 0")
        if not 0.1 <= layer.bulk_density_g_cm3 <= 2.65:
            raise ValueError("bulk density must be 0.1-2.65 g/cm3")
        # mg/kg × g/cm3 × cm × 0.1 = kg/ha
        total += (layer.nitrate_n_mg_kg + layer.ammonium_n_mg_kg) * \
            layer.bulk_density_g_cm3 * thickness * 0.1
    return total * C.SOIL_NMIN_EFFICIENCY


def organic_available_n(inputs: list[OrganicInput]) -> float:
    total = 0.0
    for item in inputs:
        _check_finite(item.total_n_kg_ha, item.availability)
        if item.total_n_kg_ha < 0 or not 0 <= item.availability <= 1:
            raise ValueError("organic input N must be >= 0 and availability in [0, 1]")
        total += item.total_n_kg_ha * item.availability
    return total


def irrigation_n(no3_mg_l: float, water_m3_ha: float) -> float:
    """N the crop takes from the irrigation water, kg N/ha (70 % of the N applied with it)."""
    _check_finite(no3_mg_l, water_m3_ha)
    if no3_mg_l < 0 or water_m3_ha < 0:
        raise ValueError("nitrate and water volume must be >= 0")
    return no3_mg_l * water_m3_ha * _N_PER_NO3 / 1000 * C.IRRIGATION_N_UPTAKE


def apply_credits(result: NResult, credits: NCredits) -> NAdjusted:
    total = credits.soil_mineral_n + credits.organic_available_n
    return NAdjusted(
        n_min=max(result.n_min - total, 0.0),
        n_avg=max(result.n_avg - total, 0.0),
        n_max=max(result.n_max - total, 0.0),
        credits=credits,
    )
