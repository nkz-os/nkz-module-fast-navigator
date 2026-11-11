import pytest

from app.zones.doses import ZoneInput, distribute

TOL = 1e-9


def zones(*pairs):
    """(area_ha, mean_value) pairs -> zone inputs z0, z1, ..."""
    return [ZoneInput(f"z{i}", a, v) for i, (a, v) in enumerate(pairs)]


def by_key(result):
    return {z.key: z for z in result.zones}


def weighted_mean_factor(result, inputs):
    area = {z.key: z.area_ha for z in inputs}
    total = sum(area.values())
    return sum(area[z.key] * (z.factor if z.factor is not None else 1.0)
               for z in result.zones) / total


def test_equal_zones_all_one():
    r = distribute(zones((2, 0.5), (2, 0.5), (2, 0.5)), "potential", 20, 60.0)
    assert [z.factor for z in r.zones] == pytest.approx([1.0] * 3)
    assert [z.n_kg_ha for z in r.zones] == pytest.approx([60.0] * 3)
    assert not any(z.capped for z in r.zones) and not r.saturated


def test_potential_two_zones_equal_area():
    r = distribute(zones((1, 0.4), (1, 0.6)), "potential", 30, 100.0)
    a, b = r.zones
    assert a.relative_vigor == pytest.approx(0.8) and b.relative_vigor == pytest.approx(1.2)
    assert a.factor == pytest.approx(0.8) and b.factor == pytest.approx(1.2)
    assert a.n_kg_ha == pytest.approx(80.0) and b.n_kg_ha == pytest.approx(120.0)


def test_compensate_is_the_mirror():
    r = distribute(zones((1, 0.4), (1, 0.6)), "compensate", 30, 100.0)
    a, b = r.zones
    assert a.relative_vigor == pytest.approx(0.8) and b.relative_vigor == pytest.approx(1.2)
    assert a.factor == pytest.approx(1.2) and b.factor == pytest.approx(0.8)


def test_bound_reached_but_not_exceeded_is_not_capped():
    r = distribute(zones((1, 0.4), (1, 0.6)), "potential", 20, 100.0)
    assert not any(z.capped for z in r.zones)
    assert [z.factor for z in r.zones] == pytest.approx([0.8, 1.2])


def test_unequal_areas_keep_the_area_weighted_mean():
    inputs = zones((1, 0.4), (3, 0.6))
    r = distribute(inputs, "potential", 30, 80.0)
    # weighted mean value = (0.4 + 1.8) / 4 = 0.55
    assert r.zones[0].relative_vigor == pytest.approx(0.4 / 0.55)
    assert r.zones[1].relative_vigor == pytest.approx(0.6 / 0.55)
    assert weighted_mean_factor(r, inputs) == pytest.approx(1.0, abs=TOL)
    mean_dose = sum(i.area_ha * z.n_kg_ha for i, z in zip(inputs, r.zones)) / 4
    assert mean_dose == pytest.approx(80.0, abs=1e-7)


def test_cap_with_an_outlier_is_rescaled_to_mean_one():
    # relative vigors 1.5, 0.9, 0.8, 0.8 (mean values 0.75, 0.45, 0.4, 0.4; mean 0.5)
    inputs = zones((1, 0.75), (1, 0.45), (1, 0.4), (1, 0.4))
    r = distribute(inputs, "potential", 20, 100.0)
    z = r.zones
    assert [x.relative_vigor for x in z] == pytest.approx([1.5, 0.9, 0.8, 0.8])
    # clamp -> 1.2, 0.9, 0.8, 0.8 ; free zones share the rest with s = (4 - 1.2) / 2.5 = 1.12
    assert [x.factor for x in z] == pytest.approx([1.2, 1.008, 0.896, 0.896])
    assert [x.capped for x in z] == [True, False, False, False]
    assert weighted_mean_factor(r, inputs) == pytest.approx(1.0, abs=TOL)
    assert not r.saturated


def test_rescaling_can_push_a_free_zone_onto_a_bound():
    # relative vigors 2.5, 1.1, 0.8, 0.5, 0.1 (mean 0.5); cap 20 % -> bounds 0.8..1.2.
    # Pass 1 pins zones 0, 3, 4; the free zones (1.1, 0.8) share 2.2 with s = 2.2 / 1.9 and
    # zone 1 would reach 1.274: it is pinned too, and zone 2 takes what is left (1.0).
    inputs = zones((1, 1.25), (1, 0.55), (1, 0.4), (1, 0.25), (1, 0.05))
    r = distribute(inputs, "potential", 20, 100.0)
    assert [x.factor for x in r.zones] == pytest.approx([1.2, 1.2, 1.0, 0.8, 0.8])
    assert [x.capped for x in r.zones] == [True, True, False, True, True]
    assert weighted_mean_factor(r, inputs) == pytest.approx(1.0, abs=TOL)
    assert not r.saturated


def test_cap_zero_is_uniform():
    r = distribute(zones((1, 0.4), (1, 0.6), (2, 0.9)), "potential", 0, 50.0)
    assert [z.factor for z in r.zones] == pytest.approx([1.0] * 3)
    assert [z.n_kg_ha for z in r.zones] == pytest.approx([50.0] * 3)
    assert all(z.capped for z in r.zones)   # every raw factor differed from 1 and was cut


def test_uniform_strategy_ignores_values():
    r = distribute(zones((1, 0.4), (1, None)), "uniform", 20, 70.0)
    assert [z.n_kg_ha for z in r.zones] == [70.0, 70.0]
    assert [z.factor for z in r.zones] == [1.0, 1.0]
    assert [z.relative_vigor for z in r.zones] == [None, None]


def test_a_zone_without_value_gets_the_target_and_is_outside_the_share():
    inputs = zones((1, 0.4), (1, 0.6), (5, None))
    r = distribute(inputs, "potential", 30, 100.0)
    a, b, c = r.zones
    assert c.relative_vigor is None and c.factor is None and c.n_kg_ha == 100.0
    assert not c.capped
    # the share is among the zones that have a value only
    assert a.factor == pytest.approx(0.8) and b.factor == pytest.approx(1.2)
    assert weighted_mean_factor(r, inputs) == pytest.approx(1.0, abs=TOL)


def test_a_single_zone_is_neutral():
    r = distribute(zones((3, 0.5)), "compensate", 20, 60.0)
    assert r.zones[0].factor == pytest.approx(1.0) and r.zones[0].n_kg_ha == pytest.approx(60.0)


def test_zones_on_both_bounds_still_keep_the_mean():
    # relative vigors 1.9, 1.9, 0.2 (cap 5 %): clipping first would give 1.05, 1.05, 0.95, mean
    # 1.0167. The mean is always reachable with a cap > 0: the low zone stays on 0.95 and the two
    # high zones share the rest, 1.025 each.
    inputs = zones((1, 0.95), (1, 0.95), (1, 0.1))
    r = distribute(inputs, "potential", 5, 100.0)
    assert [z.factor for z in r.zones] == pytest.approx([1.025, 1.025, 0.95])
    assert [z.capped for z in r.zones] == [False, False, True]
    assert weighted_mean_factor(r, inputs) == pytest.approx(1.0, abs=TOL)
    assert not r.saturated


def test_a_zone_pinned_high_and_two_released_from_the_low_bound():
    # relative vigors 1.4, 0.8, 0.8 (cap 10 %): the outlier stays on 1.1 and the other two take
    # 0.95 each, not 0.9 (which would under-dose the parcel by 3.3 %).
    inputs = zones((1, 0.7), (1, 0.4), (1, 0.4))
    r = distribute(inputs, "potential", 10, 100.0)
    assert [z.factor for z in r.zones] == pytest.approx([1.1, 0.95, 0.95])
    assert [z.capped for z in r.zones] == [True, False, False]
    assert weighted_mean_factor(r, inputs) == pytest.approx(1.0, abs=TOL)
    assert not r.saturated


def test_compensate_keeps_the_mean_on_the_same_skewed_zones():
    inputs = zones((1, 0.7), (1, 0.4), (1, 0.4))
    r = distribute(inputs, "compensate", 10, 100.0)
    assert [z.factor for z in r.zones] == pytest.approx([0.9, 1.05, 1.05])
    assert [z.capped for z in r.zones] == [True, False, False]
    assert weighted_mean_factor(r, inputs) == pytest.approx(1.0, abs=TOL)


def test_compensate_with_a_relative_vigor_of_two_or_more():
    # area 1 at vigor 3 and area 9 at vigor 7/9 (weighted mean 1): the mirror of the first is
    # negative; it stays on the low bound and the rest is shared by the other zone.
    inputs = zones((1, 0.9), (9, 0.7 / 3))
    r = distribute(inputs, "compensate", 20, 100.0)
    a, b = r.zones
    assert a.relative_vigor == pytest.approx(3.0) and b.relative_vigor == pytest.approx(7 / 9)
    assert a.factor == pytest.approx(0.8) and a.capped
    assert b.factor == pytest.approx((10 - 0.8) / 9)
    assert all(z.n_kg_ha >= 0 for z in r.zones)
    assert weighted_mean_factor(r, inputs) == pytest.approx(1.0, abs=TOL)


def test_compensate_with_a_zone_without_value():
    inputs = zones((1, 0.4), (1, 0.6), (2, None))
    r = distribute(inputs, "compensate", 30, 100.0)
    a, b, c = r.zones
    assert a.factor == pytest.approx(1.2) and b.factor == pytest.approx(0.8)
    assert c.factor is None and c.n_kg_ha == 100.0
    assert weighted_mean_factor(r, inputs) == pytest.approx(1.0, abs=TOL)


@pytest.mark.parametrize("cap", [1, 5, 10, 20, 30])
@pytest.mark.parametrize("strategy", ["potential", "compensate"])
def test_the_mean_is_kept_on_many_skewed_cases(cap, strategy):
    import random

    rng = random.Random(20261111 + cap)
    for _ in range(200):
        n = rng.randint(2, 12)
        inputs = zones(*[(rng.uniform(0.1, 20), rng.uniform(0.01, 1.0)) for _ in range(n)])
        r = distribute(inputs, strategy, cap, 80.0)
        assert weighted_mean_factor(r, inputs) == pytest.approx(1.0, abs=1e-9)
        assert not r.saturated
        lo, hi = 1 - cap / 100, 1 + cap / 100
        assert all(lo - 1e-12 <= z.factor <= hi + 1e-12 for z in r.zones)


def test_non_positive_or_invalid_inputs_are_rejected():
    for bad in (0.0, -0.2, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            distribute(zones((1, 0.4), (1, bad)), "potential", 20, 60.0)
    for area in (0.0, -1.0, float("nan")):
        with pytest.raises(ValueError):
            distribute(zones((area, 0.4), (1, 0.5)), "potential", 20, 60.0)
    with pytest.raises(ValueError):
        distribute(zones((1, 0.4)), "potential", 31, 60.0)
    with pytest.raises(ValueError):
        distribute(zones((1, 0.4)), "potential", -1, 60.0)
    with pytest.raises(ValueError):
        distribute(zones((1, 0.4)), "potential", 20, -5.0)
    with pytest.raises(ValueError):
        distribute(zones((1, 0.4)), "bogus", 20, 60.0)
    with pytest.raises(ValueError):
        distribute([], "uniform", 20, 60.0)
