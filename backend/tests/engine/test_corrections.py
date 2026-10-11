import pytest

from app.engine.corrections import (
    MineralNLayer,
    OrganicInput,
    apply_credits,
    irrigation_n,
    organic_available_n,
    soil_mineral_n,
)
from app.engine.types import NCredits, NResult, NTerms


def test_soil_mineral_n_kg_ha_with_efficiency():
    # 10 mg/kg × 1.4 g/cm3 × 30 cm × 0.1 = 42 kg/ha; × 0.9 = 37.8
    layers = [MineralNLayer(0, 30, nitrate_n_mg_kg=8, ammonium_n_mg_kg=2, bulk_density_g_cm3=1.4)]
    assert soil_mineral_n(layers) == pytest.approx(37.8)


def test_soil_mineral_n_rejects_inverted_depths():
    with pytest.raises(ValueError):
        soil_mineral_n([MineralNLayer(30, 0, 1, 1, 1.4)])


def test_irrigation_n_from_nitrate():
    # 50 mg NO3/L × 3000 m3/ha × 14/62 / 1000 = 33.87 kg N/ha, × 0.7 absorbed (paper l. 268-270)
    assert irrigation_n(50, 3000) == pytest.approx(23.709677419354836)


def test_organic_available_n():
    assert organic_available_n([OrganicInput(120, 0.5), OrganicInput(40, 0.25)]) == 70


def test_apply_credits_never_negative():
    terms = NTerms(0, 0, 0, 0, 0, 0, 1)
    adj = apply_credits(NResult((0,) * 9, 40, 60, 80, terms),
                        NCredits(soil_mineral_n=50, organic_available_n=0))
    assert (adj.n_min, adj.n_avg, adj.n_max) == (0.0, 10.0, 30.0)




def test_corrections_reject_non_finite():
    with pytest.raises(ValueError):
        irrigation_n(float("nan"), 3000)
    with pytest.raises(ValueError):
        organic_available_n([OrganicInput(float("inf"), 0.5)])
    with pytest.raises(ValueError):
        soil_mineral_n([MineralNLayer(0, 30, float("nan"), 1, 1.4)])
