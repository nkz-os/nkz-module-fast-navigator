import statistics
from datetime import date

import pytest

from app.inputs.provenance import ENTERED, MissingInput, Notice, Override
from app.inputs.yield_target import (
    combine_histories,
    history_yields,
    resolve_yield,
    zone_needed,
)
from tests.conftest import load_contract

ZONE = load_contract("bioorch_regional_yields_trzax_es22.json")
TODAY = date(2026, 10, 13)


def cycle(species, label, start, end, role="main_crop"):
    return {"crop_id": f"urn:ngsi-ld:AgriCrop:{species}{label}", "role": role,
            "species": species, "status": "harvested",
            "start": {"date": start, "provenance": "operation"},
            "end": {"date": end, "provenance": "operation"}, "campaign_label": label}


def harvest(day, kg):
    return {"id": f"urn:ngsi-ld:AgriParcelOperation:h{day}", "operationType": "harvesting",
            "endedAt": {"@type": "DateTime", "@value": f"{day}T10:00:00Z"},
            "harvestedWeight": kg}


def _o(param, value):
    return {param: Override(param, value, "own records", "u1", "2026-10-13T10:00:00Z")}


def test_history_counts_only_this_crop_s_cycles():
    cycles = [cycle("TRZAX", 2024, "2023-10-20", "2024-07-10"),
              cycle("HORVX", 2025, "2024-10-25", "2025-07-01")]
    harvests = [harvest("2024-07-10", 50000), harvest("2025-07-01", 40000)]
    got, notices = history_yields(cycles, harvests, "TRZAX", 10.0)
    assert got == {2024: 5000.0} and not notices


def test_a_zero_harvest_is_the_blank_field_not_a_failed_crop():
    cycles = [cycle("TRZAX", 2024, "2023-10-20", "2024-07-10")]
    got, notices = history_yields(cycles, [harvest("2024-07-10", 0)], "TRZAX", 10.0)
    assert got == {}
    assert notices == (Notice("harvest_zero_ignored",
                              {"operation": "urn:ngsi-ld:AgriParcelOperation:h2024-07-10",
                               "campaign": 2024}),)


def test_a_harvest_long_after_the_cycle_is_not_counted():
    cycles = [cycle("TRZAX", 2024, "2023-10-20", "2024-07-10")]
    got, _ = history_yields(cycles, [harvest("2024-09-01", 50000)], "TRZAX", 10.0)
    assert got == {}


def test_cover_crops_never_enter_the_history():
    cycles = [cycle("TRZAX", 2024, "2023-10-20", "2024-07-10", role="cover_crop")]
    got, _ = history_yields(cycles, [harvest("2024-07-10", 50000)], "TRZAX", 10.0)
    assert got == {}


def test_histories_of_several_parcels_are_area_weighted():
    assert combine_histories([({2024: 5000.0}, 10.0), ({2024: 6000.0}, 30.0),
                              ({2023: 4000.0}, 5.0)]) == {2024: 5750.0, 2023: 4000.0}


def test_history_basis_with_three_campaigns_or_more():
    history = {2021: 5000.0, 2022: 6000.0, 2023: 5500.0, 2024: 6500.0, 2025: 5200.0,
               2019: 9000.0}
    t = resolve_yield(2026, history, {}, None, {}, TODAY)
    window = [5000.0, 6000.0, 5500.0, 6500.0, 5200.0]
    assert t.basis == "history" and t.years == (2021, 2022, 2023, 2024, 2025)
    assert t.yield_kg_ha.value == statistics.median(window)
    assert t.cv_pct.value == pytest.approx(statistics.stdev(window) / statistics.fmean(window) * 100)
    assert t.yield_kg_ha.provenance == "measured" and not t.missing


def test_declared_when_the_history_is_too_short():
    t = resolve_yield(2026, {2025: 5000.0, 2024: 5100.0},
                      {2023: 6000.0, 2024: 6200.0, 2025: 5800.0}, None, {}, TODAY)
    assert t.basis == "declared" and t.yield_kg_ha.value == 6000.0
    assert t.cv_pct.provenance == "declared"
    assert Notice("history_too_short", {"years": [2024, 2025]}) in t.notices


def test_one_declared_year_takes_the_cv_from_the_zone():
    t = resolve_yield(2026, {}, {2025: 6000.0}, ZONE, {}, TODAY)
    assert t.basis == "declared" and t.cv_pct.note == "cv_from_zone"
    assert t.cv_pct.provenance == "table:eurostat_apro_cpshr"


def test_zone_basis():
    t = resolve_yield(2026, {}, {}, ZONE, {}, TODAY)
    by_year = {r["year"]: r["yield_t_ha"] * 1000 for r in ZONE["series"]}
    recent = [by_year[y] for y in ZONE["recent_years"]]
    assert t.basis == "zone" and t.years == tuple(ZONE["recent_years"])
    assert t.yield_kg_ha.value == pytest.approx(ZONE["recent_median_t_ha"] * 1000)
    assert t.yield_kg_ha.provenance == "table:eurostat_apro_cpshr"
    assert t.cv_pct.value == pytest.approx(statistics.stdev(recent) / statistics.fmean(recent) * 100)
    assert not t.notices


def test_a_stale_zone_is_flagged():
    zone = dict(ZONE, latest_year=2019)
    t = resolve_yield(2026, {}, {}, zone, {}, TODAY)
    assert Notice("zone_yield_stale", {"latest_year": 2019, "nuts": "ES22"}) in t.notices


def test_no_basis_at_all_is_missing():
    zone = dict(ZONE, recent_median_t_ha=None)
    t = resolve_yield(2026, {}, {}, zone, {}, TODAY, prefix="previous_yield")
    assert t.basis == "missing"
    assert MissingInput("previous_yield.kg_ha", "plan", {"campaign": 2026}) in t.missing
    assert MissingInput("previous_yield.cv_pct", "plan", {"campaign": 2026}) in t.missing


def test_the_technician_overrides_both_values():
    o = {**_o("yield.kg_ha", 7000.0), **_o("yield.cv_pct", 12.0)}
    t = resolve_yield(2026, {}, {}, None, o, TODAY)
    assert t.basis == "entered" and t.yield_kg_ha.value == 7000.0
    assert t.cv_pct.provenance == ENTERED and not t.missing


def test_when_the_zone_is_needed():
    three = {2023: 1.0, 2024: 1.0, 2025: 1.0}
    assert not zone_needed(2026, three, {}, {})
    assert not zone_needed(2026, {}, three, {})
    assert zone_needed(2026, {}, {2025: 6000.0}, {})
    assert zone_needed(2026, {2025: 1.0}, {}, {})
    assert not zone_needed(2026, {}, {}, {**_o("yield.kg_ha", 1.0), **_o("yield.cv_pct", 1.0)})


def test_history_reads_the_cycles_the_platform_sdk_emits():
    from tests.inputs.test_crops import _sdk_cycles
    harvests = [harvest("2026-07-10", 80000)]
    got, _ = history_yields(_sdk_cycles(), harvests, "TRZAX", 10.0)
    assert got == {2026: 8000.0}
