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


def test_organic_with_a_tiny_rate_is_suspect_and_incomplete():
    s = compliance(doc(), {}, {P1: [fert(rate=20, n=0.6, form="organic")]}, AT)["sheets"][0]
    assert "organic_rate_suspect" in s["notices"] and s["status"] == "incomplete"


def _raw(**over):
    base = {"id": "o", "hasAgriParcel": P1, "endedAt": {"@value": "2027-02-10T09:00:00Z"},
            "fertilizerType": "x", "fertilizerRate": 1000, "status": "completed"}
    base.update(over)
    return parse_operation(base)


def _one(ops, d=None, previous=None):
    return compliance(d or doc(), previous or {}, {P1: ops}, AT)["sheets"][0]


# C3
def test_partial_composition_makes_the_sheet_incomplete_and_sums_only_what_is_known():
    s = _one([_raw(nitrogenContent=15, nitrogenForm="mixed")])
    assert "partial_composition" in s["notices"] and s["status"] == "incomplete"
    assert s["realized"]["mineral_n_kg_ha"] == pytest.approx(150.0)
    assert s["realized"]["p2o5_kg_ha"] == 0.0


def test_partial_composition_completed_from_the_grade_is_complete():
    s = _one([_raw(nitrogenContent=15, nitrogenForm="mixed", fertilizerComposition="15-15-15",
                   fertilizerRate=100)])
    assert s["status"] == "ok" and s["realized"]["p2o5_kg_ha"] == pytest.approx(15.0)


def test_phosphorus_potassium_only_does_not_sum_nitrogen():
    s = _one([_raw(phosphorusPentoxideContent=15,
                   potassiumOxideContent=15)])
    assert "partial_composition" in s["notices"] and s["realized"]["mineral_n_kg_ha"] == 0.0
    assert s["realized"]["p2o5_kg_ha"] == pytest.approx(150.0)


# C4
def test_organic_flag_without_nitrogen_form_counts_as_organic():
    s = _one([_raw(fertilizerRate=20000, nitrogenContent=0.6, phosphorusPentoxideContent=0,
                   potassiumOxideContent=0, organicFertilizer=True)])
    assert s["realized"]["organic_n_total_kg_ha"] == pytest.approx(120.0)
    assert s["realized"]["mineral_n_kg_ha"] == 0.0


def test_organic_availability_from_the_single_planned_material_is_noted():
    organic = [{"material": "cattle_manure", "rate_t_ha": 20, "n_pct": 0.6, "p2o5_pct": 0.3,
                "k2o_pct": 0.7}]
    d = doc(sheet(res=result(availability=0.3), organic=organic))
    s = _one([fert(rate=20000, n=0.6, form="organic")], d)
    assert "organic_availability_from_plan" in s["notices"]
    assert "organic_availability_assumed_full" not in s["notices"]


# C5
@pytest.mark.parametrize("status", ["incomplete", "needs_review"])
def test_a_started_fertilization_is_listed_flagged_and_not_summed(status):
    s = _one([_raw(status=status, nitrogenContent=27, nitrogenForm="nitric",
                   phosphorusPentoxideContent=0, potassiumOxideContent=0)])
    assert s["status"] == "incomplete" and "operation_not_completed" in s["notices"]
    assert s["realized"]["mineral_n_kg_ha"] == 0.0
    assert [a["operation"] for a in s["applications"]] == ["o"]


def test_a_started_fertilization_in_a_past_campaign_flags_the_history():
    previous = {2026: {"sheets": [_old(P1, 90.0)]}}
    bad = _raw(status="incomplete", endedAt={"@value": "2026-03-01"}, nitrogenContent=27,
               phosphorusPentoxideContent=0, potassiumOxideContent=0)
    s = _one([bad], previous=previous)
    assert "history_incomplete:2026" in s["notices"]


# C6
def test_window_starts_at_the_earliest_planned_date():
    d = doc()
    d["sheets"][0]["applications"] = [{"planned_date": "2026-08-20"}]
    out = compliance(d, {}, {P1: [_raw(endedAt={"@value": "2026-08-20T09:00:00Z"},
                                       nitrogenContent=27, nitrogenForm="nitric",
                                       phosphorusPentoxideContent=0,
                                       potassiumOxideContent=0, fertilizerRate=600)]}, AT)
    s = out["sheets"][0]
    assert out["window"]["from"] == "2026-08-20"
    assert s["realized"]["mineral_n_kg_ha"] == pytest.approx(162.0)
    assert "operation_in_extended_window" in s["notices"]


def test_an_operation_inside_the_standard_season_has_no_extended_notice():
    d = doc()
    d["sheets"][0]["applications"] = [{"planned_date": "2026-08-20"}]
    s = _one([fert()], d)
    assert "operation_in_extended_window" not in s["notices"]


# C7
def _high_p_result():
    res = result()
    res["p2o5"] = {"rate_kg_ha": 40.0, "before_organic_kg_ha": 40.0}
    return res


def test_one_high_p_year_without_history_is_at_risk():
    s = _one([fert(rate=400, n=0, p=15)])                 # 60 kg P2O5 vs 40 * 1.3
    assert [f["rule_id"] for f in s["findings"] if f["severity"] == "warn"] == [
        "ES-RD1051-AIII-4-P"]
    assert s["status"] == "at_risk"


def test_four_full_years_over_the_limit_is_exceeded():
    previous = {y: {"sheets": [_old(P1, 90.0)]} for y in range(2023, 2027)}
    s = _one([fert(rate=400, n=0, p=15)], previous=previous)
    assert s["status"] == "exceeded"


# minors
def test_unknown_area_gives_unknown_not_zero():
    res = result()
    res["inputs"] = {"crop.eppo": {"value": "TRZAX"}}
    s = _one([fert()], doc(sheet(res=res)))
    assert "parcel_area_unknown" in s["notices"] and s["status"] == "incomplete"
    assert all(v is None for v in s["realized"].values())
    assert all(v is None for v in s["difference"].values())


def test_operation_parcel_differing_from_the_queried_urn_does_not_raise():
    op = parse_operation({"id": "o", "hasAgriParcel": [P1, P2],
                          "endedAt": {"@value": "2027-02-10"}, "fertilizerRate": 200,
                          "nitrogenContent": 27, "phosphorusPentoxideContent": 0,
                          "potassiumOxideContent": 0, "nitrogenForm": "nitric"})
    other = parse_operation({"id": "o2", "hasAgriParcel": P2, "endedAt": {"@value": "2027-02-10"},
                             "fertilizerRate": 200, "nitrogenContent": 27,
                             "phosphorusPentoxideContent": 0, "potassiumOxideContent": 0,
                             "nitrogenForm": "nitric"})
    s = _one([op, other])
    assert s["realized"]["mineral_n_kg_ha"] == pytest.approx(108.0)


@pytest.mark.parametrize("drop", ["p2o5", "k2o"])
def test_a_result_without_p_or_k_is_incomplete(drop):
    res = result()
    del res[drop]
    s = _one([], doc(sheet(res=res)))
    assert "no_result" in s["notices"] and s["status"] == "incomplete"


def test_the_response_says_when_it_was_judged():
    assert compliance(doc(), {}, {P1: []}, AT)["judged_at"] == "2027-06-01"
