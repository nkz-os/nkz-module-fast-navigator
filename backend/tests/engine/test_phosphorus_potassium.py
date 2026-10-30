import pytest

from app.engine.phosphorus_potassium import k_requirement, p_requirement, p_threshold
from app.engine.types import CropParams, CropSeason, Management, SoilState
from tests.engine.oracle_cases import CASES


@pytest.mark.parametrize("name", sorted(CASES))
def test_p_and_k_match_reference_script(name):
    soil, mgmt, crops, expected = CASES[name]
    for i, cur in enumerate(crops):
        p = p_requirement(cur, soil, mgmt, rotation_years=len(crops))
        k = k_requirement(cur, soil, mgmt, rotation_years=len(crops))
        assert (p.rate, k.rate) == pytest.approx(expected[i][3:], rel=1e-9, abs=1e-9)


RICE = CropParams(eppo="ORYSA", crop_type="cereal", dm_product_pct=86, n_product_pct=1.2,
                  n_min_product_pct=1.0, p_product_pct=0.3, k_product_pct=0.3,
                  n_residue_pct=0.7, p_residue_pct=0.1, k_residue_pct=1.5,
                  harvest_index_pct=45, residue_left_pct=50, n_fixing=False)
SOIL = SoilState(texture_class=3, clay_pct=18, ph=7.5, organic_matter_pct=2.0,
                 p_olsen_mg_kg=12, k_mg_kg=150)


def test_rice_threshold_by_species_not_by_name_column():
    # The script compares the Spanish name column with "Oryza sativa", so it never fires.
    assert p_threshold(CropSeason(RICE, 6000, 10), SOIL, strategy=2) == 4.0


def test_measured_clay_drives_p_threshold():
    s = CropSeason(RICE.__class__(**{**RICE.__dict__, "eppo": "TRZAX"}), 6000, 10)
    clay_10 = SoilState(3, 10, 7.5, 2.0, 12, 150)
    clay_40 = SoilState(3, 40, 7.5, 2.0, 12, 150)
    assert p_threshold(s, clay_10, 2) - p_threshold(s, clay_40, 2) == pytest.approx(0.16 * 30)


def test_rotation_years_must_be_positive():
    with pytest.raises(ValueError):
        p_requirement(CropSeason(RICE, 6000, 10), SOIL, Management(2, True, False), 0)
    with pytest.raises(ValueError):
        k_requirement(CropSeason(RICE, 6000, 10), SOIL, Management(2, True, False), 0)


def test_buildup_capped_per_year():
    # Wheat on a P- and K-free class-3 soil: build-up 75 kg P and 965 kg K, capped at 30/60.
    wheat = CropSeason(RICE.__class__(**{**RICE.__dict__, "eppo": "TRZAX"}), 6000, 10)
    poor = SoilState(3, 18, 7.5, 2.0, 0.0, 0.0)
    p = p_requirement(wheat, poor, Management(1, True, False), 1)
    k = k_requirement(wheat, poor, Management(1, True, False), 1)
    assert p.rate == pytest.approx(30.0) and k.rate == pytest.approx(60.0)


WHEAT = RICE.__class__(**{**RICE.__dict__, "eppo": "TRZAX"})


@pytest.mark.parametrize("p_olsen,cls,basis", [(5, "low", "buildup_and_export"),
                                               (30, "medium", "export"),
                                               (80, "high", "half_export")])
def test_p_soil_class_is_the_branch_taken(p_olsen, cls, basis):
    soil = SoilState(3, 18, 7.5, 2.0, p_olsen, 150)
    r = p_requirement(CropSeason(WHEAT, 6000, 10), soil, Management(2, True, False), 4)
    assert (r.soil_class, r.basis) == (cls, basis)
    assert r.high_from_mg_kg == pytest.approx(2 * r.threshold_mg_kg)


def test_k_on_clay_is_high_from_one_and_a_half_thresholds_and_gets_nothing():
    clay = SoilState(6, 45, 7.5, 2.0, 12, 0)
    probe = k_requirement(CropSeason(WHEAT, 6000, 10), clay, Management(2, True, False), 4)
    soil = SoilState(6, 45, 7.5, 2.0, 12, 1.6 * probe.threshold_mg_kg)
    r = k_requirement(CropSeason(WHEAT, 6000, 10), soil, Management(2, True, False), 4)
    assert r.high_from_mg_kg == pytest.approx(1.5 * r.threshold_mg_kg)
    assert (r.soil_class, r.basis, r.rate) == ("high", "none", 0.0)


def test_strategy_4_has_no_soil_class():
    for fn in (p_requirement, k_requirement):
        r = fn(CropSeason(WHEAT, 6000, 10), SOIL, Management(4, True, False), 4)
        assert (r.soil_class, r.high_from_mg_kg, r.basis) == (None, None, "export")


def test_strategy_1_reports_the_soil_and_builds_up():
    r = p_requirement(CropSeason(WHEAT, 6000, 10), SOIL, Management(1, True, False), 4)
    assert r.basis == "buildup" and r.soil_class in ("low", "medium", "high")
