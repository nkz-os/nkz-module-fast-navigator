import pytest
from pydantic import ValidationError

from app.inputs.organic import OrganicApplication
from app.plans.applications import (
    ANNEX_V,
    ApplicationIn,
    nutrients,
    split_findings,
    summarize,
)

SLURRY = OrganicApplication("slurry", 30.0, 0.5, 0.2, 0.6)


def mineral(**kw):
    base = {"stage": "pre_plant", "planned_date": "2026-10-20", "kind": "mineral",
            "product_name": "NPK 8-15-15", "n_pct": 8, "p2o5_pct": 15, "k2o_pct": 15,
            "n_form": "ammoniacal", "product_rate_kg_ha": 400, "method": "broadcast",
            "machine": "centrifugal spreader"}
    base.update(kw)
    return ApplicationIn.model_validate(base)


def organic(**kw):
    base = {"stage": "pre_plant", "kind": "organic", "organic_index": 0,
            "product_name": "pig slurry", "method": "band", "machine": "slurry tanker",
            "annex_v": ["A.a"]}
    base.update(kw)
    return ApplicationIn.model_validate(base)


def test_annex_v_catalog_is_complete():
    assert sorted(ANNEX_V) == [f"{p}.{c}" for p in "AB" for c in "abcdefghi"]


def test_mineral_nutrients():
    n = nutrients(mineral(), [])
    assert (n.n_kg_ha, n.p2o5_kg_ha, n.k2o_kg_ha, n.organic) == (32.0, 60.0, 60.0, False)


def test_organic_nutrients_come_from_the_sheet_input():
    n = nutrients(organic(), [SLURRY])
    assert (n.n_kg_ha, n.p2o5_kg_ha, n.k2o_kg_ha, n.organic) == pytest.approx((150.0, 60.0, 180.0, True))


@pytest.mark.parametrize("bad", [
    {"n_pct": 60, "p2o5_pct": 30, "k2o_pct": 20},          # more than 100 %
    {"product_rate_kg_ha": 0},
    {"n_form": None},                                       # N without its form
    {"kind": "potion"},
    {"method": "telepathy"},
    {"machine": ""},
    {"annex_v": ["C.a"]},
    {"annex_v": ["B.a", "B.a"]},
    {"organic_index": 0},                                   # a mineral cannot point at an organic input
])
def test_invalid_mineral_applications(bad):
    with pytest.raises(ValidationError):
        mineral(**bad)


@pytest.mark.parametrize("bad", [{"organic_index": None}, {"n_pct": 5}, {"product_rate_kg_ha": 100}])
def test_invalid_organic_applications(bad):
    with pytest.raises(ValidationError):
        organic(**bad)


def test_summary_totals():
    s = summarize([mineral(), organic()], [SLURRY])
    assert s["mineral_n_kg_ha"] == pytest.approx(32.0)
    assert s["organic_n_total_kg_ha"] == pytest.approx(150.0)
    assert s["p2o5_kg_ha"] == pytest.approx(120.0) and s["k2o_kg_ha"] == pytest.approx(240.0)
    assert len(s["applications"]) == 2


def test_split_findings():
    apps = [mineral(product_rate_kg_ha=1000), mineral(stage="tillering", product_rate_kg_ha=1000)]
    codes = {f["rule_id"] for f in split_findings(apps, [], n_min=60.0, n_max=150.0)}
    assert codes == {"FAST-split-pre_plant_above_n_min", "FAST-split-total_above_n_max"}
    assert all(f["severity"] == "warn" for f in split_findings(apps, [], 60.0, 150.0))
    assert split_findings([mineral(product_rate_kg_ha=1000)], [], 60.0, 150.0) == [{
        "rule_id": "FAST-split-pre_plant_above_n_min", "severity": "warn",
        "params": {"pre_plant_n_kg_ha": 80.0, "n_min_kg_ha": 60.0, "n_max_kg_ha": 150.0,
                   "planned_mineral_n_kg_ha": 80.0}}]


MINERAL = {"stage": "pre_plant", "planned_date": "2026-10-20", "kind": "mineral",
           "product_name": "NPK 8-15-15", "n_pct": 8, "p2o5_pct": 15, "k2o_pct": 15,
           "n_form": "ammoniacal", "product_rate_kg_ha": 400, "method": "broadcast",
           "machine": "centrifugal spreader"}


@pytest.mark.parametrize("extra,ok", [
    ({"n_form": "mixed", "n_pct": 32, "n_ureic_pct": 16}, True),
    ({"n_form": "mixed", "n_pct": 32}, False),                       # mixed must declare it
    ({"n_form": "mixed", "n_pct": 32, "n_ureic_pct": 40}, False),    # more than the N
    ({"n_form": "nitric", "n_pct": 27, "n_ureic_pct": 5}, False),    # only ureic or mixed
    ({"n_form": "ureic", "n_pct": 46, "n_ureic_pct": 46}, True),
    ({"n_form": "mixed", "n_pct": 27, "n_ureic_pct": 0}, True),
])
def test_ureic_n_on_the_label(extra, ok):
    data = {**MINERAL, "p2o5_pct": 0, "k2o_pct": 0, **extra}
    if ok:
        assert ApplicationIn.model_validate(data).n_ureic_pct == extra.get("n_ureic_pct")
    else:
        with pytest.raises(ValueError):
            ApplicationIn.model_validate(data)


def test_organic_applications_take_no_ureic_share():
    with pytest.raises(ValueError):
        ApplicationIn.model_validate({"stage": "pre_plant", "kind": "organic", "organic_index": 0,
                                      "product_name": "pig slurry", "method": "broadcast",
                                      "machine": "spreader", "n_ureic_pct": 1})
