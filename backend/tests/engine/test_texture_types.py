import pytest

from app.engine.texture import olsen_equivalent, texture_class
from app.engine.types import CropParams, CropSeason, Management, SoilState

DURUM = CropParams(eppo="TRZDU", crop_type="cereal", dm_product_pct=87.5, n_product_pct=2.4,
                   n_min_product_pct=2.05, p_product_pct=0.42, k_product_pct=0.5,
                   n_residue_pct=0.65, p_residue_pct=0.06, k_residue_pct=1.2,
                   harvest_index_pct=40, residue_left_pct=10, n_fixing=False)
SOIL = SoilState(texture_class=3, clay_pct=18, ph=7.5, organic_matter_pct=2.0,
                 p_olsen_mg_kg=12, k_mg_kg=150)
MGMT = Management(strategy=2, tillage=True, irrigated=False)


@pytest.mark.parametrize("sand,clay,cls", [(92, 3, 1), (65, 10, 2), (42, 18, 3),
                                           (20, 15, 4), (32, 34, 5), (20, 60, 6)])
def test_texture_class_centres_map_to_their_class(sand, clay, cls):
    assert texture_class(sand, clay) == cls


def test_texture_class_rejects_impossible_texture():
    with pytest.raises(ValueError):
        texture_class(80, 30)


def test_olsen_equivalent_uses_published_table5():
    assert olsen_equivalent(20, "bray1") == pytest.approx(9.4)
    assert olsen_equivalent(10, "ammonium_lactate") == pytest.approx(2.5)  # paper, not 0.2
    assert olsen_equivalent(7, "olsen") == 7


def test_olsen_equivalent_unknown_method_fails():
    with pytest.raises(ValueError):
        olsen_equivalent(10, "magic")




def test_invalid_crop_type_rejected():
    with pytest.raises(ValueError):
        CropParams(**{**DURUM.__dict__, "crop_type": "weed"})


def test_soil_state_validates_class_and_ph():
    with pytest.raises(ValueError):
        SoilState(texture_class=7, clay_pct=18, ph=7, organic_matter_pct=2, p_olsen_mg_kg=10, k_mg_kg=100)
    with pytest.raises(ValueError):
        SoilState(texture_class=3, clay_pct=18, ph=15, organic_matter_pct=2, p_olsen_mg_kg=10, k_mg_kg=100)


def test_management_strategy_range():
    with pytest.raises(ValueError):
        Management(strategy=5, tillage=True, irrigated=False)


def test_season_rejects_zero_yield():
    with pytest.raises(ValueError):
        CropSeason(DURUM, 0, 10)
