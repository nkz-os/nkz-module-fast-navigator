"""Soil inputs of a sheet: its representative laboratory analysis (art. 6.2), estimates otherwise."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

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


def build_soil(analyses: list[dict], estimated: list[dict], analysis_id: str | None,
               nmin_analysis_id: str | None, overrides: dict[str, Override]) -> SoilInputs:
    notices: list[Notice] = []
    absent: list[MissingInput] = []
    chosen = select_analysis(analyses, analysis_id)
    if analysis_id and chosen is None:
        notices.append(Notice("soil_analysis_not_found", {"analysis": analysis_id}))
    hz = (chosen or {}).get("horizons") or []
    chosen_id = (chosen or {}).get("id")
    lab_src = f"soil:lab-analysis:{chosen_id}" if chosen else None

    def lab(key: str) -> Sourced | None:
        value = topsoil_mean(hz, key)
        return Sourced(value, MEASURED, lab_src) if value is not None else None

    def est(key: str, low: float, high: float) -> Sourced | None:
        value = topsoil_mean(estimated, key)
        if value is None:
            return None
        if not low <= value <= high:
            notices.append(Notice("soil_estimate_out_of_range", {"field": key, "value": round(value, 3)}))
            return None
        return Sourced(value, ESTIMATED, "soil:horizons")

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
        "sand_pct": choose("sand_pct", lambda: lab("sand"), lambda: est("sand", 0, 100)),
        "clay_pct": choose("clay_pct", lambda: lab("clay"), lambda: est("clay", 0, 100)),
        "ph": choose("ph", lambda: lab("ph"), lambda: est("ph", 3, 10)),
        "organic_matter_pct": choose("organic_matter_pct", lambda: lab("organicMatter")),
        "p_olsen_mg_kg": choose("p_olsen_mg_kg", lambda: _lab_p(hz, lab_src, chosen_id, notices)),
        "k_mg_kg": choose("k_mg_kg", lambda: _lab_k(hz, lab_src, chosen_id, notices)),
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

    measured_bd = lab("bulkDensity")
    if "soil.bulk_density_g_cm3" in overrides:
        values["bulk_density_g_cm3"] = overrides["soil.bulk_density_g_cm3"].as_sourced()
    elif measured_bd is not None and 0.1 <= measured_bd.value <= 2.65:
        values["bulk_density_g_cm3"] = measured_bd
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
    return SoilInputs(chosen_id, (chosen or {}).get("samplingDate"), values, provisional,
                      tuple(notices), tuple(absent), tuple(nmin_missing))
