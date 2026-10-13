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


def test_missing_structured_nutrients_count_as_zero():
    r = parse_operation(op())
    assert r.p2o5_pct == 0.0 and r.k2o_pct == 0.0


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
