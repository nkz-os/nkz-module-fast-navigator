from dataclasses import replace
from datetime import date

import pytest

from app.rules import BLOCK, WARN, evaluate
from app.rules.context import PlanContext, SheetContext
from app.rules.es import rd1051
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
            "soil.ph": {"value": 7.8, "provenance": "measured"},
            "soil.organic_matter_pct": {"value": 1.9, "provenance": "measured"},
            "soil.p_olsen_mg_kg": {"value": 14.0, "provenance": "entered"},
            "soil.k_mg_kg": {"value": 210.0, "provenance": "measured"},
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
    assert RULES_VERSION == "es-2026.10.3"


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


def inputs_with(**over):
    return {**result()["inputs"], **over}


@pytest.fixture
def soil_mandatory(monkeypatch):
    """Soil data are mandatory (MAPA guides published + 1 year) for the blocking 6.2 rule."""
    monkeypatch.setattr(rd1051, "SOIL_DATA_MANDATORY_FROM", date(2026, 1, 1))


def soil_findings(c, rule_id="ES-RD1051-6.2-soil"):
    return [f for f in evaluate(all_rules(), c) if f.rule_id == rule_id]


def test_soil_needs_a_laboratory_analysis(soil_mandatory):
    none = result(inputs=inputs_with(**{"soil.analysis_id": {"value": None}}))
    (f,) = soil_findings(ctx(sheet(result=none)))
    assert f.severity == BLOCK and f.params["reasons"] == ["no_analysis"]


def test_soil_gaps_only_warn_while_soil_data_are_not_mandatory():
    none = result(inputs=inputs_with(**{"soil.analysis_id": {"value": None}}))
    c = ctx(sheet(result=none))
    assert soil_findings(c) == []
    (f,) = soil_findings(c, "ES-RD1051-6.2-soil-transitional")
    assert f.severity == WARN and f.params["reasons"] == ["no_analysis"]


def test_estimated_texture_does_not_block_a_measured_analysis():
    est = result(provisional=True, inputs=inputs_with(
        **{"soil.sand_pct": {"value": 40, "provenance": "estimated"},
           "soil.clay_pct": {"value": 25, "provenance": "estimated"}}))
    assert soil_findings(ctx(sheet(result=est))) == []


def test_estimated_or_missing_legal_soil_values_block(soil_mandatory):
    est = result(inputs=inputs_with(**{"soil.ph": {"value": 7.0, "provenance": "estimated"},
                                       "soil.k_mg_kg": {"value": None, "provenance": "missing"}}))
    (f,) = soil_findings(ctx(sheet(result=est)))
    assert f.params["reasons"] == ["not_measured"]
    assert f.params["fields"] == ["soil.ph", "soil.k_mg_kg"]


def analysed(date_s, irrigated):
    return sheet(inputs={"irrigated": irrigated, "strategy": 2}, result=result(
        inputs=inputs_with(**{"soil.analysis_id": {"value": "a1", "sampling_date": date_s}})))


def test_analysis_age_limits_depend_on_irrigation(soil_mandatory):
    (old,) = soil_findings(ctx(analysed("2016-10-19", False)))
    assert old.params["reasons"] == ["too_old"]
    assert old.params["sampling_date"] == "2016-10-19" and old.params["max_age_years"] == 10
    assert soil_findings(ctx(analysed("2016-10-20", False))) == []
    (irr,) = soil_findings(ctx(analysed("2020-10-01", True)))
    assert irr.params["reasons"] == ["too_old"] and irr.params["max_age_years"] == 5
    assert soil_findings(ctx(analysed("2020-10-01", False))) == []


def test_analysis_without_sampling_date_blocks(soil_mandatory):
    (f,) = soil_findings(ctx(analysed(None, False)))
    assert f.params["reasons"] == ["no_sampling_date"]


def test_datetime_sampling_dates_are_accepted_and_garbage_blocks(soil_mandatory):
    assert soil_findings(ctx(analysed("2026-09-01T00:00:00Z", False))) == []
    (f,) = soil_findings(ctx(analysed("last spring", False)))
    assert f.params["reasons"] == ["no_sampling_date"]


def no_analysis_sheet(area):
    return sheet(result=result(inputs=inputs_with(**{
        "soil.analysis_id": {"value": None}, f"parcel.{P1}.area_ha": {"value": area}})))


def test_small_sheet_of_a_small_unit_is_exempt_from_the_analysis():
    c = ctx(no_analysis_sheet(4.0))
    assert soil_findings(c) == []
    (f,) = soil_findings(c, "ES-RD1051-6.2-analysis-exempt")
    assert f.severity == "info"
    assert f.params == {"sheet_area_ha": 4.0, "unit_area_ha": 4.0}
    assert f.citation == "RD 1311/2012, annex III part I C.i.d (RD 1051/2022)"


def test_exemption_needs_a_unit_of_at_most_20_ha_and_a_known_area(soil_mandatory):
    P2 = "urn:ngsi-ld:AgriParcel:p2"
    big = sheet(key="maize", parcels=({"urn": P2, "sigpac": None},), result=result(
        inputs={f"parcel.{P2}.area_ha": {"value": 21.0}, "soil.analysis_id": {"value": "a2"}}))
    c = ctx(no_analysis_sheet(4.0), big)
    assert "wheat" in [f.sheet_key for f in soil_findings(c)]
    assert soil_findings(c, "ES-RD1051-6.2-analysis-exempt") == []
    unknown = sheet(result=result(inputs=inputs_with(**{"soil.analysis_id": {"value": None},
                                                         f"parcel.{P1}.area_ha": {"value": None}})))
    assert soil_findings(ctx(unknown))


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


MANURE_INPUT = {"kind": "manure", "kg_ha": 20000}


def findings(c, rule_id):
    return [f for f in evaluate(all_rules(), c) if f.rule_id == rule_id]


def test_an_organic_input_without_an_application_blocks_6_4():
    organic_sheet = sheet(inputs={"irrigated": False, "strategy": 2, "organic": [MANURE_INPUT]})
    hits = findings(ctx(organic_sheet), "ES-RD1051-6.4-content")
    assert [(f.params, f.severity) for f in hits] == [({"organic": 0}, BLOCK)]


def test_an_organic_input_covering_the_requirement_still_needs_an_application():
    nothing = result(n={"avg_kg_ha": 0.0}, p2o5={"rate_kg_ha": 0.0}, k2o={"rate_kg_ha": 0.0})
    only = sheet(inputs={"irrigated": False, "strategy": 2, "organic": [MANURE_INPUT]},
                 applications=(), result=nothing)
    assert [f.params for f in findings(ctx(only), "ES-RD1051-6.4-content")] == [{"organic": 0}]


def test_an_organic_input_with_its_application_passes_6_4_and_6_5():
    manure = {**GOOD_APP, "kind": "organic", "organic_index": 0, "annex_v": ["A.i"]}
    organic_sheet = sheet(inputs={"irrigated": False, "strategy": 2, "organic": [MANURE_INPUT]},
                          applications=(GOOD_APP, manure))
    c = ctx(organic_sheet)
    assert not findings(c, "ES-RD1051-6.4-content")
    assert not findings(c, "ES-RD1051-6.5-annexV")


def test_only_the_organic_inputs_without_application_block():
    manure = {**GOOD_APP, "kind": "organic", "organic_index": 1, "annex_v": ["A.i"]}
    organic_sheet = sheet(inputs={"irrigated": False, "strategy": 2,
                                  "organic": [MANURE_INPUT, MANURE_INPUT]},
                          applications=(GOOD_APP, manure))
    assert [f.params for f in findings(ctx(organic_sheet), "ES-RD1051-6.4-content")] == [
        {"organic": 0}]


def test_organic_applications_need_an_annex_v_a_measure():
    manure = {**GOOD_APP, "kind": "organic", "annex_v": []}
    assert "ES-RD1051-6.5-annexV" in ids(ctx(sheet(applications=(manure,))), BLOCK)
    assert "ES-RD1051-6.5-annexV" in ids(
        ctx(sheet(applications=({**manure, "annex_v": ["B.a"]},))), BLOCK)
    assert "ES-RD1051-6.5-annexV" not in ids(
        ctx(sheet(applications=({**manure, "annex_v": ["A.i"]},))))


def test_a_described_measure_satisfies_6_5():
    manure = {**GOOD_APP, "kind": "organic", "annex_v": []}
    text = {**manure, "other_measure": "composted, incorporated within 4 h"}
    assert "ES-RD1051-6.5-annexV" not in ids(ctx(sheet(applications=(text,))))
    blank = {**manure, "other_measure": "   "}
    assert "ES-RD1051-6.5-annexV" in ids(ctx(sheet(applications=(blank,))), BLOCK)
    mixed = {**GOOD_APP, "kind": "organo_mineral", "annex_v": []}
    assert "ES-RD1051-6.5-annexV" in ids(ctx(sheet(applications=(mixed,))), BLOCK)


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


def test_mineral_product_with_ureic_n_falls_under_12_3():
    ureic = {**GOOD_APP, "kind": "mineral", "n_form": "ureic", "annex_v": []}
    assert "ES-RD1051-12.3" in ids(ctx(sheet(applications=(ureic,))), BLOCK)
    assert "ES-RD1051-12.3" not in ids(ctx(sheet(applications=({**ureic, "annex_v": ["B.a"]},))))


def test_organo_mineral_product_with_ureic_n_falls_under_12_3():
    mixed = {**GOOD_APP, "kind": "organo_mineral", "n_form": "ureic", "annex_v": ["A.i"]}
    assert "ES-RD1051-12.3" in ids(ctx(sheet(applications=(mixed,))), BLOCK)
    assert "ES-RD1051-12.3" not in ids(ctx(sheet(applications=({**mixed, "annex_v": ["B.c"]},))))
    organic = {**mixed, "kind": "organic", "annex_v": ["A.i"]}
    assert "ES-RD1051-12.3" not in ids(ctx(sheet(applications=(organic,))))


def test_unknown_area_is_not_a_scope_exemption():
    small = sheet(result=result(inputs=inputs_with(**{f"parcel.{P1}.area_ha": {"value": 8.0}})))
    assert "ES-RD1051-4.2-scope" in ids(ctx(small))
    assert "ES-RD1051-4.2-scope" not in ids(ctx(small, sheet(key="other", result=None)))
    noarea = sheet(key="other", parcels=({"urn": "urn:x", "sigpac": None},))
    assert "ES-RD1051-4.2-scope" not in ids(ctx(small, noarea))


def test_a_zone_previous_yield_from_the_point_lookup_must_be_confirmed():
    point = result(inputs=inputs_with(
        **{"yield.basis": {"value": "farm"}, "previous_yield.basis": {"value": "zone"},
           "region.nuts": {"value": "ES23", "provenance": "table:natural_earth_province"}}))
    assert "FAST-region-unconfirmed" in ids(ctx(sheet(result=point)), BLOCK)


def test_a_sheet_needing_only_p_still_needs_applications():
    only_p = result(n={"avg_kg_ha": 0.0}, p2o5={"rate_kg_ha": 30.0}, k2o={"rate_kg_ha": 0.0})
    assert "ES-RD1051-6.4-content" in ids(ctx(sheet(applications=(), result=only_p)), BLOCK)


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


def test_an_unknown_region_is_flagged_once_for_the_plan():
    unknown = result(inputs={k: v for k, v in result()["inputs"].items()
                             if k != "region.nuts"})
    second = replace(sheet(result=unknown), key="barley")
    hits = findings(ctx(sheet(result=unknown), second), "FAST-region-unknown")
    assert [(f.severity, f.params, f.sheet_key) for f in hits] == [
        ("info", {"sheets": ["wheat", "barley"]}, None)]
    assert hits[0].citation.startswith("FaST")
    assert not findings(ctx(), "FAST-region-unknown")


def test_every_finding_carries_its_citation():
    bad = sheet(applications=({**GOOD_APP, "kind": "ammonium_carbonate"},))
    for f in evaluate(all_rules(), ctx(bad)):
        assert f.citation.startswith(("RD 1051/2022", "FaST", "Navarra"))
