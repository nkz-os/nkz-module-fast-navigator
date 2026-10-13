from dataclasses import replace
from datetime import date

import pytest

from app.rules import BLOCK, evaluate
from app.rules.context import PlanContext, SheetContext
from app.rules.registry import RULES_VERSION, all_rules

P1 = "urn:ngsi-ld:AgriParcel:p1"
GOOD_APP = {"stage": "pre_plant", "kind": "mineral", "product_name": "NPK 8-15-15",
            "n_pct": 8, "p2o5_pct": 15, "k2o_pct": 15, "n_form": "ammoniacal",
            "product_rate_kg_ha": 300, "method": "broadcast", "machine": "spreader",
            "annex_v": [], "other_measure": None}


def result(**over):
    base = {
        "status": "complete", "provisional": False, "missing": [],
        "n": {"avg_kg_ha": 120.0}, "p2o5": {"rate_kg_ha": 40.0}, "k2o": {"rate_kg_ha": 30.0},
        "inputs": {
            f"parcel.{P1}.area_ha": {"value": 12.0, "provenance": "measured"},
            f"parcel.{P1}.identifier": {"value": "31201A00100123", "provenance": "measured"},
            "soil.analysis_id": {"value": "a1", "sampling_date": "2026-09-01"},
            "irrigation.water_m3_ha": {"value": 0.0, "provenance": "declared"},
            "region.nuts": {"value": "ES24", "provenance": "declared"},
            "yield.basis": {"value": "zone", "years": [2020]},
        },
    }
    base.update(over)
    return base


def sheet(**over):
    base = SheetContext(key="wheat", inputs={"irrigated": False, "strategy": 2},
                        parcels=({"urn": P1, "sigpac": None},), applications=(GOOD_APP,),
                        result=result(), summary={"mineral_n_kg_ha": 24.0})
    return replace(base, **over)


def ctx(*sheets, rain=None, notebook=False):
    return PlanContext(campaign=2027, sheets=sheets or (sheet(),),
                       rain={"annual_mm": 600.0} if rain is None else rain,
                       vulnerable_zone=True, voluntary_digital_notebook=notebook,
                       at=date(2026, 10, 20))


def ids(c, severity=None):
    return {f.rule_id for f in evaluate(all_rules(), c)
            if severity is None or f.severity == severity}


def test_a_good_plan_has_no_blocking_findings():
    assert ids(ctx(), BLOCK) == set()
    assert RULES_VERSION == "es-2026.10.0"


def test_scope_hint_for_small_rainfed_units():
    small = sheet(result=result(inputs={**result()["inputs"],
                                        f"parcel.{P1}.area_ha": {"value": 8.0}}))
    assert "ES-RD1051-4.2-scope" in ids(ctx(small))
    assert "ES-RD1051-4.2-scope" not in ids(ctx())


def test_recinto_needs_an_identifier():
    bare = result()
    bare["inputs"] = {k: v for k, v in bare["inputs"].items() if not k.endswith(".identifier")}
    assert "ES-RD1051-6.1-recinto" in ids(ctx(sheet(result=bare)), BLOCK)
    declared = sheet(result=bare, parcels=({"urn": P1, "sigpac": "31:201:0:0:1:123:1"},))
    assert "ES-RD1051-6.1-recinto" not in ids(ctx(declared))


@pytest.mark.parametrize("change", [
    {"inputs": {**result()["inputs"], "soil.analysis_id": {"value": None}}},
    {"provisional": True},
])
def test_soil_needs_a_laboratory_analysis(change):
    assert "ES-RD1051-6.2-soil" in ids(ctx(sheet(result=result(**change))), BLOCK)


def test_water_needs_the_rain_normal_and_the_irrigation_volume():
    assert "ES-RD1051-6.3-water" in ids(ctx(rain={}), BLOCK)
    irrigated = sheet(inputs={"irrigated": True, "strategy": 2},
                      result=result(inputs={**result()["inputs"],
                                            "irrigation.water_m3_ha": {"value": None}}))
    assert "ES-RD1051-6.3-water" in ids(ctx(irrigated), BLOCK)


def test_content_needs_applications_when_there_is_a_requirement():
    assert "ES-RD1051-6.4-content" in ids(ctx(sheet(applications=())), BLOCK)
    nothing = result(n={"avg_kg_ha": 0.0}, p2o5={"rate_kg_ha": 0.0}, k2o={"rate_kg_ha": 0.0})
    assert "ES-RD1051-6.4-content" not in ids(ctx(sheet(applications=(), result=nothing)))


def test_organic_applications_need_an_annex_v_a_measure():
    manure = {**GOOD_APP, "kind": "organic", "annex_v": []}
    assert "ES-RD1051-6.5-annexV" in ids(ctx(sheet(applications=(manure,))), BLOCK)
    assert "ES-RD1051-6.5-annexV" in ids(
        ctx(sheet(applications=({**manure, "annex_v": ["B.a"]},))), BLOCK)
    assert "ES-RD1051-6.5-annexV" not in ids(
        ctx(sheet(applications=({**manure, "annex_v": ["A.i"]},))))


def test_ammonium_carbonate_is_forbidden():
    bad = {**GOOD_APP, "kind": "ammonium_carbonate"}
    assert "ES-RD1051-12.1" in ids(ctx(sheet(applications=(bad,))), BLOCK)


@pytest.mark.parametrize("kind", ["urea", "urea_solution"])
def test_urea_needs_one_of_the_three_ways(kind):
    urea = {**GOOD_APP, "kind": kind, "n_form": "ureic", "annex_v": ["A.a"]}
    assert "ES-RD1051-12.3" in ids(ctx(sheet(applications=(urea,))), BLOCK)
    assert "ES-RD1051-12.3" not in ids(ctx(sheet(applications=({**urea, "annex_v": ["B.c"]},))))
    assert "ES-RD1051-12.3" not in ids(
        ctx(sheet(applications=({**urea, "other_measure": "urease inhibitor in the blend, "
                                                           "tested 35 % less NH3"},))))
    assert "ES-RD1051-12.3" not in ids(ctx(sheet(applications=(urea,)), notebook=True))
    assert "ES-RD1051-12.3" in ids(
        ctx(sheet(applications=({**urea, "other_measure": "   "},))), BLOCK)


def test_strategy_4_warns():
    assert "ES-RD1051-AIII-strategy4" in ids(
        ctx(sheet(inputs={"irrigated": False, "strategy": 4})), "warn")


def test_an_incomplete_sheet_blocks():
    assert "FAST-sheet-incomplete" in ids(ctx(sheet(result=None)), BLOCK)
    missing = result(status="incomplete", missing=[{"field": "soil.k_mg_kg", "owner": "soil",
                                                    "params": {}}])
    found = [f for f in evaluate(all_rules(), ctx(sheet(result=missing)))
             if f.rule_id == "FAST-sheet-incomplete"]
    assert found[0].params == {"missing": ["soil.k_mg_kg"]}


def test_a_zone_yield_from_the_point_lookup_must_be_confirmed():
    point = result(inputs={**result()["inputs"],
                           "region.nuts": {"value": "ES23",
                                           "provenance": "table:natural_earth_province"}})
    assert "FAST-region-unconfirmed" in ids(ctx(sheet(result=point)), BLOCK)
    exact = result(inputs={**result()["inputs"],
                           "region.nuts": {"value": "ES22", "provenance": "table:ine_province"}})
    assert "FAST-region-unconfirmed" not in ids(ctx(sheet(result=exact)))


def test_navarra_rules_are_flagged_as_not_checked():
    navarra = result(inputs={**result()["inputs"],
                             "region.nuts": {"value": "ES22", "provenance": "declared"}})
    assert "ES-NA-not-checked" in ids(ctx(sheet(result=navarra)), "info")
    assert "ES-NA-not-checked" not in ids(ctx())


def test_every_finding_carries_its_citation():
    bad = sheet(applications=({**GOOD_APP, "kind": "ammonium_carbonate"},))
    for f in evaluate(all_rules(), ctx(bad)):
        assert f.citation.startswith(("RD 1051/2022", "FaST", "Navarra"))
