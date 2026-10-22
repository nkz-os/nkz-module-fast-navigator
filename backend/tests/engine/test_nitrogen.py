import pytest

from app.engine.nitrogen import n_requirement
from app.engine.types import CropParams, CropSeason, Management, SoilState
from tests.engine.oracle_cases import CASES


@pytest.mark.parametrize("name", sorted(CASES))
def test_n_matches_reference_script(name):
    soil, mgmt, crops, expected = CASES[name]
    for i, cur in enumerate(crops):
        res = n_requirement(cur, crops[i - 1], soil, mgmt)   # cyclic, like the script
        n_min, n_max, n_avg = expected[i][:3]
        assert (res.n_min, res.n_max, res.n_avg) == pytest.approx(
            (n_min, n_max, n_avg), rel=1e-9, abs=1e-9)


DURUM = CropParams(eppo="TRZDU", crop_type="cereal", dm_product_pct=87.5, n_product_pct=2.4,
                   n_min_product_pct=2.05, p_product_pct=0.42, k_product_pct=0.5,
                   n_residue_pct=0.65, p_residue_pct=0.06, k_residue_pct=1.2,
                   harvest_index_pct=40, residue_left_pct=10, n_fixing=False)
SOIL = SoilState(texture_class=3, clay_pct=18, ph=7.5, organic_matter_pct=2.0,
                 p_olsen_mg_kg=12, k_mg_kg=150)
MGMT = Management(strategy=2, tillage=True, irrigated=False)


def test_irrigation_n_lowers_requirement_one_to_one():
    cur = CropSeason(DURUM, 3000, 20)
    base = n_requirement(cur, cur, SOIL, MGMT)
    water = n_requirement(cur, cur, SOIL, MGMT, irrigation_n_kg_ha=15)
    assert base.n_avg - water.n_avg == pytest.approx(15)


def test_negative_irrigation_n_rejected():
    cur = CropSeason(DURUM, 3000, 20)
    with pytest.raises(ValueError):
        n_requirement(cur, cur, SOIL, MGMT, irrigation_n_kg_ha=-1)


def test_higher_yield_needs_more_n():
    prev = CropSeason(DURUM, 3000, 20)
    low = n_requirement(CropSeason(DURUM, 3000, 20), prev, SOIL, MGMT)
    high = n_requirement(CropSeason(DURUM, 5000, 20), prev, SOIL, MGMT)
    assert high.n_avg > low.n_avg


def test_levels_non_decreasing_and_min_avg_max_ordered():
    res = n_requirement(CropSeason(DURUM, 3000, 30), CropSeason(DURUM, 3000, 30), SOIL, MGMT)
    assert list(res.levels) == sorted(res.levels)
    assert len(res.levels) == 9
    assert res.n_min <= res.n_avg <= res.n_max


def test_breakdown_adds_up_to_average_rate():
    res = n_requirement(CropSeason(DURUM, 3000, 20), CropSeason(DURUM, 3000, 20), SOIL, MGMT)
    t = res.terms
    total = (t.n_end + t.crop_uptake + t.previous_residues + t.previous_roots + t.n_other
             + t.fixation) / t.loss_divisor
    assert total == pytest.approx(res.n_avg)


def test_rate_never_negative():
    tiny = CropSeason(DURUM, 100, 0)
    big_prev = CropSeason(DURUM, 9000, 0)
    res = n_requirement(tiny, big_prev, SOIL, MGMT)
    assert min(res.levels) >= 0.0


def test_tree_irrigation_n_is_credited():
    from tests.engine.oracle_cases import OLIVE, season
    olive = season(OLIVE, 5000, 25, 50, 100, 1.0, 0.12, 1.3)
    mgmt = Management(strategy=2, tillage=True, irrigated=True)
    base = n_requirement(olive, olive, SOIL, mgmt)
    watered = n_requirement(olive, olive, SOIL, mgmt, irrigation_n_kg_ha=10)
    assert base.n_avg - watered.n_avg == pytest.approx(10)
    assert watered.terms.n_other == pytest.approx(-10)


def test_fallow_or_no_previous_crop():
    cur = CropSeason(DURUM, 3000, 20)
    res = n_requirement(cur, None, SOIL, MGMT)
    t = res.terms
    assert t.previous_residues == 0 and t.previous_roots == 0
    assert res.n_avg == pytest.approx(t.n_end + t.crop_uptake + t.n_other)
