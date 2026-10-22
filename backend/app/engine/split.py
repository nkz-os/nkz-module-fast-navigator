"""Split of the N requirement into applications and product rates (paper l. 240-248)."""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import constants as C

PRE_PLANT = "pre_plant"


@dataclass(frozen=True)
class PlannedApplication:
    stage: str                  # PRE_PLANT or a crop stage label
    product_rate_kg_ha: float
    n_pct: float                # % N of the product
    p2o5_pct: float
    k2o_pct: float
    organic: bool = False       # organic N is credited through corrections.organic_available_n

    def __post_init__(self) -> None:
        for name in ("product_rate_kg_ha", "n_pct", "p2o5_pct", "k2o_pct"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ValueError(f"{name} must be a finite number")
        if self.product_rate_kg_ha < 0:
            raise ValueError("product_rate_kg_ha must be >= 0")
        for name in ("n_pct", "p2o5_pct", "k2o_pct"):
            if not 0 <= getattr(self, name) <= 100:
                raise ValueError(f"{name} must be 0..100")
        if self.n_pct + self.p2o5_pct + self.k2o_pct > 100:
            raise ValueError("N + P2O5 + K2O cannot exceed 100 % of the product")

    @property
    def n_kg_ha(self) -> float:
        return self.product_rate_kg_ha * self.n_pct / 100

    @property
    def p2o5_kg_ha(self) -> float:
        return self.product_rate_kg_ha * self.p2o5_pct / 100

    @property
    def k2o_kg_ha(self) -> float:
        return self.product_rate_kg_ha * self.k2o_pct / 100


def product_rate(nutrient_kg_ha: float, content_pct: float) -> float:
    """kg of product per ha that supplies `nutrient_kg_ha` at `content_pct` %."""
    if content_pct <= 0 or content_pct > 100:
        raise ValueError("content_pct must be in (0, 100]")
    if nutrient_kg_ha < 0:
        raise ValueError("nutrient_kg_ha must be >= 0")
    return nutrient_kg_ha * 100 / content_pct


def totals(apps: list[PlannedApplication]) -> tuple[float, float, float]:
    """(N, P2O5, K2O) kg/ha supplied by the applications."""
    return (sum(a.n_kg_ha for a in apps), sum(a.p2o5_kg_ha for a in apps),
            sum(a.k2o_kg_ha for a in apps))


def n_split_issues(n_min: float, n_max: float, apps: list[PlannedApplication],
                   tol: float = 1e-6) -> list[str]:
    """Agronomic checks of the mineral N split; legal limits live in the rules layer.

    N_min/N_max are the requirement after credits (corrections.apply_credits), which already
    subtract the available N of organic inputs, so organic applications are left out here.
    - pre-plant N must not exceed N_min (the farmer tops up later in good years)
    - the planned total must lie in [N_min, N_max]
    """
    issues: list[str] = []
    mineral = [a for a in apps if not a.organic]
    pre = sum(a.n_kg_ha for a in mineral if a.stage == PRE_PLANT)
    total = sum(a.n_kg_ha for a in mineral)
    if pre > n_min + tol:
        issues.append("pre_plant_above_n_min")
    if total < n_min - tol:
        issues.append("total_below_n_min")
    if total > n_max + tol:
        issues.append("total_above_n_max")
    return issues


def to_oxides(p_kg_ha: float, k_kg_ha: float) -> tuple[float, float]:
    """Elemental P and K to P2O5 and K2O."""
    return p_kg_ha * C.P_TO_P2O5, k_kg_ha * C.K_TO_K2O
