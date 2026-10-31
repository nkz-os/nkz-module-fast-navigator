import pytest

from app.engine import constants as C
from app.engine.texture import texture_class
from app.inputs.provenance import (
    ENTERED,
    ESTIMATED,
    MEASURED,
    MISSING,
    MissingInput,
    Notice,
    Override,
)
from app.inputs.soil import build_soil, topsoil_mean

H = {"depthFrom": 0, "depthTo": 30, "sand": 40.0, "clay": 25.0, "ph": 7.8,
     "organicMatter": 1.9, "phosphorusAvailable": 14.0, "phosphorusMethod": "olsen",
     "potassiumExchangeable": 220.0, "potassiumMethod": "ammonium_acetate"}


def analysis(id_, horizons, day="2026-09-01"):
    return {"id": id_, "samplingDate": day, "laboratoryReference": "LAB-1",
            "dataSource": "lab_analysis", "horizons": horizons}


def _o(param, value):
    return {param: Override(param, value, "lab sheet", "u1", "2026-10-13T10:00:00Z")}


def test_a_full_laboratory_analysis():
    s = build_soil([analysis("a1", [H])], [], None, None, {})
    v = s.values
    assert s.analysis_id == "a1" and not s.provisional
    assert v["p_olsen_mg_kg"].value == 14.0 and v["p_olsen_mg_kg"].provenance == MEASURED
    assert v["k_mg_kg"].value == 220.0
    assert v["texture_class"].value == texture_class(40.0, 25.0)
    assert v["bulk_density_g_cm3"].value == C.CLASS_BULK_DENSITY[v["texture_class"].value]
    assert v["bulk_density_g_cm3"].provenance == "table:fertilicalc"
    assert v["mineral_n_kg_ha"].value == 0.0 and v["mineral_n_kg_ha"].provenance == MISSING


def test_the_newest_analysis_with_fertility_data_is_representative():
    texture_only = analysis("new", [{"depthFrom": 0, "depthTo": 30, "sand": 50.0}], "2026-10-01")
    s = build_soil([texture_only, analysis("old", [H], "2025-09-01")], [], None, None, {})
    assert s.analysis_id == "old"


def test_an_explicit_analysis_that_does_not_exist():
    s = build_soil([analysis("a1", [H])], [], "nope", None, {})
    assert s.analysis_id is None
    assert Notice("soil_analysis_not_found", {"analysis": "nope"}) in s.notices


def test_p_is_converted_to_olsen():
    h = dict(H, phosphorusAvailable=28.0, phosphorusMethod="bray1")
    s = build_soil([analysis("a1", [h])], [], None, None, {})
    assert s.values["p_olsen_mg_kg"].value == pytest.approx(28.0 * C.OLSEN_FACTOR["bray1"])
    assert s.values["p_olsen_mg_kg"].note == "method:bray1"


def test_mixed_p_methods_are_not_used():
    top = dict(H, depthTo=15)
    bottom = dict(H, depthFrom=15, phosphorusMethod="bray1")
    s = build_soil([analysis("a1", [top, bottom])], [], None, None, {})
    assert not s.values["p_olsen_mg_kg"].known
    assert Notice("soil_p_methods_mixed", {"analysis": "a1"}) in s.notices


def test_k_by_another_method_is_not_used():
    h = dict(H, potassiumMethod="mehlich3")
    s = build_soil([analysis("a1", [h])], [], None, None, {})
    assert not s.values["k_mg_kg"].known
    assert Notice("soil_k_method_unsupported", {"method": "mehlich3"}) in s.notices


def test_topsoil_mean_is_thickness_weighted_and_needs_every_horizon():
    hz = [{"depthFrom": 0, "depthTo": 10, "ph": 7.0}, {"depthFrom": 10, "depthTo": 40, "ph": 8.0},
          {"depthFrom": 40, "depthTo": 60, "ph": 9.0}]
    assert topsoil_mean(hz, "ph") == pytest.approx((7.0 * 10 + 8.0 * 20) / 30)
    assert topsoil_mean(hz + [{"depthFrom": 0, "depthTo": 5}], "ph") is None


def test_texture_and_ph_are_estimated_when_there_is_no_analysis():
    est = [{"depthFrom": 0, "depthTo": 30, "sand": 35.0, "clay": 30.0, "ph": 8.1}]
    s = build_soil([], est, None, None, {})
    assert s.provisional
    assert s.values["sand_pct"].provenance == ESTIMATED
    assert s.values["texture_class"].provenance == ESTIMATED
    assert not s.values["p_olsen_mg_kg"].known and not s.values["organic_matter_pct"].known


def test_an_estimate_out_of_range_is_dropped():
    est = [{"depthFrom": 0, "depthTo": 30, "sand": 450.0, "clay": 300.0, "ph": 8.1}]
    s = build_soil([], est, None, None, {})
    assert not s.values["sand_pct"].known
    assert Notice("soil_estimate_out_of_range", {"field": "sand", "value": 450.0}) in s.notices


def test_entered_values_win():
    s = build_soil([], [], None, None, {**_o("soil.p_olsen_mg_kg", 12.0), **_o("soil.texture_class", 4)})
    assert s.values["p_olsen_mg_kg"].provenance == ENTERED
    assert s.values["texture_class"].value == 4
    assert s.values["bulk_density_g_cm3"].value == C.CLASS_BULK_DENSITY[4]


def test_mineral_n_from_the_chosen_analysis():
    nmin = analysis("n1", [{"depthFrom": 0, "depthTo": 30, "nitrateN": 8.0, "ammoniumN": 2.0,
                            "bulkDensity": 1.4}])
    s = build_soil([analysis("a1", [H]), nmin], [], None, "n1", {})
    assert s.values["mineral_n_kg_ha"].value == pytest.approx(37.8)
    assert s.values["mineral_n_kg_ha"].provenance == MEASURED


def test_a_missing_n_form_counts_zero_and_is_reported():
    nmin = analysis("n1", [{"depthFrom": 0, "depthTo": 30, "nitrateN": 10.0}])
    s = build_soil([analysis("a1", [H]), nmin], [], None, "n1", {})
    bd = C.CLASS_BULK_DENSITY[texture_class(40.0, 25.0)]
    assert s.values["mineral_n_kg_ha"].value == pytest.approx(10.0 * bd * 30 * 0.1 * 0.9)
    assert Notice("nmin_form_not_measured", {"analysis": "n1", "missing": "ammoniumN"}) in s.notices


def test_a_p_value_without_its_method_makes_the_method_unknown():
    top = dict(H, depthTo=15)
    bottom = {k: v for k, v in H.items() if k != "phosphorusMethod"}
    bottom["depthFrom"] = 15
    s = build_soil([analysis("a1", [top, bottom])], [], None, None, {})
    assert not s.values["p_olsen_mg_kg"].known
    assert Notice("soil_p_method_unknown", {"analysis": "a1"}) in s.notices


def test_a_k_value_without_its_method_makes_the_method_unknown():
    top = dict(H, depthTo=15)
    bottom = {k: v for k, v in H.items() if k != "potassiumMethod"}
    bottom["depthFrom"] = 15
    s = build_soil([analysis("a1", [top, bottom])], [], None, None, {})
    assert not s.values["k_mg_kg"].known
    assert Notice("soil_k_method_unknown", {"analysis": "a1"}) in s.notices


def test_an_nmin_only_analysis_is_not_the_representative_one():
    n1 = analysis("n1", [{"depthFrom": 0, "depthTo": 30, "nitrateN": 10.0, "ammoniumN": 2.0}],
                  "2026-10-01")
    s = build_soil([n1, analysis("a1", [H], "2025-09-01")], [], None, None, {})
    assert s.analysis_id == "a1"


def test_no_chosen_nmin_analysis_is_not_blocking():
    s = build_soil([analysis("a1", [H])], [], None, None, {})
    assert s.nmin_missing == () and s.values["mineral_n_kg_ha"].note == "no_nmin_analysis"


def test_a_chosen_nmin_analysis_that_does_not_exist_blocks():
    s = build_soil([analysis("a1", [H])], [], None, "nope", {})
    assert MissingInput("soil.nmin_analysis", "soil", {"analysis": "nope"}) in s.nmin_missing
    assert Notice("nmin_analysis_not_found", {"analysis": "nope"}) in s.notices


def test_a_chosen_nmin_analysis_without_values_blocks():
    n1 = analysis("n1", [{"depthFrom": 0, "depthTo": 30, "sand": 40.0}])
    s = build_soil([analysis("a1", [H]), n1], [], None, "n1", {})
    assert MissingInput("soil.mineral_n", "soil", {"analysis": "n1"}) in s.nmin_missing
    assert any(n.code == "nmin_no_values" for n in s.notices)


def test_a_chosen_nmin_analysis_without_a_bulk_density_blocks():
    h = {k: v for k, v in H.items() if k not in ("sand", "clay")}
    n1 = analysis("n1", [{"depthFrom": 0, "depthTo": 30, "nitrateN": 8.0, "ammoniumN": 2.0}])
    s = build_soil([analysis("a1", [h]), n1], [], None, "n1", {})
    assert MissingInput("soil.bulk_density_g_cm3", "soil", {"analysis": "n1"}) in s.nmin_missing
    assert any(n.code == "nmin_bulk_density_unknown" for n in s.notices)


def test_a_credited_nmin_analysis_blocks_nothing():
    n1 = analysis("n1", [{"depthFrom": 0, "depthTo": 30, "nitrateN": 8.0, "ammoniumN": 2.0,
                          "bulkDensity": 1.4}])
    assert build_soil([analysis("a1", [H]), n1], [], None, "n1", {}).nmin_missing == ()


OC = [{"depthFrom": 0, "depthTo": 5, "organicCarbon": 4.0},
      {"depthFrom": 5, "depthTo": 30, "organicCarbon": 1.6}]


def test_organic_matter_is_estimated_from_the_organic_carbon_of_the_soil_module():
    s = build_soil([], OC, None, None, {})
    om = s.values["organic_matter_pct"]
    oc_mean = (4.0 * 5 + 1.6 * 25) / 30
    assert om.value == pytest.approx(oc_mean * 1.724)      # van Bemmelen factor
    assert om.provenance == ESTIMATED and om.source == "soil:estimated"
    assert s.provisional
    assert [n.code for n in s.notices] == ["soil_om_estimated"]
    assert Notice("soil_om_estimated", {"oc_pct": round(oc_mean, 2), "om_pct": round(om.value, 2)}) in s.notices
    assert MissingInput("soil.organic_matter_pct", "soil", {}) not in s.missing


def test_a_laboratory_organic_matter_beats_the_estimate():
    s = build_soil([analysis("a1", [H])], OC, None, None, {})
    assert s.values["organic_matter_pct"].value == 1.9
    assert s.values["organic_matter_pct"].provenance == MEASURED
    assert not any(n.code == "soil_om_estimated" for n in s.notices)


def test_an_override_beats_the_estimate():
    s = build_soil([], OC, None, None, _o("soil.organic_matter_pct", 2.5))
    assert s.values["organic_matter_pct"].value == 2.5
    assert not any(n.code == "soil_om_estimated" for n in s.notices)


def test_no_organic_matter_without_organic_carbon_in_every_horizon():
    s = build_soil([], [OC[0], {"depthFrom": 5, "depthTo": 30}], None, None, {})
    assert not s.values["organic_matter_pct"].known


def test_an_organic_carbon_out_of_range_is_dropped():
    s = build_soil([], [{"depthFrom": 0, "depthTo": 30, "organicCarbon": 400.0}], None, None, {})
    assert not s.values["organic_matter_pct"].known
    assert any(n.code == "soil_estimate_out_of_range" for n in s.notices)
