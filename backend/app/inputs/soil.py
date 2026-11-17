"""Soil inputs of a sheet: its representative laboratory analysis (art. 6.2), estimates otherwise."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise

from app.engine import constants as C
from app.engine.corrections import MineralNLayer, soil_mineral_n
from app.engine.texture import olsen_equivalent, texture_class

from .provenance import (
    ENTERED,
    ESTIMATED,
    MEASURED,
    MISSING,
    MissingInput,
    Notice,
    Override,
    Sourced,
    missing,
    table,
)

TOPSOIL_CM = 30.0
# Organic matter = organic carbon x 1.724 (van Bemmelen factor, the one the soil module uses).
VAN_BEMMELEN = 1.724
ESTIMATED_OM_SOURCE = "soil:estimated"
ZONE_MEAN_PREFIX = "zone-mean:"
# The FertiliCalc K thresholds are for ammonium-acetate K; other extractions are not comparable.
K_METHODS_SUPPORTED = frozenset({"ammonium_acetate"})
# Mineral N has its own selector (nmin_analysis_id), so an N-only analysis is not representative.
_FERTILITY_KEYS = ("organicMatter", "phosphorusAvailable", "potassiumExchangeable")


@dataclass(frozen=True)
class SoilInputs:
    analysis_id: str | None
    sampling_date: str | None
    values: dict[str, Sourced]
    provisional: bool
    notices: tuple[Notice, ...]
    missing: tuple[MissingInput, ...]
    # A chosen mineral-N analysis that cannot be credited: blocks N (silence would credit 0).
    nmin_missing: tuple[MissingInput, ...] = ()
    # The analysis the mineral N was taken from (None when none was chosen), and its date: the
    # zone doses credit a zone's own mineral N only if it was sampled on that same date.
    nmin_analysis_id: str | None = None
    nmin_sampling_date: str | None = None
    # With a zone campaign: the soil.* values no zone sample gave, taken from this analysis
    # (id, sampling date) instead. Empty when every value came from the zones or an override.
    parcel_fallback_fields: tuple[str, ...] = ()
    parcel_fallback_id: str | None = None
    parcel_fallback_date: str | None = None


def zone_mean_id(run_id: str) -> str:
    """Id of the synthetic analysis that is the parcel soil of a zone campaign."""
    return f"{ZONE_MEAN_PREFIX}{run_id}"


def _num(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _topsoil(horizons: list[dict]) -> list[dict]:
    out = []
    for h in horizons:
        top, bottom = _num(h.get("depthFrom")), _num(h.get("depthTo"))
        if top is not None and bottom is not None and bottom > top and top < TOPSOIL_CM:
            out.append(h)
    return out


def topsoil_mean(horizons: list[dict], key: str) -> float | None:
    """Thickness-weighted mean of `key` over 0-30 cm; None unless every overlapping horizon has it."""
    total = weight = 0.0
    for h in _topsoil(horizons):
        value = _num(h.get(key))
        if value is None:
            return None
        thickness = min(float(h["depthTo"]), TOPSOIL_CM) - float(h["depthFrom"])
        total += value * thickness
        weight += thickness
    return total / weight if weight > 0 else None


def _method(horizons: list[dict], value_key: str, method_key: str) -> tuple[str | None, bool]:
    """(the single method of `method_key` in the topsoil, whether several were found).

    A topsoil horizon that carries the value but not its method leaves the method unknown:
    the value must not be averaged in as if it had the other horizons' method.
    """
    topsoil = _topsoil(horizons)
    if any(h.get(value_key) is not None and h.get(method_key) is None for h in topsoil):
        return None, False
    methods = {h.get(method_key) for h in topsoil} - {None}
    if len(methods) == 1:
        return methods.pop(), False
    return None, len(methods) > 1


def select_analysis(analyses: list[dict], analysis_id: str | None) -> dict | None:
    """The chosen analysis, or the newest one with fertility data (the list is newest first)."""
    if analysis_id:
        return next((a for a in analyses if a.get("id") == analysis_id), None)
    for a in analyses:
        if any(k in h for h in a.get("horizons") or [] for k in _FERTILITY_KEYS):
            return a
    return None


def _lab_p(hz: list[dict], src: str | None, analysis_id: str | None,
           notices: list[Notice]) -> Sourced | None:
    raw = topsoil_mean(hz, "phosphorusAvailable")
    if raw is None:
        return None
    method, mixed = _method(hz, "phosphorusAvailable", "phosphorusMethod")
    if method is None:
        notices.append(Notice("soil_p_methods_mixed" if mixed else "soil_p_method_unknown",
                              {"analysis": analysis_id}))
        return None
    try:
        return Sourced(olsen_equivalent(raw, method), MEASURED, src, f"method:{method}")
    except ValueError:
        notices.append(Notice("soil_p_method_unsupported", {"method": method}))
        return None


def _lab_k(hz: list[dict], src: str | None, analysis_id: str | None,
           notices: list[Notice]) -> Sourced | None:
    raw = topsoil_mean(hz, "potassiumExchangeable")
    if raw is None:
        return None
    method, mixed = _method(hz, "potassiumExchangeable", "potassiumMethod")
    if method is None:
        notices.append(Notice("soil_k_methods_mixed" if mixed else "soil_k_method_unknown",
                              {"analysis": analysis_id}))
        return None
    if method not in K_METHODS_SUPPORTED:
        notices.append(Notice("soil_k_method_unsupported", {"method": method}))
        return None
    return Sourced(raw, MEASURED, src, f"method:{method}")


def _weakest(*values: Sourced) -> str:
    provenances = {v.provenance for v in values}
    if ESTIMATED in provenances:
        return ESTIMATED
    if ENTERED in provenances:
        return ENTERED
    return MEASURED


def _mineral_n(analysis: dict | None, class_bd: float | None
               ) -> tuple[Sourced, list[Notice]]:
    if analysis is None:
        return Sourced(0.0, MISSING, None, "no_nmin_analysis"), []
    analysis_id = analysis.get("id")
    src = f"soil:lab-analysis:{analysis_id}"
    notices: list[Notice] = []
    layers: list[MineralNLayer] = []
    for h in analysis.get("horizons") or []:
        top, bottom = _num(h.get("depthFrom")), _num(h.get("depthTo"))
        nitrate, ammonium = _num(h.get("nitrateN")), _num(h.get("ammoniumN"))
        if top is None or bottom is None or bottom <= top or (nitrate is None and ammonium is None):
            continue
        if nitrate is None or ammonium is None:
            notices.append(Notice("nmin_form_not_measured", {
                "analysis": analysis_id, "missing": "ammoniumN" if ammonium is None else "nitrateN"}))
        bd = _num(h.get("bulkDensity"))
        if bd is None or not 0.1 <= bd <= 2.65:
            if class_bd is None:
                return Sourced(0.0, MISSING, src, "nmin_bulk_density_unknown"), notices
            bd = class_bd
        layers.append(MineralNLayer(top, bottom, nitrate or 0.0, ammonium or 0.0, bd))
    if not layers:
        return Sourced(0.0, MISSING, src, "no_nmin_values"), notices
    return Sourced(soil_mineral_n(layers), MEASURED, src), notices


def analysis_p_olsen(analysis: dict) -> float | None:
    """Topsoil P of one analysis as Olsen-equivalent mg/kg; None if absent or unusable."""
    hz = analysis.get("horizons") or []
    try:
        got = _lab_p(hz, None, analysis.get("id"), [])
    except ValueError:
        return None
    return got.value if got is not None else None


def analysis_k(analysis: dict) -> float | None:
    """Topsoil ammonium-acetate K of one analysis (mg/kg); None if absent or unusable."""
    hz = analysis.get("horizons") or []
    try:
        got = _lab_k(hz, None, analysis.get("id"), [])
    except ValueError:
        return None
    return got.value if got is not None else None


def unusable_readings(analysis: dict) -> tuple[tuple[str, ...], list[Notice]]:
    """The soil.* fields (P, K) the analysis carries but that cannot be used (unknown, mixed or
    unsupported method...), with the notices that say why."""
    hz = analysis.get("horizons") or []
    fields: list[str] = []
    notices: list[Notice] = []
    for field, key, read in (("soil.p_olsen_mg_kg", "phosphorusAvailable", _lab_p),
                             ("soil.k_mg_kg", "potassiumExchangeable", _lab_k)):
        if topsoil_mean(hz, key) is None:
            continue
        try:
            got = read(hz, None, analysis.get("id"), notices)
        except ValueError:
            got = None
        if got is None:
            fields.append(field)
    return tuple(fields), notices


def analysis_mineral_n(analysis: dict, class_bd: float | None) -> float | None:
    """Mineral N of one analysis (kg N/ha); None when it cannot be credited (no values, no DA,
    bad data such as a negative concentration)."""
    try:
        got, _ = _mineral_n(analysis, class_bd)
    except ValueError:
        return None
    return got.value if got.known else None


def has_n_values(analysis: dict) -> bool:
    """Whether any horizon of the analysis carries nitrate or ammonium N."""
    return any(h.get("nitrateN") is not None or h.get("ammoniumN") is not None
               for h in analysis.get("horizons") or [])


def analysis_n_depth(analysis: dict) -> tuple[float, float] | None:
    """Depth range (cm) the analysis' mineral N covers: from the top of the first to the bottom
    of the last N horizon. None when it has no usable N horizon or they are not contiguous."""
    layers = []
    for h in analysis.get("horizons") or []:
        top, bottom = _num(h.get("depthFrom")), _num(h.get("depthTo"))
        if top is None or bottom is None or bottom <= top or not (
                h.get("nitrateN") is not None or h.get("ammoniumN") is not None):
            continue
        layers.append((top, bottom))
    if not layers:
        return None
    layers.sort()
    if any(nxt[0] != prev[1] for prev, nxt in pairwise(layers)):
        return None
    return layers[0][0], layers[-1][1]


def build_soil(analyses: list[dict], estimated: list[dict], analysis_id: str | None,
               nmin_analysis_id: str | None, overrides: dict[str, Override],
               zone_mean: dict | None = None,
               parcel_candidates: list[dict] | None = None) -> SoilInputs:
    """`zone_mean`: the synthetic analysis of a zone campaign; it is the parcel soil unless the
    technician chose an analysis (`analysis_id`). The fields no zone sample has come from the
    newest fertility analysis of `parcel_candidates` (the analyses that are not zone samples;
    default `analyses`), then from the estimates."""
    notices: list[Notice] = []
    absent: list[MissingInput] = []
    use_zone = zone_mean is not None and not analysis_id
    chosen = select_analysis(parcel_candidates if use_zone and parcel_candidates is not None
                             else analyses, analysis_id)
    zm_hz = ((zone_mean or {}).get("horizons") or []) if use_zone else []
    zm_src = f"soil:{zone_mean['id']}" if use_zone else None
    fallback_fields: list[str] = []
    if analysis_id and chosen is None:
        notices.append(Notice("soil_analysis_not_found", {"analysis": analysis_id}))
    hz = (chosen or {}).get("horizons") or []
    chosen_id = (chosen or {}).get("id")
    lab_src = f"soil:lab-analysis:{chosen_id}" if chosen else None

    def peek(key: str) -> tuple[Sourced | None, bool]:
        """(the lab value of `key`, whether it comes from the parcel analysis in a zone campaign)."""
        if use_zone:
            zone_value = topsoil_mean(zm_hz, key)
            if zone_value is not None:
                return Sourced(zone_value, MEASURED, zm_src), False
        value = topsoil_mean(hz, key)
        return (Sourced(value, MEASURED, lab_src) if value is not None else None), use_zone

    def took(name: str, got: Sourced | None, from_parcel: bool) -> Sourced | None:
        if got is not None and from_parcel:
            fallback_fields.append(name)
        return got

    def lab(key: str, name: str) -> Sourced | None:
        got, from_parcel = peek(key)
        return took(name, got, from_parcel)

    def est(key: str, low: float, high: float) -> Sourced | None:
        value = topsoil_mean(estimated, key)
        if value is None:
            return None
        if not low <= value <= high:
            notices.append(Notice("soil_estimate_out_of_range", {"field": key, "value": round(value, 3)}))
            return None
        return Sourced(value, ESTIMATED, "soil:horizons")

    def est_om() -> Sourced | None:
        """Provisional organic matter from the estimated organic carbon (%) of the topsoil."""
        oc = est("organicCarbon", 0, 60)
        if oc is None:
            return None
        om = oc.value * VAN_BEMMELEN
        notices.append(Notice("soil_om_estimated", {"oc_pct": round(oc.value, 2),
                                                    "om_pct": round(om, 2)}))
        return Sourced(om, ESTIMATED, ESTIMATED_OM_SOURCE, f"oc_x_{VAN_BEMMELEN}")

    def choose(field: str, *candidates: Callable[[], Sourced | None]) -> Sourced:
        name = f"soil.{field}"
        if name in overrides:
            return overrides[name].as_sourced()
        for candidate in candidates:
            got = candidate()
            if got is not None:
                return got
        absent.append(MissingInput(name, "soil", {}))
        return missing()

    values: dict[str, Sourced] = {
        "sand_pct": choose("sand_pct", lambda: lab("sand", "soil.sand_pct"), lambda: est("sand", 0, 100)),
        "clay_pct": choose("clay_pct", lambda: lab("clay", "soil.clay_pct"), lambda: est("clay", 0, 100)),
        "ph": choose("ph", lambda: lab("ph", "soil.ph"), lambda: est("ph", 3, 10)),
        "organic_matter_pct": choose("organic_matter_pct", lambda: lab("organicMatter", "soil.organic_matter_pct"), est_om),
        "p_olsen_mg_kg": choose(
            "p_olsen_mg_kg",
            lambda: _lab_p(zm_hz, zm_src, None, notices) if use_zone else None,
            lambda: took("soil.p_olsen_mg_kg", _lab_p(hz, lab_src, chosen_id, notices), use_zone)),
        "k_mg_kg": choose(
            "k_mg_kg",
            lambda: _lab_k(zm_hz, zm_src, None, notices) if use_zone else None,
            lambda: took("soil.k_mg_kg", _lab_k(hz, lab_src, chosen_id, notices), use_zone)),
    }

    if "soil.texture_class" in overrides:
        values["texture_class"] = overrides["soil.texture_class"].as_sourced()
    elif values["sand_pct"].known and values["clay_pct"].known:
        try:
            cls = texture_class(values["sand_pct"].value, values["clay_pct"].value)
            values["texture_class"] = Sourced(
                cls, _weakest(values["sand_pct"], values["clay_pct"]), "engine:texture_class")
        except ValueError:
            notices.append(Notice("soil_texture_invalid", {}))
            values["texture_class"] = missing()
            absent.append(MissingInput("soil.texture_class", "soil", {}))
    else:
        values["texture_class"] = missing()
        absent.append(MissingInput("soil.texture_class", "soil", {}))

    measured_bd, bd_from_parcel = peek("bulkDensity")
    if "soil.bulk_density_g_cm3" in overrides:
        values["bulk_density_g_cm3"] = overrides["soil.bulk_density_g_cm3"].as_sourced()
    elif measured_bd is not None and 0.1 <= measured_bd.value <= 2.65:
        values["bulk_density_g_cm3"] = took("soil.bulk_density_g_cm3", measured_bd, bd_from_parcel)
    elif values["texture_class"].known:
        values["bulk_density_g_cm3"] = Sourced(
            C.CLASS_BULK_DENSITY[int(values["texture_class"].value)], table("fertilicalc"),
            "engine:CLASS_BULK_DENSITY")
    else:
        values["bulk_density_g_cm3"] = missing()   # only the mineral N needs it

    nmin = None
    nmin_missing: list[MissingInput] = []
    if nmin_analysis_id:
        nmin = next((a for a in analyses if a.get("id") == nmin_analysis_id), None)
        if nmin is None:
            notices.append(Notice("nmin_analysis_not_found", {"analysis": nmin_analysis_id}))
            nmin_missing.append(MissingInput("soil.nmin_analysis", "soil",
                                             {"analysis": nmin_analysis_id}))
    bd = values["bulk_density_g_cm3"]
    values["mineral_n_kg_ha"], nmin_notices = _mineral_n(nmin, bd.value if bd.known else None)
    notices.extend(nmin_notices)
    blocked = {"no_nmin_values": ("soil.mineral_n", "nmin_no_values"),
               "nmin_bulk_density_unknown": ("soil.bulk_density_g_cm3",
                                             "nmin_bulk_density_unknown")}
    if nmin is not None and values["mineral_n_kg_ha"].note in blocked:
        field_name, code = blocked[values["mineral_n_kg_ha"].note]
        nmin_missing.append(MissingInput(field_name, "soil", {"analysis": nmin_analysis_id}))
        notices.append(Notice(code, {"analysis": nmin_analysis_id}))

    provisional = any(v.provenance == ESTIMATED for v in values.values())
    head = zone_mean if use_zone else chosen
    return SoilInputs((head or {}).get("id"), (head or {}).get("samplingDate"), values, provisional,
                      tuple(notices), tuple(absent), tuple(nmin_missing),
                      (nmin or {}).get("id"), (nmin or {}).get("samplingDate"),
                      tuple(dict.fromkeys(fallback_fields)),
                      chosen_id if fallback_fields else None,
                      (chosen or {}).get("samplingDate") if fallback_fields else None)
