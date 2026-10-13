import pytest

from app.inputs.overrides import check_override, farmer_may_override


@pytest.mark.parametrize("param,value", [
    ("crop.harvest_index_pct", 45.0), ("previous_crop.n_product_pct", 2.1),
    ("crop.crop_type", "cereal"), ("crop.n_fixing", True), ("yield.kg_ha", 6000.0),
    ("previous_yield.cv_pct", 15.0), ("soil.ph", 7.9), ("soil.texture_class", 4),
    ("soil.bulk_density_g_cm3", 1.4), ("irrigation.uptake", 0.5), ("organic.2.availability", 0.6),
])
def test_valid_overrides(param, value):
    check_override(param, value)


@pytest.mark.parametrize("param,value", [
    ("crop.harvest_index_pct", 140.0), ("crop.n_product_pct", 12.0), ("crop.crop_type", "weed"),
    ("crop.n_fixing", 1.0), ("yield.kg_ha", 0.0), ("soil.ph", 15.0), ("soil.texture_class", 3.5),
    ("irrigation.uptake", 1.2), ("organic.0.availability", -0.1), ("crop.unknown", 1.0),
    ("nuts", 1.0), ("soil.ph", True), ("soil.ph", float("inf")),
])
def test_invalid_overrides(param, value):
    with pytest.raises(ValueError):
        check_override(param, value)


def test_the_farmer_only_sets_organic_availability():
    assert farmer_may_override("organic.0.availability")
    assert not farmer_may_override("irrigation.uptake")
    assert not farmer_may_override("crop.n_min_product_pct")
