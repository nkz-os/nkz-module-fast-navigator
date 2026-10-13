"""Engine crop parameters from the BioOrch balance coefficients (spec §4, §5.2)."""
from __future__ import annotations

from dataclasses import dataclass

from app.engine.types import CROP_TYPES, CropParams

from .provenance import MissingInput, Notice, Override, Sourced, missing, table

# engine field -> key in the `values` object of GET /crop-balance-coefficients
COEFFICIENT_FIELDS = {
    "dm_product_pct": "dm_product_pct",
    "n_product_pct": "n_product_pct",
    "p_product_pct": "p_product_pct",
    "k_product_pct": "k_product_pct",
    "n_residue_pct": "n_residue_pct",
    "p_residue_pct": "p_residue_pct",
    "k_residue_pct": "k_residue_pct",
    "harvest_index_pct": "balance_harvest_index_pct",
    "residue_left_pct": "residue_left_pct",
}
N_MIN_FIELD = "n_min_product_pct"


@dataclass(frozen=True)
class CropBuild:
    eppo: str | None
    params: CropParams | None
    inputs: dict[str, Sourced]
    notices: tuple[Notice, ...]
    missing: tuple[MissingInput, ...]
    dataset_version: str | None
    attributions: tuple[dict, ...]


def _number(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def build_crop(eppo: str | None, coefficients: dict | None, overrides: dict[str, Override],
               prefix: str = "crop") -> CropBuild:
    """CropParams for `eppo`, every field with its provenance.

    A field the source lacks and nobody entered is missing: without coefficients there is no
    calculation (spec §4). The N minimum has no open source (spec §5.2); when neither BioOrch
    nor the technician gives it, the typical N stands in and a notice says so (owner 2026-10-13).
    """
    if eppo is None:
        return CropBuild(None, None, {}, (), (MissingInput(f"{prefix}.eppo", "plan", {}),),
                         None, ())
    coefficients = coefficients or {}
    values = coefficients.get("values") or {}
    version = coefficients.get("dataset_version")
    src = "bioorch:crop-balance-coefficients" + (f"@{version}" if version else "")
    inputs: dict[str, Sourced] = {}
    notices: list[Notice] = []
    absent: list[MissingInput] = []

    def from_table(key: str) -> Sourced | None:
        item = values.get(key)
        if isinstance(item, dict) and _number(item.get("value")):
            return Sourced(float(item["value"]), table(str(item.get("source_id") or "unknown")),
                           src, item.get("ref"))
        return None

    def pick(name: str, key: str) -> Sourced:
        if name in overrides:
            return overrides[name].as_sourced()
        got = from_table(key)
        if got is None:
            absent.append(MissingInput(name, "bioorch", {"eppo": eppo}))
            return missing(src)
        return got

    for field, key in COEFFICIENT_FIELDS.items():
        inputs[field] = pick(f"{prefix}.{field}", key)

    n_min_name = f"{prefix}.{N_MIN_FIELD}"
    listed = from_table(N_MIN_FIELD)
    if n_min_name in overrides:
        inputs[N_MIN_FIELD] = overrides[n_min_name].as_sourced()
    elif listed is not None:
        inputs[N_MIN_FIELD] = listed
    elif inputs["n_product_pct"].known:
        typical = inputs["n_product_pct"]
        inputs[N_MIN_FIELD] = Sourced(typical.value, typical.provenance, typical.source,
                                      "n_min_fallback_typical")
        notices.append(Notice("n_min_fallback_typical", {"eppo": eppo}))
    else:
        inputs[N_MIN_FIELD] = missing(src)  # the typical N is already reported missing

    type_name = f"{prefix}.crop_type"
    if type_name in overrides:
        inputs["crop_type"] = overrides[type_name].as_sourced()
    elif coefficients.get("crop_type") in CROP_TYPES:
        inputs["crop_type"] = Sourced(coefficients["crop_type"], table("bioorch"), src)
    else:
        inputs["crop_type"] = missing(src)
        absent.append(MissingInput(type_name, "bioorch", {"eppo": eppo}))

    fix_name = f"{prefix}.n_fixing"
    if fix_name in overrides:
        inputs["n_fixing"] = overrides[fix_name].as_sourced()
    elif isinstance(coefficients.get("n_fixing"), bool):
        inputs["n_fixing"] = Sourced(coefficients["n_fixing"], table("bioorch"), src)
    else:
        inputs["n_fixing"] = missing(src)
        absent.append(MissingInput(fix_name, "bioorch", {"eppo": eppo}))

    params = None
    if not absent:
        try:
            params = CropParams(
                eppo=eppo, crop_type=inputs["crop_type"].value,
                n_fixing=bool(inputs["n_fixing"].value),
                **{f: float(inputs[f].value) for f in (*COEFFICIENT_FIELDS, N_MIN_FIELD)})
        except ValueError as exc:
            absent.append(MissingInput(f"{prefix}.coefficients", "bioorch",
                                       {"eppo": eppo, "error": str(exc)}))
    return CropBuild(eppo, params, inputs, tuple(notices), tuple(absent), version,
                     tuple(coefficients.get("attributions") or ()))
