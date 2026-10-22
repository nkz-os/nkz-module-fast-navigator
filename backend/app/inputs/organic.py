"""Organic inputs of the campaign: available N (MAPA 2010 defaults) and P, K credited in full."""
from __future__ import annotations

import math
from dataclasses import dataclass

from app.engine import constants as C
from app.engine.corrections import OrganicInput, organic_available_n

from .provenance import MissingInput, Notice, Override, Sourced, missing, table

ORGANIC_TABLE_VERSION = "mapa-2010-ch6-p47"
MAPA_SOURCE_ID = "mapa_guia_2010"
MATERIALS = ("cattle_manure", "other_manure", "slurry", "compost", "other")


@dataclass(frozen=True)
class AvailabilityDefault:
    value: float
    low: float
    high: float
    ref: str


# MAPA (2010) Guía práctica de la fertilización racional de los cultivos en España, ch. 6,
# p. 47. The guide gives ranges; the default is the midpoint and the range travels with it.
# It gives no figure for slurry or compost: the user declares those (owner 2026-10-13).
N_AVAILABILITY: dict[str, AvailabilityDefault] = {
    "cattle_manure": AvailabilityDefault(
        0.25, 0.20, 0.30, "MAPA 2010, ch. 6, p. 47: cattle manure, 20-30 % of its N "
                          "mineralised in the first year"),
    "other_manure": AvailabilityDefault(
        0.45, 0.40, 0.50, "MAPA 2010, ch. 6, p. 47: other manures, 40-50 % of their N "
                          "mineralised in the first year"),
}


@dataclass(frozen=True)
class OrganicApplication:
    material: str
    rate_t_ha: float      # fresh matter
    n_pct: float          # % of fresh matter, from the supplier or the holder (art. 5.1.c)
    p2o5_pct: float
    k2o_pct: float

    def __post_init__(self) -> None:
        if self.material not in MATERIALS:
            raise ValueError(f"material must be one of {', '.join(MATERIALS)}")
        for name in ("rate_t_ha", "n_pct", "p2o5_pct", "k2o_pct"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or not math.isfinite(value):
                raise ValueError(f"{name} must be a finite number")
        if self.rate_t_ha <= 0:
            raise ValueError("rate_t_ha must be > 0")
        if not all(0 <= getattr(self, n) <= 100 for n in ("n_pct", "p2o5_pct", "k2o_pct")):
            raise ValueError("contents must be 0..100 %")
        if self.n_pct + self.p2o5_pct + self.k2o_pct > 100:
            raise ValueError("N + P2O5 + K2O cannot exceed 100 %")

    @property
    def n_kg_ha(self) -> float:
        return self.rate_t_ha * 1000 * self.n_pct / 100

    @property
    def p2o5_kg_ha(self) -> float:
        return self.rate_t_ha * 1000 * self.p2o5_pct / 100

    @property
    def k2o_kg_ha(self) -> float:
        return self.rate_t_ha * 1000 * self.k2o_pct / 100


@dataclass(frozen=True)
class OrganicCredit:
    n_available_kg_ha: float
    p_kg_ha: float     # elemental P, credited in full (spec §6)
    k_kg_ha: float     # elemental K, credited in full
    availability: tuple[Sourced, ...]
    notices: tuple[Notice, ...]
    missing: tuple[MissingInput, ...]


def organic_credit(apps: list[OrganicApplication] | tuple[OrganicApplication, ...],
                   overrides: dict[str, Override]) -> OrganicCredit:
    inputs: list[OrganicInput] = []
    availability: list[Sourced] = []
    absent: list[MissingInput] = []
    for i, app in enumerate(apps):
        name = f"organic.{i}.availability"
        default = N_AVAILABILITY.get(app.material)
        if name in overrides:
            share = overrides[name].as_sourced()
        elif default is not None:
            share = Sourced(default.value, table(MAPA_SOURCE_ID), ORGANIC_TABLE_VERSION,
                            f"{default.ref} (range {default.low:g}-{default.high:g}; "
                            "default = midpoint)")
        else:
            share = missing("plan")
            absent.append(MissingInput(name, "plan", {"material": app.material}))
        availability.append(share)
        if share.known:
            inputs.append(OrganicInput(app.n_kg_ha, float(share.value)))
    p = sum(a.p2o5_kg_ha for a in apps) / C.P_TO_P2O5
    k = sum(a.k2o_kg_ha for a in apps) / C.K_TO_K2O
    return OrganicCredit(organic_available_n(inputs), p, k, tuple(availability), (), tuple(absent))
