import pytest

from app.engine.split import (
    PRE_PLANT,
    PlannedApplication,
    n_split_issues,
    product_rate,
    to_oxides,
    totals,
)


def test_product_rate_urea():
    assert product_rate(46, 46) == pytest.approx(100)


def test_product_rate_rejects_zero_content():
    with pytest.raises(ValueError):
        product_rate(10, 0)


def test_split_flags_pre_plant_above_min_and_total_above_max():
    apps = [PlannedApplication(PRE_PLANT, 200, 27, 0, 0),       # 54 kg N pre-plant
            PlannedApplication("tillering", 100, 46, 0, 0)]     # +46 = 100 total
    assert n_split_issues(n_min=50, n_max=90, apps=apps) == [
        "pre_plant_above_n_min", "total_above_n_max"]


def test_split_ok_inside_range():
    apps = [PlannedApplication(PRE_PLANT, 100, 15, 15, 15),     # 15 N
            PlannedApplication("tillering", 100, 46, 0, 0)]     # +46 = 61
    assert n_split_issues(n_min=40, n_max=80, apps=apps) == []
    assert totals(apps) == pytest.approx((61, 15, 15))


def test_product_composition_over_100_rejected():
    with pytest.raises(ValueError):
        PlannedApplication(PRE_PLANT, 100, 46, 46, 46)


def test_to_oxides():
    assert to_oxides(10, 10) == pytest.approx((22.9, 12.047))


def test_organic_applications_do_not_count_against_mineral_n_range():
    # Available N of organic inputs is already subtracted from N_min/N_max (credits).
    apps = [PlannedApplication(PRE_PLANT, 20000, 0.6, 0.3, 0.6, organic=True),  # 120 kg N
            PlannedApplication("tillering", 100, 46, 0, 0)]                       # 46 kg N
    assert n_split_issues(n_min=40, n_max=80, apps=apps) == []
    assert totals(apps)[0] == pytest.approx(166)


def test_application_rejects_nan_rate():
    with pytest.raises(ValueError):
        PlannedApplication(PRE_PLANT, float("nan"), 46, 0, 0)
