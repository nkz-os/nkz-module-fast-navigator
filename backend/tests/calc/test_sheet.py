import json
from dataclasses import replace
from datetime import date

import pytest

from app.calc.sheet import COMPLETE, INCOMPLETE, calculate
from app.engine import ENGINE_VERSION
from app.engine import constants as C
from app.engine.corrections import apply_credits
from app.engine.nitrogen import n_requirement
from app.engine.phosphorus_potassium import k_requirement, p_requirement
from app.engine.types import CropSeason, Management, NCredits, SoilState
from app.inputs.crop import build_crop
from app.inputs.crops import FALLOW, crops_for_campaign
from app.inputs.irrigation import irrigation_credit
from app.inputs.organic import OrganicApplication, organic_credit
from app.inputs.provenance import DECLARED, MissingInput, Override, Sourced, missing
from app.inputs.soil import build_soil
from app.inputs.yield_target import resolve_yield
from tests.calc.builders import COEFF, H, assembled


def _o(param, value):
    return {param: Override(param, value, "technician", "t1", "2026-10-13T10:00:00Z")}


def test_a_complete_sheet_matches_the_engine():
    a = assembled()
    r = calculate(a)
    assert r.status == COMPLETE and not r.missing
    soil = SoilState(texture_class=a.soil.values["texture_class"].value, clay_pct=25.0, ph=7.8,
                     organic_matter_pct=1.9, p_olsen_mg_kg=14.0, k_mg_kg=220.0)
    current = CropSeason(a.crop.params, a.yield_target.yield_kg_ha.value,
                         a.yield_target.cv_pct.value, False)
    previous = CropSeason(a.previous_crop.params, a.previous_yield.yield_kg_ha.value, 0.0)
    expected = apply_credits(n_requirement(current, previous, soil, a.management), NCredits())
    assert r.n["avg_kg_ha"] == pytest.approx(expected.n_avg)
    assert r.n["min_kg_ha"] == pytest.approx(expected.n_min)
    p = p_requirement(current, soil, a.management, 4)
    k = k_requirement(current, soil, a.management, 4)
    assert r.p2o5["rate_kg_ha"] == pytest.approx(p.rate * C.P_TO_P2O5)
    assert r.k2o["rate_kg_ha"] == pytest.approx(k.rate * C.K_TO_K2O)
    assert r.versions["engine"] == ENGINE_VERSION
    assert r.versions["coefficients"] == "2026-10-11.1"
    json.dumps(r.to_dict())


def test_the_n_minimum_notice_only_for_strategies_1_and_2():
    codes = lambda r: {n.code for n in r.notices}
    assert "n_min_fallback_typical" in codes(calculate(assembled()))
    s3 = assembled(management=Management(strategy=3, tillage=True, irrigated=False))
    assert "n_min_fallback_typical" not in codes(calculate(s3))


def test_without_a_cv_n_is_missing_but_p_and_k_are_computed():
    target = resolve_yield(2027, {}, {2026: 5400.0}, None, {}, date(2026, 10, 13))
    r = calculate(assembled(yield_target=target))
    assert r.status == INCOMPLETE and r.n is None
    assert r.p2o5 is not None and r.k2o is not None
    assert MissingInput("yield.cv_pct", "plan", {"campaign": 2027}) in r.missing


def test_without_soil_p_only_p_is_missing():
    h = {k: v for k, v in H.items() if k not in ("phosphorusAvailable", "phosphorusMethod")}
    soil = build_soil([{"id": "a1", "horizons": [h]}], [], None, None, {})
    r = calculate(assembled(soil=soil))
    assert r.p2o5 is None and r.k2o is not None and r.n is not None
    assert MissingInput("soil.p_olsen_mg_kg", "soil", {}) in r.missing


def test_strategy_4_needs_no_soil_and_drops_the_threshold():
    r = calculate(assembled(soil=build_soil([], [], None, None, {}),
                            management=Management(strategy=4, tillage=True, irrigated=False)))
    assert r.p2o5["threshold_mg_kg"] is None and r.k2o["threshold_mg_kg"] is None
    assert r.p2o5["rate_kg_ha"] == pytest.approx(r.p2o5["exported_kg_ha"])


def test_fallow_needs_no_preceding_crop():
    choice = crops_for_campaign([], 2027, declared_crop="TRZAX", declared_previous=FALLOW)
    r = calculate(assembled(choice=choice, previous_crop=None, previous_yield=None))
    assert r.n is not None and r.n["terms_kg_ha"]["previous_residues"] == 0.0


def test_an_unknown_preceding_crop_blocks_n_only():
    choice = crops_for_campaign([], 2027, declared_crop="TRZAX")
    r = calculate(assembled(choice=choice, previous_crop=None, previous_yield=None))
    assert r.n is None and r.p2o5 is not None
    assert MissingInput("previous_crop", "plan", {"campaign": 2027}) in r.missing


def test_a_legume_needs_the_organic_matter():
    soil = build_soil([{"id": "a1", "horizons": [{k: v for k, v in H.items()
                                                  if k != "organicMatter"}]}], [], None, None, {})
    crop = build_crop("TRZAX", COEFF, _o("crop.n_fixing", True))
    r = calculate(assembled(crop=crop, soil=soil))
    assert r.n is None
    assert MissingInput("soil.organic_matter_pct", "soil", {}) in r.missing


def test_n_does_not_read_unneeded_soil_fields():
    other = H | {"phosphorusAvailable": 40.0, "potassiumExchangeable": 90.0, "sand": 10.0,
                 "clay": 50.0, "ph": 6.0}
    a = calculate(assembled())
    b = calculate(assembled(soil=build_soil([{"id": "a1", "horizons": [other]}], [], None, None, {})))
    assert a.n["avg_kg_ha"] == pytest.approx(b.n["avg_kg_ha"])


def test_strategy_4_does_not_read_the_soil():
    s4 = Management(strategy=4, tillage=True, irrigated=False)
    a = calculate(assembled(management=s4))
    b = calculate(assembled(management=s4, soil=build_soil([], [], None, None, {})))
    assert a.p2o5["rate_kg_ha"] == pytest.approx(b.p2o5["rate_kg_ha"])
    assert a.k2o["rate_kg_ha"] == pytest.approx(b.k2o["rate_kg_ha"])


def test_the_preceding_crop_s_cv_is_not_read():
    today = date(2026, 10, 13)
    flat = resolve_yield(2026, {}, {2025: 5400.0}, None, _o("previous_yield.cv_pct", 30.0), today,
                         prefix="previous_yield")
    zero_cv = replace(flat, cv_pct=Sourced(0.0, DECLARED))
    assert calculate(assembled(previous_yield=flat)).n["avg_kg_ha"] == pytest.approx(
        calculate(assembled(previous_yield=zero_cv)).n["avg_kg_ha"])


def test_pending_organic_availability_blocks_n():
    organic = organic_credit([OrganicApplication("slurry", 30.0, 0.5, 0.2, 0.6)], {})
    r = calculate(assembled(organic=organic))
    assert r.n is None
    assert MissingInput("organic.0.availability", "plan", {"material": "slurry"}) in r.missing


def test_irrigated_without_water_volume_blocks_n():
    r = calculate(assembled(management=Management(strategy=2, tillage=True, irrigated=True),
                            irrigation=irrigation_credit(True, None, missing(), {})))
    assert r.n is None
    assert MissingInput("irrigation.water_m3_ha", "plan", {}) in r.missing


def test_organic_p_is_subtracted_from_the_p2o5_rate():
    organic = organic_credit([OrganicApplication("cattle_manure", 20.0, 0.5, 0.2, 0.6)], {})
    base = calculate(assembled())
    r = calculate(assembled(organic=organic))
    assert r.p2o5["organic_credit_kg_ha"] == pytest.approx(40.0)
    assert r.p2o5["rate_kg_ha"] == pytest.approx(max(base.p2o5["rate_kg_ha"] - 40.0, 0.0))
    assert r.n["credits_kg_ha"]["organic_available_n"] == pytest.approx(25.0)


def test_estimated_soil_makes_the_sheet_provisional():
    est = [{"depthFrom": 0, "depthTo": 30, "sand": 40.0, "clay": 25.0, "ph": 7.8}]
    soil = build_soil([], est, None, None, _o("soil.p_olsen_mg_kg", 14.0) | _o("soil.k_mg_kg", 220.0))
    assert calculate(assembled(soil=soil)).provisional


def test_inputs_carry_every_value_with_its_provenance():
    r = calculate(assembled())
    assert r.inputs["crop.dm_product_pct"]["provenance"] == "table:panagos_2022"
    assert r.inputs["yield.kg_ha"]["provenance"] == "declared"
    assert r.inputs["soil.p_olsen_mg_kg"]["provenance"] == "measured"
    assert r.inputs["irrigation.n_kg_ha"]["note"] == "rainfed"
    assert r.inputs["region.nuts"]["value"] == "ES22"


def test_missing_inputs_are_listed_once():
    choice = crops_for_campaign([], 2027)
    r = calculate(assembled(choice=choice, previous_crop=None, previous_yield=None))
    fields = [m.field for m in r.missing]
    assert len(fields) == len(set(fields))
