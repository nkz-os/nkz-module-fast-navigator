from dataclasses import replace
from datetime import date

import pytest

from app.rules import evaluate
from app.rules.context import PlanContext, SheetContext
from app.rules.es import advice, rd1051
from app.rules.es.annex3 import valid_adjustment
from app.rules.registry import RULES_VERSION, all_rules

P1 = "urn:ngsi-ld:AgriParcel:p1"
SOIL = {f: {"value": 1.0, "provenance": "measured"} for f in rd1051.SOIL_FIELDS}


def result(avg=150.0, soil_n=20.0, organic=0.0, analysis=True, area=12.0):
    inputs = {f"parcel.{P1}.area_ha": {"value": area, "provenance": "measured"},
              f"parcel.{P1}.identifier": {"value": "31201A00100123", "provenance": "measured"},
              "region.nuts": {"value": "ES24", "provenance": "declared"},
              **(SOIL if analysis else {}),
              "soil.analysis_id": ({"value": "a1", "sampling_date": "2026-09-01"} if analysis
                                   else {"value": None, "sampling_date": None})}
    return {"status": "complete", "provisional": False, "missing": [],
            "n": {"avg_kg_ha": avg - soil_n - organic, "before_credits": {"avg_kg_ha": avg},
                  "credits_kg_ha": {"soil_mineral_n": soil_n, "organic_available_n": organic,
                                    "irrigation_n": 0.0}},
            "p2o5": {"rate_kg_ha": 40.0, "before_organic_kg_ha": 40.0},
            "k2o": {"rate_kg_ha": 30.0, "before_organic_kg_ha": 30.0}, "inputs": inputs}


APP = {"stage": "pre_plant", "kind": "mineral", "n_pct": 27, "n_form": "nitric",
       "product_rate_kg_ha": 300, "annex_v": [], "other_measure": None}


def sheet(**over):
    base = SheetContext(key="wheat", inputs={"irrigated": False, "strategy": 2, "organic": []},
                        parcels=({"urn": P1, "sigpac": None},), applications=(APP,),
                        result=result(), summary={"mineral_n_kg_ha": 81.0, "p2o5_kg_ha": 40.0,
                                                  "k2o_kg_ha": 30.0})
    return replace(base, **over)


def ctx(*sheets, at=date(2026, 10, 20), campaign=2027, vulnerable=None):
    return PlanContext(campaign=campaign, sheets=sheets or (sheet(),),
                       rain={"annual_mm": 600.0}, vulnerable_zone=vulnerable,
                       voluntary_digital_notebook=False, at=at)


def found(c, rule_id):
    return [f for f in evaluate(all_rules(), c) if f.rule_id == rule_id]


def test_version():
    assert RULES_VERSION == "es-2026.10.3"


# 1. soil data: transitional warning until the MAPA guides + 1 year
def test_missing_analysis_only_warns_while_the_guides_are_unpublished():
    c = ctx(sheet(result=result(analysis=False)))
    assert rd1051.SOIL_DATA_MANDATORY_FROM is None
    assert found(c, "ES-RD1051-6.2-soil") == []
    (w,) = found(c, "ES-RD1051-6.2-soil-transitional")
    assert w.severity == "warn" and "no_analysis" in w.params["reasons"]


def test_missing_analysis_blocks_once_soil_data_are_mandatory(monkeypatch):
    monkeypatch.setattr(rd1051, "SOIL_DATA_MANDATORY_FROM", date(2027, 6, 1))
    early = ctx(sheet(result=result(analysis=False)), at=date(2027, 5, 31))
    late = ctx(sheet(result=result(analysis=False)), at=date(2027, 6, 1))
    assert found(early, "ES-RD1051-6.2-soil") == [] and found(early, "ES-RD1051-6.2-soil-transitional")
    assert found(late, "ES-RD1051-6.2-soil")[0].severity == "block"
    assert found(late, "ES-RD1051-6.2-soil-transitional") == []


# 2. advice judged on the period the plan is applied in
def test_campaign_end():
    assert advice.campaign_end(2028) == date(2028, 8, 31)


@pytest.mark.parametrize("campaign,at,required", [
    (2028, date(2027, 8, 31), True),      # applied 1-Sep-2027..31-Aug-2028: advice due
    (2027, date(2027, 8, 31), False),     # applied until 31-Aug-2027: not yet
    (2027, date(2027, 9, 2), True),       # closed after the deadline
])
def test_advice_follows_the_period_of_application(campaign, at, required):
    assert advice.advice_required(ctx(at=at, campaign=campaign)) is required


def test_a_later_planned_date_extends_the_period():
    late = {**APP, "planned_date": "2027-09-15"}
    c = ctx(sheet(applications=(late,)), at=date(2027, 3, 1), campaign=2027)
    assert advice.fertilization_until(c) == date(2027, 9, 15)
    assert advice.advice_required(c) is True
    (f,) = found(c, "ES-RD1051-6.6-advice")
    assert f.params["applies_until"] == "2027-09-15"


# 4. ureic N declared on the label
@pytest.mark.parametrize("app,ureic", [
    ({**APP, "n_form": "mixed", "n_pct": 32, "n_ureic_pct": 16}, True),
    ({**APP, "n_form": "mixed", "n_pct": 27, "n_ureic_pct": 0}, False),
    ({**APP, "kind": "organo_mineral", "n_form": "mixed", "n_pct": 10, "n_ureic_pct": 4}, True),
])
def test_declared_ureic_n_falls_under_12_3(app, ureic):
    assert bool(found(ctx(sheet(applications=(app,))), "ES-RD1051-12.3")) is ureic


# 5. justified N adjustment (annex III-I.3)
ADJ = {"basis": "foliar_analysis", "date": "2026-10-01", "reference": "LAB-77",
       "description": "N deficiency in flag leaf", "justified_n_kg_ha": 200.0}


def over_limit(adjustment):
    # calculated 130 (150 − 20 soil), limit 156; effective 180
    return sheet(summary={"mineral_n_kg_ha": 180.0, "p2o5_kg_ha": 40.0, "k2o_kg_ha": 30.0},
                 n_adjustment=adjustment)


def test_a_justified_adjustment_lifts_the_n_limit_up_to_the_justified_value():
    c = ctx(over_limit(ADJ))
    assert found(c, "ES-RD1051-AIII-3-N") == []
    (i,) = found(c, "ES-RD1051-AIII-3-N-adjusted")
    assert i.severity == "info" and i.params["justified_n_kg_ha"] == 200.0
    assert i.params["basis"] == "foliar_analysis"


@pytest.mark.parametrize("bad", [
    {**ADJ, "justified_n_kg_ha": 170.0},              # below the effective N
    {**ADJ, "date": "2026-11-01"},                    # in the future
    {**ADJ, "reference": " "},                        # analysis without reference
    {**ADJ, "basis": "hunch"},
    {**ADJ, "description": ""},
])
def test_an_insufficient_adjustment_still_blocks(bad):
    c = ctx(over_limit(bad))
    assert found(c, "ES-RD1051-AIII-3-N")[0].severity == "block"
    assert found(c, "ES-RD1051-AIII-3-N-adjusted") == []


def test_year_evolution_needs_no_reference():
    adj = {**ADJ, "basis": "year_evolution", "reference": None}
    assert valid_adjustment(adj, date(2026, 10, 20)) is not None
