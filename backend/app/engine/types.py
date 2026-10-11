"""Engine inputs and outputs. Immutable; every number in kg/ha unless the name says otherwise."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

CROP_TYPES = (
    "cereal", "industrial", "tuber_root", "forage_legume", "grain_legume",
    "tree", "vegetable", "forage",
)


def _finite(obj: object, *names: str) -> None:
    for name in names:
        value = getattr(obj, name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number")


@dataclass(frozen=True)
class CropParams:
    """Balance coefficients of one crop (BioOrch, possibly overridden by the technician)."""
    eppo: str
    crop_type: str
    dm_product_pct: float       # dry matter of the harvested product, % of fresh weight
    n_product_pct: float        # typical N, % of product DM
    n_min_product_pct: float    # minimum N, % of product DM (strategies 1-2)
    p_product_pct: float
    k_product_pct: float
    n_residue_pct: float        # % of residue DM
    p_residue_pct: float
    k_residue_pct: float
    harvest_index_pct: float
    residue_left_pct: float     # Fres: share of residues left in the field
    n_fixing: bool

    def __post_init__(self) -> None:
        _finite(self, "dm_product_pct", "n_product_pct", "n_min_product_pct", "p_product_pct",
                "k_product_pct", "n_residue_pct", "p_residue_pct", "k_residue_pct",
                "harvest_index_pct", "residue_left_pct")
        if self.crop_type not in CROP_TYPES:
            raise ValueError(f"unknown crop_type {self.crop_type!r}")
        if not 0 < self.harvest_index_pct <= 100:
            raise ValueError("harvest_index_pct must be in (0, 100]")
        if not 0 < self.dm_product_pct <= 100:
            raise ValueError("dm_product_pct must be in (0, 100]")
        if not 0 <= self.residue_left_pct <= 100:
            raise ValueError("residue_left_pct must be in [0, 100]")
        for name in ("n_product_pct", "n_min_product_pct", "p_product_pct", "k_product_pct",
                     "n_residue_pct", "p_residue_pct", "k_residue_pct"):
            if not 0 <= getattr(self, name) <= 10:
                raise ValueError(f"{name} must be in [0, 10] % of DM")


@dataclass(frozen=True)
class CropSeason:
    crop: CropParams
    yield_kg_ha: float          # target yield, fresh product as sold
    yield_cv_pct: float         # inter-annual coefficient of variation of the yield
    previous_residues_burned: bool = False   # residues of the preceding crop burned before this one

    def __post_init__(self) -> None:
        _finite(self, "yield_kg_ha", "yield_cv_pct")
        if self.yield_kg_ha <= 0:
            raise ValueError("yield_kg_ha must be > 0")
        if not 0 <= self.yield_cv_pct <= 100:
            raise ValueError("yield_cv_pct must be in [0, 100]")


@dataclass(frozen=True)
class SoilState:
    texture_class: int          # FertiliCalc class 1..6 (see texture.texture_class)
    clay_pct: float
    ph: float
    organic_matter_pct: float
    p_olsen_mg_kg: float        # already converted to Olsen (texture.olsen_equivalent)
    k_mg_kg: float

    def __post_init__(self) -> None:
        _finite(self, "clay_pct", "ph", "organic_matter_pct", "p_olsen_mg_kg", "k_mg_kg")
        if self.texture_class not in range(1, 7):
            raise ValueError("texture_class must be 1..6")
        if not 0 <= self.clay_pct <= 100:
            raise ValueError("clay_pct must be 0..100")
        if not 0 <= self.organic_matter_pct <= 100:
            raise ValueError("organic_matter_pct must be 0..100")
        if not 0 <= self.ph <= 14:
            raise ValueError("ph must be 0..14")
        if self.p_olsen_mg_kg < 0 or self.k_mg_kg < 0:
            raise ValueError("soil P and K must be >= 0")


@dataclass(frozen=True)
class Management:
    strategy: int               # 1..4 (FertiliCalc)
    tillage: bool
    irrigated: bool

    def __post_init__(self) -> None:
        if self.strategy not in (1, 2, 3, 4):
            raise ValueError("strategy must be 1..4")


@dataclass(frozen=True)
class NTerms:
    """Breakdown of the average-level N balance (all kg N/ha, signed as in Eq. 6)."""
    crop_uptake: float          # (1+fNR)(Ny+Nr)
    n_end: float
    previous_residues: float    # −(1−burn)·kim·Fres'·N'r
    previous_roots: float       # −fNR(N'y+N'r)
    n_other: float              # −Nother (deposition + irrigation water)
    fixation: float             # −Nfix
    loss_divisor: float         # (1−n)


@dataclass(frozen=True)
class NResult:
    levels: tuple[float, ...]   # 9 probability levels, before credits
    n_min: float
    n_avg: float
    n_max: float
    terms: NTerms


@dataclass(frozen=True)
class NutrientRate:
    """P or K rate, elemental kg/ha."""
    rate: float
    exported: float
    buildup_per_year: float
    threshold_mg_kg: float


@dataclass(frozen=True)
class NCredits:
    soil_mineral_n: float = 0.0     # already × efficiency
    organic_available_n: float = 0.0


@dataclass(frozen=True)
class NAdjusted:
    n_min: float
    n_avg: float
    n_max: float
    credits: NCredits = field(default_factory=NCredits)
