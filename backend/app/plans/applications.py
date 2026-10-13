"""Planned applications of a crop sheet (art. 6.4) and the nutrients they bring."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from app.engine.split import PRE_PLANT, PlannedApplication, n_split_issues
from app.inputs.organic import OrganicApplication

ANNEX_V_SOURCE = "RD 1051/2022, annex V (consolidated text with RD 840/2024)"
ANNEX_V: dict[str, str] = {
    "A.a": "band spreading with trailing hoses or rigid tubes",
    "A.b": "band spreading with discs or shoes (shallow slot)",
    "A.c": "injection (open slot)",
    "A.d": "incorporation of slurry and liquids within 4 hours",
    "A.e": "slurry dilution followed by low-pressure irrigation",
    "A.f": "acidified slurry or slurry with urease inhibitors",
    "A.g": "urease or nitrification inhibitors (professional supervision)",
    "A.h": "composting or digestion to ammoniacal N below 0.6 % of fresh weight",
    "A.i": "incorporation of manure within 12 hours",
    "B.a": "dose and timing matched to crop uptake, split applications",
    "B.b": "incorporation into the soil (deep injection or mixing)",
    "B.c": "incorporation of urea at application or within 4 hours",
    "B.d": "polymer-coated urea (CMC 9)",
    "B.e": "nutrient polymers (CMC 8, Regulation (EU) 2019/1009)",
    "B.f": "irrigation right after application, or fertigation",
    "B.g": "rice: N applied on dry soil before flooding",
    "B.h": "urease inhibitors",
    "B.i": "variable-rate application within the parcel",
}
KINDS = ("mineral", "urea", "urea_solution", "ammonium_carbonate", "organo_mineral", "organic")
N_FORMS = ("ureic", "ammoniacal", "nitric", "organic", "mixed")
METHODS = ("broadcast", "localized", "band", "injection", "incorporated", "fertigation", "foliar",
           "other")
SPLIT_RULE_PREFIX = "FAST-split-"

AnnexVCode = Literal["A.a", "A.b", "A.c", "A.d", "A.e", "A.f", "A.g", "A.h", "A.i",
                     "B.a", "B.b", "B.c", "B.d", "B.e", "B.f", "B.g", "B.h", "B.i"]


def _text(max_length: int):
    return Annotated[str, StringConstraints(strip_whitespace=True, min_length=1,
                                            max_length=max_length)]


class ApplicationIn(BaseModel):
    stage: _text(64)       # "pre_plant" or a crop stage label
    planned_date: dt.date | None = None
    kind: Literal["mineral", "urea", "urea_solution", "ammonium_carbonate", "organo_mineral",
                  "organic"]
    product_name: _text(200)
    registry_ref: str | None = Field(default=None, max_length=100)
    organic_index: int | None = Field(default=None, ge=0)
    n_pct: float | None = Field(default=None, ge=0, le=100)
    p2o5_pct: float | None = Field(default=None, ge=0, le=100)
    k2o_pct: float | None = Field(default=None, ge=0, le=100)
    n_form: Literal["ureic", "ammoniacal", "nitric", "organic", "mixed"] | None = None
    product_rate_kg_ha: float | None = Field(default=None, gt=0, le=100_000)
    method: Literal["broadcast", "localized", "band", "injection", "incorporated", "fertigation",
                    "foliar", "other"]
    method_detail: str | None = Field(default=None, max_length=200)
    machine: _text(200)    # description or ManufacturingMachine URN
    annex_v: list[AnnexVCode] = Field(default_factory=list, max_length=18)
    other_measure: str | None = Field(default=None, max_length=500)

    @field_validator("registry_ref", "method_detail", "other_measure")
    @classmethod
    def _strip_optional(cls, v: str | None) -> str | None:
        return (v.strip() or None) if v is not None else None

    @model_validator(mode="after")
    def _consistent(self) -> ApplicationIn:
        if len(set(self.annex_v)) != len(self.annex_v):
            raise ValueError("annex V measures must not repeat")
        own = (self.n_pct, self.p2o5_pct, self.k2o_pct, self.product_rate_kg_ha, self.n_form)
        if self.kind == "organic":
            if self.organic_index is None:
                raise ValueError("an organic application points at the sheet's organic input")
            if any(v is not None for v in own):
                raise ValueError("an organic application takes its rate and composition from "
                                 "the sheet's organic input (art. 5.1.c)")
            return self
        if self.organic_index is not None:
            raise ValueError("only organic applications point at an organic input")
        if self.product_rate_kg_ha is None:
            raise ValueError("product_rate_kg_ha is required")
        n, p, k = (self.n_pct or 0.0), (self.p2o5_pct or 0.0), (self.k2o_pct or 0.0)
        if n + p + k > 100:
            raise ValueError("N + P2O5 + K2O cannot exceed 100 % of the product")
        if n > 0 and self.n_form is None:
            raise ValueError("n_form is required when the product contains N")
        return self


@dataclass(frozen=True)
class ApplicationNutrients:
    n_kg_ha: float
    p2o5_kg_ha: float
    k2o_kg_ha: float
    organic: bool


def nutrients(app: ApplicationIn, organic_inputs: list[OrganicApplication]) -> ApplicationNutrients:
    if app.kind == "organic":
        source = organic_inputs[app.organic_index]
        return ApplicationNutrients(source.n_kg_ha, source.p2o5_kg_ha, source.k2o_kg_ha, True)
    rate = app.product_rate_kg_ha
    return ApplicationNutrients(rate * (app.n_pct or 0.0) / 100, rate * (app.p2o5_pct or 0.0) / 100,
                                rate * (app.k2o_pct or 0.0) / 100, False)


def summarize(apps: list[ApplicationIn], organic_inputs: list[OrganicApplication]) -> dict:
    each = [nutrients(a, organic_inputs) for a in apps]
    return {
        "applications": [{"n_kg_ha": n.n_kg_ha, "p2o5_kg_ha": n.p2o5_kg_ha,
                          "k2o_kg_ha": n.k2o_kg_ha, "organic": n.organic} for n in each],
        "mineral_n_kg_ha": sum(n.n_kg_ha for n in each if not n.organic),
        "organic_n_total_kg_ha": sum(n.n_kg_ha for n in each if n.organic),
        "p2o5_kg_ha": sum(n.p2o5_kg_ha for n in each),
        "k2o_kg_ha": sum(n.k2o_kg_ha for n in each),
    }


def split_findings(apps: list[ApplicationIn], organic_inputs: list[OrganicApplication],
                   n_min: float, n_max: float) -> list[dict]:
    """Agronomic split checks of the mineral N (paper l. 240-248); legal limits are rules (05c)."""
    planned = []
    for app in apps:
        if app.kind == "organic":
            continue   # organic N is credited in the requirement (05a), not split here
        planned.append(PlannedApplication(app.stage, app.product_rate_kg_ha, app.n_pct or 0.0,
                                          app.p2o5_pct or 0.0, app.k2o_pct or 0.0))
    issues = n_split_issues(n_min, n_max, planned)
    if not issues:
        return []
    params = {"pre_plant_n_kg_ha": sum(p.n_kg_ha for p in planned if p.stage == PRE_PLANT),
              "n_min_kg_ha": n_min, "n_max_kg_ha": n_max,
              "planned_mineral_n_kg_ha": sum(p.n_kg_ha for p in planned)}
    return [{"rule_id": f"{SPLIT_RULE_PREFIX}{issue}", "severity": "warn", "params": params}
            for issue in issues]
