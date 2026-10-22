from datetime import date

from app.rules import BLOCK, INFO, WARN, Finding, Rule, count_blocking, evaluate
from app.rules.context import PlanContext, SheetContext, plan_area


def sheet(key="a", irrigated=False, parcels=(("urn:p1", 4.0),), result_extra=None):
    inputs = {f"parcel.{u}.area_ha": {"value": area, "provenance": "measured"}
              for u, area in parcels}
    inputs["region.nuts"] = {"value": "ES22", "provenance": "declared"}
    return SheetContext(key=key, inputs={"irrigated": irrigated},
                        parcels=tuple({"urn": u, "sigpac": None} for u, _ in parcels),
                        applications=(), result={"inputs": inputs, **(result_extra or {})},
                        summary=None)


def ctx(*sheets, at=date(2027, 1, 10)):
    return PlanContext(campaign=2027, sheets=tuple(sheets), rain=None, vulnerable_zone=None,
                       voluntary_digital_notebook=False, at=at)


def test_rules_apply_only_while_in_force():
    old = Rule("R-old", "x", WARN, date(2020, 1, 1), date(2026, 12, 31), lambda c: [({}, None)])
    new = Rule("R-new", "y", BLOCK, date(2027, 1, 1), None, lambda c: [({"k": 1}, "a")])
    found = evaluate([old, new], ctx(sheet()))
    assert found == [Finding("R-new", BLOCK, "y", {"k": 1}, "a")]
    assert [f.rule_id for f in evaluate([old, new], ctx(sheet(), at=date(2026, 6, 1)))] == ["R-old"]


def test_count_blocking():
    findings = [Finding("a", BLOCK, "c"), Finding("b", WARN, "c"), Finding("c", BLOCK, "c"),
                Finding("d", INFO, "c")]
    assert count_blocking(findings) == 2


def test_finding_to_dict():
    assert Finding("a", WARN, "art. 1", {"x": 1}, "s").to_dict() == {
        "rule_id": "a", "severity": "warn", "citation": "art. 1", "params": {"x": 1},
        "sheet_key": "s"}


def test_sheet_values_and_provenance():
    s = sheet()
    assert s.value("region.nuts") == "ES22" and s.provenance("region.nuts") == "declared"
    assert s.value("nope") is None and s.provenance("nope") is None
    assert SheetContext("b", {}, (), (), None, None).value("region.nuts") is None


def test_plan_area_counts_each_parcel_once():
    a = sheet("a", parcels=(("urn:p1", 4.0), ("urn:p2", 3.0)))
    b = sheet("b", parcels=(("urn:p1", 4.0),))        # double crop on p1
    assert plan_area(ctx(a, b)) == (7.0, True)
    assert plan_area(ctx(sheet(irrigated=True))) == (4.0, False)
