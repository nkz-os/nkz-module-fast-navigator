from dataclasses import replace
from datetime import date

import pytest

from app.rules import evaluate
from app.rules.context import PlanContext, SheetContext
from app.rules.es import annex3
from app.rules.es.advice import (
    ADVICE_OTHER,
    ADVICE_VULNERABLE,
    advice_required,
    advice_required_from,
    exempt,
)
from app.rules.registry import all_rules

P1 = "urn:ngsi-ld:AgriParcel:p1"


def result(avg=150.0, soil_n=20.0, organic=30.0, p2o5=50.0, k2o=40.0, area=12.0):
    return {"status": "complete", "provisional": False, "missing": [],
            "n": {"avg_kg_ha": avg - soil_n - organic,
                  "before_credits": {"avg_kg_ha": avg},
                  "credits_kg_ha": {"soil_mineral_n": soil_n, "organic_available_n": organic,
                                    "irrigation_n": 0.0}},
            "p2o5": {"rate_kg_ha": p2o5, "before_organic_kg_ha": p2o5},
            "k2o": {"rate_kg_ha": k2o, "before_organic_kg_ha": k2o},
            "inputs": {f"parcel.{P1}.area_ha": {"value": area, "provenance": "measured"}}}


def sheet(mineral_n=100.0, p2o5=50.0, k2o=40.0, history=(), res=None, irrigated=False):
    return SheetContext(key="wheat", inputs={"irrigated": irrigated, "strategy": 2},
                        parcels=({"urn": P1, "sigpac": None},), applications=(),
                        result=res or result(),
                        summary={"mineral_n_kg_ha": mineral_n, "p2o5_kg_ha": p2o5,
                                 "k2o_kg_ha": k2o}, history=tuple(history))


def ctx(*sheets, at=date(2026, 10, 20), vulnerable=None):
    return PlanContext(campaign=2027, sheets=sheets or (sheet(),), rain={"annual_mm": 600.0},
                       vulnerable_zone=vulnerable, voluntary_digital_notebook=False, at=at)


def found(c, rule_id):
    return [f for f in evaluate(all_rules(), c) if f.rule_id == rule_id]


def test_calculated_and_effective_n():
    r = result()
    assert annex3.calculated_n(r) == pytest.approx(130.0)       # 150 − 20 soil mineral N
    assert annex3.effective_n(r, {"mineral_n_kg_ha": 100.0}) == pytest.approx(130.0)  # + 30 organic
    assert annex3.calculated_n({"n": None}) is None


def test_n_limit_is_twenty_percent_over_the_calculated():
    assert found(ctx(sheet(mineral_n=126.0)), "ES-RD1051-AIII-3-N") == []      # 156 = 130 × 1.2
    over = found(ctx(sheet(mineral_n=126.5)), "ES-RD1051-AIII-3-N")
    assert over[0].severity == "block"
    assert over[0].params == {"effective_n_kg_ha": 156.5, "calculated_n_kg_ha": 130.0,
                              "limit_kg_ha": 156.0}


def test_p_and_k_limits_over_five_years():
    history = [{"campaign": y, "p2o5_planned_kg_ha": 90.0, "p2o5_calculated_kg_ha": 50.0,
                "k2o_planned_kg_ha": 40.0, "k2o_calculated_kg_ha": 40.0} for y in (2023, 2024,
                                                                                2025, 2026)]
    p = found(ctx(sheet(p2o5=50.0, history=history)), "ES-RD1051-AIII-4-P")
    assert p[0].severity == "warn"
    assert p[0].params["planned_kg_ha"] == 410.0 and p[0].params["calculated_kg_ha"] == 250.0
    assert p[0].params["years"] == [2023, 2024, 2025, 2026, 2027]
    assert found(ctx(sheet(history=history)), "ES-RD1051-AIII-5-K") == []
    assert found(ctx(sheet(history=history)), "ES-RD1051-AIII-history-short") == []


def test_a_single_high_year_does_not_breach_the_five_year_limit_alone():
    history = [{"campaign": y, "p2o5_planned_kg_ha": 20.0, "p2o5_calculated_kg_ha": 50.0,
                "k2o_planned_kg_ha": None, "k2o_calculated_kg_ha": None} for y in (2025, 2026)]
    assert found(ctx(sheet(p2o5=90.0, history=history)), "ES-RD1051-AIII-4-P") == []
    short = found(ctx(sheet(history=history)), "ES-RD1051-AIII-history-short")
    assert short[0].params == {"years_available": 2}


def test_advice_dates():
    assert advice_required_from(None) == ADVICE_VULNERABLE == date(2027, 9, 1)
    assert advice_required_from(True) == ADVICE_VULNERABLE
    assert advice_required_from(False) == ADVICE_OTHER == date(2028, 9, 1)


@pytest.mark.parametrize("at,vulnerable,required", [
    (date(2027, 8, 31), None, False), (date(2027, 9, 1), None, True),
    (date(2027, 9, 1), True, True), (date(2027, 9, 1), False, False),
    (date(2028, 9, 1), False, True),
])
def test_advice_required(at, vulnerable, required):
    assert advice_required(ctx(at=at, vulnerable=vulnerable)) is required


def test_exempt_units_need_no_advice():
    small = sheet(res=result(area=8.0))
    assert exempt(ctx(small)) and not advice_required(ctx(small, at=date(2029, 1, 1)))
    assert not exempt(ctx(replace(small, inputs={"irrigated": True, "strategy": 2})))


def test_advice_finding_is_informative():
    (f,) = found(ctx(at=date(2027, 10, 1)), "ES-RD1051-6.6-advice")
    assert f.severity == "info"
    assert f.params == {"required": True, "required_from": "2027-09-01", "vulnerable_zone": None,
                        "assumed_vulnerable": True, "exempt": False, "irrigated_dates": False,
                        "applies_until": "2027-08-31", "irrigated_spring_2026": None,
                        "assumed_spring_2026": False}


def test_irrigated_plans_use_the_earlier_dates():
    assert advice_required_from(None, True) == date(2027, 1, 1)
    assert advice_required_from(False, True) == date(2028, 1, 1)
    irr = sheet(irrigated=True)
    assert advice_required(ctx(irr, at=date(2027, 2, 1)))
    assert not advice_required(ctx(sheet(), at=date(2027, 2, 1)))
    assert not advice_required(ctx(irr, at=date(2027, 12, 31), vulnerable=False))
    assert advice_required(ctx(irr, at=date(2028, 1, 1), vulnerable=False))
    (f,) = found(ctx(irr, at=date(2027, 2, 1)), "ES-RD1051-6.6-advice")
    assert f.params["irrigated_dates"] is True and f.params["required_from"] == "2027-01-01"


def test_unknown_area_is_never_exempt():
    small = sheet(res=result(area=8.0))
    assert exempt(ctx(small))
    uncalculated = replace(sheet(), key="other", result=None)
    assert not exempt(ctx(small, uncalculated))
    assert advice_required(ctx(small, uncalculated, at=date(2027, 9, 1)))
    noarea = replace(sheet(), key="other", parcels=({"urn": "urn:x", "sigpac": None},))
    assert not exempt(ctx(small, noarea))
