import pytest

from app.inputs.irrigation import irrigation_credit
from app.inputs.provenance import (
    DECLARED,
    ENTERED,
    MEASURED,
    MissingInput,
    Notice,
    Override,
    Sourced,
    missing,
)

NO3 = Sourced(50.0, MEASURED, "broker:urn:ngsi-ld:WaterQualityObserved:w1", "2026-05-01")


def test_rainfed_has_no_irrigation_n():
    c = irrigation_credit(False, None, missing(), {})
    assert c.n_kg_ha.value == 0.0 and c.n_kg_ha.note == "rainfed" and not c.missing


def test_irrigated_without_water_volume_is_missing():
    c = irrigation_credit(True, None, NO3, {})
    assert c.missing == (MissingInput("irrigation.water_m3_ha", "plan", {}),)


def test_n_from_the_water_at_the_default_uptake():
    c = irrigation_credit(True, 3000.0, NO3, {})
    assert c.n_kg_ha.value == pytest.approx(50.0 * 3000.0 * 14 / 62 / 1000 * 0.7)
    assert c.uptake.provenance == "table:villalobos_2020"
    assert c.uptake.note == "irrigation_uptake_fertilicalc"
    assert c.water_m3_ha.provenance == DECLARED


def test_the_technician_changes_the_uptake():
    o = {"irrigation.uptake": Override("irrigation.uptake", 0.5, "drip, no drainage", "t1",
                                       "2026-10-13T10:00:00Z")}
    c = irrigation_credit(True, 3000.0, NO3, o)
    assert c.uptake.provenance == ENTERED
    assert c.n_kg_ha.value == pytest.approx(50.0 * 3000.0 * 14 / 62 / 1000 * 0.5)


def test_unknown_nitrate_is_not_discounted():
    c = irrigation_credit(True, 3000.0, missing(), {})
    assert c.n_kg_ha.value == 0.0 and not c.n_kg_ha.known
    assert Notice("irrigation_no3_unknown", {}) in c.notices and not c.missing
