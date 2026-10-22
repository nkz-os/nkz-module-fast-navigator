from datetime import date

import pytest

from app.compliance.realized import PARSED, STRUCTURED, UNREADABLE, parse_operation

P1 = "urn:ngsi-ld:AgriParcel:p1"


def op(**over):
    base = {"id": "urn:ngsi-ld:AgriParcelOperation:o1", "type": "AgriParcelOperation",
            "operationType": "fertilization", "status": "completed", "hasAgriParcel": P1,
            "endedAt": {"@type": "DateTime", "@value": "2027-02-10T09:00:00Z"},
            "fertilizerType": "NAC 27", "fertilizerRate": 200,
            "nitrogenContent": 27, "nitrogenForm": "nitric"}
    base.update(over)
    return {k: v for k, v in base.items() if v is not None}


def test_structured_composition():
    r = parse_operation(op(phosphorusPentoxideContent=0, potassiumOxideContent=0))
    assert (r.parcel, r.day, r.product, r.rate_kg_ha) == (P1, date(2027, 2, 10), "NAC 27", 200.0)
    assert r.composition == STRUCTURED and r.n_kg_ha == pytest.approx(54.0)
    assert r.p2o5_kg_ha == 0.0 and r.k2o_kg_ha == 0.0 and not r.organic and r.notices == ()


def test_blank_structured_nutrients_are_filled_from_a_strict_grade():
    r = parse_operation(op(fertilizerComposition="15-15-15", nitrogenContent=15))
    assert r.composition == STRUCTURED
    assert (r.n_pct, r.p2o5_pct, r.k2o_pct) == (15, 15, 15)
    assert "partial_composition" not in r.notices and "composition_mismatch" not in r.notices


def test_blank_nutrients_without_a_grade_are_not_recorded():
    r = parse_operation(op())                      # N only
    assert r.composition == STRUCTURED and r.n_pct == 27
    assert r.p2o5_pct is None and r.k2o_pct is None
    assert r.p2o5_kg_ha is None and "partial_composition" in r.notices


def test_phosphorus_and_potassium_only_leave_nitrogen_unrecorded():
    r = parse_operation(op(nitrogenContent=None, nitrogenForm=None,
                           phosphorusPentoxideContent=15, potassiumOxideContent=15))
    assert r.n_pct is None and r.n_kg_ha is None and "partial_composition" in r.notices


def test_a_grade_that_disagrees_loses_to_the_structured_value():
    r = parse_operation(op(nitrogenContent=15, fertilizerComposition="8-15-15"))
    assert r.n_pct == 15 and (r.p2o5_pct, r.k2o_pct) == (15, 15)
    assert "composition_mismatch" in r.notices


def test_organic_flag_and_status():
    assert parse_operation(op(nitrogenForm=None, organicFertilizer=True)).organic
    assert not parse_operation(op(organicFertilizer=False)).organic
    assert parse_operation(op(status="needs_review")).status == "needs_review"


@pytest.mark.parametrize("text,npk", [("8-15-15", (8, 15, 15)), (" 15 - 15 - 15 ", (15, 15, 15)),
                                      ("0-0-60", (0, 0, 60)), ("7,5-14-14", (7.5, 14, 14))])
def test_strict_npk_text(text, npk):
    r = parse_operation(op(nitrogenContent=None, nitrogenForm=None, fertilizerComposition=text))
    assert r.composition == PARSED and (r.n_pct, r.p2o5_pct, r.k2o_pct) == npk


@pytest.mark.parametrize("text", ["NPK 8-15-15", "8-15", "abono complejo", "60-30-20", ""])
def test_anything_else_is_unreadable(text):
    r = parse_operation(op(nitrogenContent=None, nitrogenForm=None, fertilizerComposition=text))
    assert r.composition == UNREADABLE and r.n_kg_ha is None
    assert "unreadable_composition" in r.notices


def test_dates_rates_and_areas():
    r = parse_operation(op(endedAt=None, startedAt="2027-03-01T08:00:00Z", areaCovered=3.5))
    assert r.day == date(2027, 3, 1) and r.area_ha == 3.5
    undated = parse_operation(op(endedAt=None))
    assert undated.day is None and "undated" in undated.notices
    norate = parse_operation(op(fertilizerRate=None))
    assert norate.rate_kg_ha is None and norate.n_kg_ha is None and "no_rate" in norate.notices
    bad = parse_operation(op(fertilizerRate=float("nan")))
    assert bad.rate_kg_ha is None and "no_rate" in bad.notices


def test_parcel_from_either_relationship_shape():
    assert parse_operation(op(hasAgriParcel=None, refAgriParcel=P1)).parcel == P1
    assert parse_operation(op(hasAgriParcel={"object": P1})).parcel == P1


def test_organic():
    r = parse_operation(op(nitrogenForm="organic", fertilizerRate=20000, nitrogenContent=0.6))
    assert r.organic and r.n_kg_ha == pytest.approx(120.0)


def test_huge_integer_is_not_a_number():
    assert parse_operation(op(fertilizerRate=10**400)).rate_kg_ha is None


def test_instant_becomes_the_madrid_calendar_date():
    r = parse_operation(op(endedAt={"@value": "2026-08-31T23:30:00Z"}))
    assert r.day == date(2026, 9, 1)
    assert parse_operation(op(endedAt={"@value": "2026-08-31"})).day == date(2026, 8, 31)
