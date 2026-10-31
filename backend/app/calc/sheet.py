"""One crop sheet's requirement: the engine over assembled inputs, every term with its provenance."""
from __future__ import annotations

import json
from dataclasses import dataclass

from app.engine import ENGINE_VERSION
from app.engine import constants as C
from app.engine.corrections import apply_credits
from app.engine.nitrogen import n_requirement
from app.engine.phosphorus_potassium import k_requirement, p_requirement
from app.engine.types import CropSeason, Management, NCredits, SoilState
from app.inputs.crop import CropBuild
from app.inputs.crops import FALLOW, CropChoice
from app.inputs.irrigation import IrrigationCredit
from app.inputs.organic import ORGANIC_TABLE_VERSION, OrganicCredit
from app.inputs.parcel import ParcelInfo
from app.inputs.provenance import DECLARED, MissingInput, Notice, Sourced
from app.inputs.soil import SoilInputs
from app.inputs.yield_target import YieldTarget

CALC_VERSION = "1.1.0"
COMPLETE, INCOMPLETE = "complete", "incomplete"
_N_MIN_NOTICE = "n_min_fallback_typical"

# Values for soil fields a computation never reads: n_requirement reads only the organic
# matter (N-fixing crops); P and K with strategy 4 read clay, pH and class only for a
# threshold the result drops. tests/calc/test_sheet.py pins that outputs ignore them.
_NEUTRAL_SOIL = {"texture_class": 3, "clay_pct": 0.0, "ph": 7.0, "organic_matter_pct": 0.0,
                 "p_olsen_mg_kg": 0.0, "k_mg_kg": 0.0}


@dataclass(frozen=True)
class AssembledInputs:
    campaign: int
    management: Management
    previous_residues_burned: bool
    rotation_years: int
    choice: CropChoice
    crop: CropBuild
    previous_crop: CropBuild | None      # None for fallow or an unknown preceding crop
    yield_target: YieldTarget
    previous_yield: YieldTarget | None
    soil: SoilInputs
    organic: OrganicCredit
    irrigation: IrrigationCredit
    region: Sourced
    parcels: tuple[ParcelInfo, ...]
    notices: tuple[Notice, ...] = ()


@dataclass(frozen=True)
class SheetResult:
    status: str
    provisional: bool
    n: dict | None
    p2o5: dict | None
    k2o: dict | None
    inputs: dict[str, dict]
    notices: tuple[Notice, ...]
    missing: tuple[MissingInput, ...]
    versions: dict[str, str | None]

    def to_dict(self) -> dict:
        return {"status": self.status, "provisional": self.provisional, "n": self.n,
                "p2o5": self.p2o5, "k2o": self.k2o, "inputs": self.inputs,
                "notices": [n.to_dict() for n in self.notices],
                "missing": [m.to_dict() for m in self.missing], "versions": self.versions}


class _Absent(Exception):
    def __init__(self, fields: list[str]):
        super().__init__(", ".join(fields))
        self.fields = fields


def _soil_state(soil: SoilInputs, needed: tuple[str, ...]) -> SoilState:
    absent = [f for f in needed if not soil.values[f].known]
    if absent:
        raise _Absent(absent)
    v = {f: soil.values[f].value if soil.values[f].known else neutral
         for f, neutral in _NEUTRAL_SOIL.items()}
    return SoilState(texture_class=int(v["texture_class"]), clay_pct=float(v["clay_pct"]),
                     ph=float(v["ph"]), organic_matter_pct=float(v["organic_matter_pct"]),
                     p_olsen_mg_kg=float(v["p_olsen_mg_kg"]), k_mg_kg=float(v["k_mg_kg"]))


def _soil_missing(fields: list[str]) -> list[MissingInput]:
    return [MissingInput(f"soil.{f}", "soil", {}) for f in fields]


def _keep_crop_notice(notice: Notice, strategy: int) -> bool:
    return notice.code != _N_MIN_NOTICE or strategy in (1, 2)


def _notices(a: AssembledInputs) -> list[Notice]:
    strategy = a.management.strategy
    out = list(a.notices) + list(a.choice.notices)
    for build in (a.crop, a.previous_crop):
        if build is not None:
            out += [n for n in build.notices if _keep_crop_notice(n, strategy)]
    for target in (a.yield_target, a.previous_yield):
        if target is not None:
            out += list(target.notices)
    out += list(a.soil.notices) + list(a.organic.notices) + list(a.irrigation.notices)
    for parcel in a.parcels:
        out += list(parcel.notices)
    return out


def _previous(a: AssembledInputs, missing: list[MissingInput]) -> tuple[bool, CropSeason | None]:
    """(computable, season). Fallow is computable with no season; unknown is not computable."""
    if a.choice.previous.value == FALLOW:
        return True, None
    if not a.choice.previous.known:
        return False, None
    pb, py = a.previous_crop, a.previous_yield
    if pb is None or py is None:
        missing.append(MissingInput("previous_crop.coefficients", "bioorch",
                                    {"eppo": a.choice.previous.value}))
        return False, None
    missing.extend(pb.missing)
    missing.extend(m for m in py.missing if not m.field.endswith(".cv_pct"))
    if pb.params is None or not py.yield_kg_ha.known:
        return False, None
    # The preceding crop's CV is never read (n_requirement uses its yield only).
    try:
        return True, CropSeason(pb.params, float(py.yield_kg_ha.value), 0.0)
    except ValueError as exc:
        missing.append(MissingInput("previous_yield.kg_ha", "plan", {"error": str(exc)}))
        return False, None


def _nitrogen(a: AssembledInputs, current: CropSeason, previous: CropSeason | None,
              soil: SoilState) -> dict:
    irrigation = float(a.irrigation.n_kg_ha.value or 0.0)
    res = n_requirement(current, previous, soil, a.management, irrigation_n_kg_ha=irrigation)
    mineral = a.soil.values["mineral_n_kg_ha"]
    credits = NCredits(soil_mineral_n=float(mineral.value or 0.0),
                       organic_available_n=a.organic.n_available_kg_ha)
    adj = apply_credits(res, credits)
    t = res.terms
    return {
        "min_kg_ha": adj.n_min, "avg_kg_ha": adj.n_avg, "max_kg_ha": adj.n_max,
        "before_credits": {"min_kg_ha": res.n_min, "avg_kg_ha": res.n_avg,
                           "max_kg_ha": res.n_max},
        "levels_kg_ha": list(res.levels),
        "terms_kg_ha": {"crop_uptake": t.crop_uptake, "n_end": t.n_end,
                        "previous_residues": t.previous_residues,
                        "previous_roots": t.previous_roots, "n_other": t.n_other,
                        "fixation": t.fixation, "loss_divisor": t.loss_divisor},
        "credits_kg_ha": {"soil_mineral_n": credits.soil_mineral_n,
                          "organic_available_n": credits.organic_available_n,
                          "irrigation_n": irrigation},
    }


def _oxide(rate, organic_kg_ha: float, factor: float, strategy: int) -> dict:
    return {"rate_kg_ha": max(rate.rate - organic_kg_ha, 0.0) * factor,
            "before_organic_kg_ha": rate.rate * factor,
            "exported_kg_ha": rate.exported * factor,
            "buildup_per_year_kg_ha": rate.buildup_per_year * factor,
            "organic_credit_kg_ha": organic_kg_ha * factor,
            "threshold_mg_kg": None if strategy == 4 else rate.threshold_mg_kg,
            "soil_class": None if strategy == 4 else rate.soil_class,
            "high_from_mg_kg": None if strategy == 4 else rate.high_from_mg_kg,
            "basis": rate.basis,
            "strategy": strategy}


def _inputs(a: AssembledInputs) -> dict[str, dict]:
    out: dict[str, dict] = {"crop.eppo": a.choice.crop.to_dict(),
                            "previous_crop.eppo": a.choice.previous.to_dict()}
    for prefix, build in (("crop", a.crop), ("previous_crop", a.previous_crop)):
        if build is not None:
            out.update({f"{prefix}.{k}": v.to_dict() for k, v in build.inputs.items()})
    for prefix, target in (("yield", a.yield_target), ("previous_yield", a.previous_yield)):
        if target is not None:
            out[f"{prefix}.kg_ha"] = target.yield_kg_ha.to_dict()
            out[f"{prefix}.cv_pct"] = target.cv_pct.to_dict()
            out[f"{prefix}.basis"] = {"value": target.basis, "years": list(target.years)}
    m = a.management
    for name, value in (("strategy", m.strategy), ("tillage", m.tillage),
                        ("irrigated", m.irrigated), ("rotation_years", a.rotation_years),
                        ("previous_residues_burned", a.previous_residues_burned)):
        out[f"management.{name}"] = Sourced(value, DECLARED, "plan").to_dict()
    out.update({f"soil.{k}": v.to_dict() for k, v in a.soil.values.items()})
    out["soil.analysis_id"] = {"value": a.soil.analysis_id, "sampling_date": a.soil.sampling_date}
    for name in ("n_kg_ha", "uptake", "water_m3_ha", "no3_mg_l"):
        out[f"irrigation.{name}"] = getattr(a.irrigation, name).to_dict()
    for i, share in enumerate(a.organic.availability):
        out[f"organic.{i}.availability"] = share.to_dict()
    out["region.nuts"] = a.region.to_dict()
    for parcel in a.parcels:
        out[f"parcel.{parcel.urn}.area_ha"] = parcel.area_ha.to_dict()
        out[f"parcel.{parcel.urn}.identifier"] = parcel.identifier.to_dict()
    return out


def _dedupe(items: list[MissingInput]) -> tuple[MissingInput, ...]:
    seen, out = set(), []
    for m in items:
        key = (m.field, json.dumps(m.params, sort_keys=True, default=str))
        if key not in seen:
            seen.add(key)
            out.append(m)
    return tuple(out)


def calculate(a: AssembledInputs) -> SheetResult:
    strategy = a.management.strategy
    missing: list[MissingInput] = list(a.choice.missing) + list(a.crop.missing) \
        + list(a.yield_target.missing)
    for parcel in a.parcels:
        missing.extend(parcel.missing)
    missing.extend(a.organic.missing)
    missing.extend(a.irrigation.missing)
    missing.extend(a.soil.nmin_missing)

    current = None
    if a.crop.params is not None and a.yield_target.yield_kg_ha.known:
        cv = a.yield_target.cv_pct
        # A missing CV blocks N (below) but not P and K, which never read it.
        try:
            current = CropSeason(a.crop.params, float(a.yield_target.yield_kg_ha.value),
                                 float(cv.value) if cv.known else 0.0,
                                 a.previous_residues_burned)
        except ValueError as exc:
            missing.append(MissingInput("yield.kg_ha", "plan", {"error": str(exc)}))
    previous_ok, previous = _previous(a, missing)

    n = None
    if (current is not None and a.yield_target.cv_pct.known and previous_ok
            and not a.organic.missing and not a.irrigation.missing
            and not a.soil.nmin_missing):
        needed = ("organic_matter_pct",) if a.crop.params.n_fixing else ()
        try:
            n = _nitrogen(a, current, previous, _soil_state(a.soil, needed))
        except _Absent as exc:
            missing.extend(_soil_missing(exc.fields))

    p2o5 = k2o = None
    if current is not None:
        p_needed = () if strategy == 4 else ("texture_class", "clay_pct", "ph", "p_olsen_mg_kg")
        k_needed = () if strategy == 4 else ("texture_class", "k_mg_kg")
        try:
            soil = _soil_state(a.soil, p_needed)
            p2o5 = _oxide(p_requirement(current, soil, a.management, a.rotation_years),
                          a.organic.p_kg_ha, C.P_TO_P2O5, strategy)
        except _Absent as exc:
            missing.extend(_soil_missing(exc.fields))
        try:
            soil = _soil_state(a.soil, k_needed)
            k2o = _oxide(k_requirement(current, soil, a.management, a.rotation_years),
                         a.organic.k_kg_ha, C.K_TO_K2O, strategy)
        except _Absent as exc:
            missing.extend(_soil_missing(exc.fields))

    status = COMPLETE if None not in (n, p2o5, k2o) and not missing else INCOMPLETE
    return SheetResult(
        status=status, provisional=a.soil.provisional, n=n, p2o5=p2o5, k2o=k2o,
        inputs=_inputs(a), notices=tuple(_notices(a)), missing=_dedupe(missing),
        versions={"engine": ENGINE_VERSION, "calc": CALC_VERSION,
                  "coefficients": a.crop.dataset_version,
                  "previous_coefficients": (a.previous_crop.dataset_version
                                            if a.previous_crop is not None else None),
                  "organic_table": ORGANIC_TABLE_VERSION})
