"""N the crop takes from the irrigation water (spec §6, D11)."""
from __future__ import annotations

from dataclasses import dataclass

from app.engine import constants as C
from app.engine.corrections import irrigation_n

from .provenance import DECLARED, MISSING, MissingInput, Notice, Override, Sourced, missing, table

UPTAKE_SOURCE_ID = "villalobos_2020"


@dataclass(frozen=True)
class IrrigationCredit:
    n_kg_ha: Sourced
    uptake: Sourced
    water_m3_ha: Sourced
    no3_mg_l: Sourced
    notices: tuple[Notice, ...]
    missing: tuple[MissingInput, ...]


def irrigation_credit(irrigated: bool, water_m3_ha: float | None, no3: Sourced,
                      overrides: dict[str, Override]) -> IrrigationCredit:
    if "irrigation.uptake" in overrides:
        uptake = overrides["irrigation.uptake"].as_sourced()
    else:
        uptake = Sourced(C.IRRIGATION_N_UPTAKE, table(UPTAKE_SOURCE_ID),
                         "engine:IRRIGATION_N_UPTAKE", "irrigation_uptake_fertilicalc")
    if not irrigated:
        rainfed = Sourced(0.0, DECLARED, "plan", "rainfed")
        return IrrigationCredit(rainfed, uptake, rainfed, no3, (), ())
    if water_m3_ha is None:
        return IrrigationCredit(missing("plan"), uptake, missing("plan"), no3, (),
                                (MissingInput("irrigation.water_m3_ha", "plan", {}),))
    water = Sourced(float(water_m3_ha), DECLARED, "plan")
    if not no3.known:
        return IrrigationCredit(Sourced(0.0, MISSING, None, "irrigation_no3_unknown"), uptake,
                                water, no3, (Notice("irrigation_no3_unknown", {}),), ())
    n = irrigation_n(float(no3.value), float(water_m3_ha), float(uptake.value))
    return IrrigationCredit(Sourced(n, no3.provenance, "engine:irrigation_n"), uptake, water, no3,
                            (), ())
