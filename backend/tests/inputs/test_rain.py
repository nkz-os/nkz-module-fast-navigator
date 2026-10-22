from datetime import date, timedelta

import pytest

from app.inputs.provenance import Notice
from app.inputs.rain import rain_normal, rain_years


def year_days(year, mm=1.0, skip=0):
    d, out = date(year, 1, 1), []
    while d.year == year:
        out.append({"date": d.isoformat(), "precip_mm": mm, "source": "open_meteo"})
        d += timedelta(days=1)
    return out[skip:]


def test_the_ten_years_before_the_plan_year():
    assert rain_years(2027) == list(range(2016, 2026))


def test_complete_years():
    normal = rain_normal({y: year_days(y) for y in rain_years(2027)})
    assert len(normal.years) == 10 and not normal.notices
    assert normal.monthly_mm[0] == pytest.approx(31.0)
    assert normal.annual_mm == pytest.approx(sum(normal.monthly_mm))
    assert normal.sources == ("open_meteo",)


def test_an_incomplete_year_is_left_out_and_reported():
    days = {y: year_days(y) for y in rain_years(2027)}
    days[2020] = year_days(2020, skip=3)
    normal = rain_normal(days)
    assert 2020 not in normal.years
    assert Notice("rain_years_incomplete", {"years": [2020]}) in normal.notices
    assert Notice("rain_normal_short_series", {"years": 9}) in normal.notices


def test_a_repeated_day_counts_once():
    days = year_days(2021)
    normal = rain_normal({2021: days + days[:1]})
    assert normal.annual_mm == pytest.approx(365.0)


def test_no_data():
    normal = rain_normal({2021: []})
    assert normal.annual_mm is None and normal.monthly_mm == ()
