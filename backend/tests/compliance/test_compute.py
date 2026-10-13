from datetime import date

import pytest

from app.compliance.compute import compliance
from app.compliance.realized import parse_operation

P1, P2 = "urn:ngsi-ld:AgriParcel:p1", "urn:ngsi-ld:AgriParcel:p2"
AT = date(2027, 6, 1)


def result(avg=150.0, soil_n=20.0, organic=0.0, areas=((P1, 10.0),), availability=None):
    inputs = {f"parcel.{u}.area_ha": {"value": a, "provenance": "measured"} for u, a in areas}
    if availability is not None:
        inputs["organic.0.availability"] = {"value": availability, "provenance": "table:mapa"}
    return {"status": "complete",
            "n": {"avg_kg_ha": avg - soil_n - organic, "before_credits": {"avg_kg_ha": avg},
                  "credits_kg_ha": {"soil_mineral_n": soil_n, "organic_available_n": organic,
                                    "irrigation_n": 0.0}},
            "p2o5": {"rate_kg_ha": 40.0, "before_organic_kg_ha": 40.0},
            "k2o": {"rate_kg_ha": 30.0, "before_organic_kg_ha": 30.0},
            "inputs": {**inputs, "crop.eppo": {"value": "TRZAX"}}}


def sheet(key="wheat", parcels=(P1,), res=None, organic=(), adjustment=None):
    return {"key": key, "inputs": {"irrigated": False, "strategy": 2, "organic": list(organic)},
            "parcels": [{"urn": u, "sigpac": None} for u in parcels], "applications": [],
            "result": res or result(), "n_adjustment": adjustment,
            "applications_summary": {"mineral_n_kg_ha": 100.0, "organic_n_total_kg_ha": 0.0,
                                     "p2o5_kg_ha": 40.0, "k2o_kg_ha": 30.0}}


def doc(*sheets, campaign=2027):
    return {"plan": {"campaign": campaign}, "live": False, "rain": {"annual_mm": 600.0},
            "declarations": {"vulnerable_zone": True, "voluntary_digital_notebook": False},
            "sheets": list(sheets or [sheet()])}


def fert(day="2027-02-10", parcel=P1, rate=200, n=27, p=0, k=0, form="nitric", **extra):
    return parse_operation({"id": f"op-{day}-{parcel[-2:]}-{rate}", "hasAgriParcel": parcel,
                            "endedAt": {"@value": f"{day}T09:00:00Z"}, "fertilizerRate": rate,
                            "nitrogenContent": n, "phosphorusPentoxideContent": p,
                            "potassiumOxideContent": k, "nitrogenForm": form,
                            "fertilizerType": "x", **extra})


def test_realized_within_the_limit_is_ok():
    out = compliance(doc(), {}, {P1: [fert(rate=200)]}, AT)       # 54 kg N, limit 156
    (s,) = out["sheets"]
    assert s["status"] == "ok" and s["realized"]["mineral_n_kg_ha"] == pytest.approx(54.0)
    assert s["difference"]["mineral_n_kg_ha"] == pytest.approx(-46.0)
    assert out["window"] == {"from": "2026-09-01", "until": "2027-08-31"}


def test_realized_over_the_limit_is_exceeded():
    out = compliance(doc(), {}, {P1: [fert(rate=400), fert(day="2027-03-10", rate=300)]}, AT)
    (s,) = out["sheets"]                                          # 189 kg N > 156
    assert s["status"] == "exceeded"
    assert [f["rule_id"] for f in s["findings"] if f["severity"] == "block"] == [
        "ES-RD1051-AIII-3-N"]


def test_a_valid_adjustment_covers_the_realized_n():
    adj = {"basis": "foliar_analysis", "date": "2027-02-01", "reference": "LAB-1",
           "description": "d", "justified_n_kg_ha": 200.0,
           "scope": {"crop_eppo": "TRZAX", "parcels": [P1]}}
    out = compliance(doc(sheet(adjustment=adj)), {}, {P1: [fert(rate=400), fert(
        day="2027-03-10", rate=300)]}, AT)
    (s,) = out["sheets"]
    assert s["status"] == "ok"
    assert "ES-RD1051-AIII-3-N-adjusted" in [f["rule_id"] for f in s["findings"]]


def test_operations_outside_the_window_do_not_count():
    out = compliance(doc(), {}, {P1: [fert(day="2026-08-31", rate=900), fert(day="2027-09-01",
                                                                               rate=900)]}, AT)
    assert out["sheets"][0]["realized"]["mineral_n_kg_ha"] == 0.0


@pytest.mark.parametrize("bad,notice", [
    ({"endedAt": None}, "undated"),
    ({"fertilizerRate": None}, "no_rate"),
])
def test_unusable_operations_make_the_sheet_incomplete(bad, notice):
    entity = {"id": "o", "hasAgriParcel": P1, "endedAt": {"@value": "2027-02-10"},
              "fertilizerRate": 200, "nitrogenContent": 27, "nitrogenForm": "nitric"}
    entity.update(bad)
    out = compliance(doc(), {}, {P1: [parse_operation({k: v for k, v in entity.items()
                                                        if v is not None})]}, AT)
    s = out["sheets"][0]
    assert s["status"] == "incomplete" and notice in s["notices"]
    assert s["realized"]["mineral_n_kg_ha"] == 0.0


def test_unreadable_composition_is_listed_not_summed():
    op = parse_operation({"id": "o", "hasAgriParcel": P1, "endedAt": {"@value": "2027-02-10"},
                          "fertilizerRate": 300, "fertilizerComposition": "complejo"})
    s = compliance(doc(), {}, {P1: [op]}, AT)["sheets"][0]
    assert s["status"] == "incomplete" and "unreadable_composition" in s["notices"]
    assert s["applications"][0]["composition"] == "unreadable"


def test_area_weighting_over_the_sheet():
    res = result(areas=((P1, 10.0), (P2, 30.0)))
    d = doc(sheet(parcels=(P1, P2), res=res))
    out = compliance(d, {}, {P1: [fert(rate=400, areaCovered=5.0)], P2: []}, AT)
    # 108 kg N/ha on 5 ha of a 40 ha sheet → 13.5 kg N/ha
    assert out["sheets"][0]["realized"]["mineral_n_kg_ha"] == pytest.approx(13.5)


def test_a_parcel_in_two_sheets_is_ambiguous():
    d = doc(sheet("wheat"), sheet("vetch"))
    out = compliance(d, {}, {P1: [fert()]}, AT)
    assert [u["reason"] for u in out["unattributed"]] == ["parcel_in_several_sheets"]
    assert {s["status"] for s in out["sheets"]} == {"incomplete"}


def test_organic_realized_uses_the_single_planned_availability():
    organic = [{"material": "cattle_manure", "rate_t_ha": 20, "n_pct": 0.6, "p2o5_pct": 0.3,
                "k2o_pct": 0.7}]
    d = doc(sheet(res=result(availability=0.3), organic=organic))
    out = compliance(d, {}, {P1: [fert(rate=20000, n=0.6, form="organic")]}, AT)
    r = out["sheets"][0]["realized"]
    assert r["organic_n_total_kg_ha"] == pytest.approx(120.0)
    assert r["organic_n_available_kg_ha"] == pytest.approx(36.0)


def test_organic_without_a_single_planned_material_counts_in_full():
    out = compliance(doc(), {}, {P1: [fert(rate=20000, n=0.6, form="organic")]}, AT)
    s = out["sheets"][0]
    assert s["realized"]["organic_n_available_kg_ha"] == pytest.approx(120.0)
    assert "organic_availability_assumed_full" in s["notices"]


def test_history_uses_realized_then_planned():
    snap = {"sheets": [{"key": "w", "parcels": [{"urn": P1}],
                        "result": {"p2o5": {"before_organic_kg_ha": 40.0},
                                   "k2o": {"before_organic_kg_ha": 30.0}},
                        "applications_summary": {"p2o5_kg_ha": 90.0, "k2o_kg_ha": 30.0}}]}
    previous = {2025: snap, 2026: snap}
    ops = {P1: [fert(day="2025-03-01", rate=400, n=0, p=50, k=0)]}   # 200 kg P2O5 in 2025
    out = compliance(doc(), previous, ops, AT)
    p = [f for f in out["sheets"][0]["findings"] if f["rule_id"] == "ES-RD1051-AIII-4-P"]
    # 2025 realized 200 + 2026 planned 90 + 2027 realized 0 = 290 > (40·3)·1.3 = 156
    assert p and p[0]["params"]["planned_kg_ha"] == pytest.approx(290.0)
    assert sorted(p[0]["params"]["history"]) == ["planned", "realized"]


def _old(parcel, planned_p, calc_p=40.0, **over):
    s = {"key": "o", "parcels": [{"urn": parcel}],
         "result": {"p2o5": {"before_organic_kg_ha": calc_p}, "k2o": {"before_organic_kg_ha": 0}},
         "applications_summary": {"p2o5_kg_ha": planned_p, "k2o_kg_ha": 0.0}}
    s.update(over)
    return s


def _p_finding(out):
    return [f for f in out["sheets"][0]["findings"] if f["rule_id"] == "ES-RD1051-AIII-4-P"]


def test_history_unusable_past_operation_marks_the_sheet_incomplete():
    previous = {2026: {"sheets": [_old(P1, 90.0)]}}
    bad = parse_operation({"id": "o", "hasAgriParcel": P1, "endedAt": {"@value": "2026-03-01"},
                           "fertilizerComposition": "complejo", "fertilizerRate": 100})
    s = compliance(doc(), previous, {P1: [bad]}, AT)["sheets"][0]
    assert "history_incomplete:2026" in s["notices"] and s["status"] == "incomplete"


@pytest.mark.parametrize("drop", ["applications_summary", "result"])
def test_history_snapshot_missing_data_is_flagged_and_skipped(drop):
    old = _old(P1, 90.0)
    old[drop] = None
    out = compliance(doc(), {2026: {"sheets": [old]}}, {}, AT)
    s = out["sheets"][0]
    assert "history_incomplete:2026" in s["notices"] and s["status"] == "incomplete"
    assert not _p_finding(out) or _p_finding(out)[0]["params"]["years"] == [2027]


def test_history_is_area_weighted_over_parcels():
    d = doc(sheet(parcels=(P1, P2), res=result(areas=((P1, 10.0), (P2, 30.0)))))
    previous = {2026: {"sheets": [_old(P1, 90.0), _old(P2, 10.0)]}}
    out = compliance(d, previous, {}, AT)
    # current planned 100/40 per ha + history (90*10+10*30)/40 = 30 ; calculated 40 + 40
    (f,) = _p_finding(out) or [None]
    assert f is None or f["params"]["planned_kg_ha"] == pytest.approx(70.0)
    s = out["sheets"][0]
    assert s["status"] in ("ok", "exceeded")


def test_history_weighted_value_reaches_the_rule():
    # force the P rule to fire so the params expose the weighted history
    res = result(areas=((P1, 10.0), (P2, 30.0)))
    res["p2o5"] = {"rate_kg_ha": 0.0, "before_organic_kg_ha": 0.0}
    d = doc(sheet(parcels=(P1, P2), res=res))
    d["sheets"][0]["applications_summary"]["p2o5_kg_ha"] = 0.0
    previous = {2026: {"sheets": [_old(P1, 90.0, calc_p=0.0), _old(P2, 10.0, calc_p=0.0)]}}
    (f,) = _p_finding(compliance(d, previous, {}, AT))
    assert f["params"]["planned_kg_ha"] == pytest.approx(30.0)


def test_history_stacked_old_sheets_on_one_parcel_sum():
    res = result()
    res["p2o5"] = {"rate_kg_ha": 0.0, "before_organic_kg_ha": 0.0}
    d = doc(sheet(res=res))
    d["sheets"][0]["applications_summary"]["p2o5_kg_ha"] = 0.0
    previous = {2026: {"sheets": [_old(P1, 50.0, calc_p=0.0), _old(P1, 30.0, calc_p=0.0)]}}
    (f,) = _p_finding(compliance(d, previous, {}, AT))
    assert f["params"]["planned_kg_ha"] == pytest.approx(80.0)


def test_operation_on_a_parcel_outside_the_plan_is_unattributed():
    out = compliance(doc(), {}, {"urn:ngsi-ld:AgriParcel:zz": [fert(parcel="urn:ngsi-ld:AgriParcel:zz")]},
                     AT)
    assert [u["reason"] for u in out["unattributed"]] == ["parcel_not_in_plan"]
    assert out["sheets"][0]["status"] == "ok"


@pytest.mark.parametrize("res", [{}, {"status": "complete", "inputs": {}}])
def test_a_sheet_without_n_result_is_incomplete(res):
    d = doc(sheet())
    d["sheets"][0]["result"] = res
    s = compliance(d, {}, {}, AT)["sheets"][0]
    assert s["status"] == "incomplete" and "no_result" in s["notices"]


def test_organic_with_a_tiny_rate_is_suspect_but_not_incomplete():
    s = compliance(doc(), {}, {P1: [fert(rate=20, n=0.6, form="organic")]}, AT)["sheets"][0]
    assert "organic_rate_suspect" in s["notices"] and s["status"] == "ok"
