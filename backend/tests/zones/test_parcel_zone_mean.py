"""The parcel soil of a zone campaign: the area-weighted mean of the zones' own samples."""
from dataclasses import replace
from datetime import date

import pytest

from app.calc.assemble import SheetRequest, assemble
from app.calc.sheet import COMPLETE, calculate
from app.inputs.soil import build_soil
from app.zones.read import ZoneRead, ZoningRead
from app.zones.soil import parcel_zone_mean
from tests.fakes import URN, FakeSources, complete_data
from tests.zones.test_api_zone_doses import RUN, zone_set

ZA = "urn:ngsi-ld:AgriManagementZone:p:A"
ZB = "urn:ngsi-ld:AgriManagementZone:p:B"
OUTER = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
HOLE = [[4, 4], [4, 6], [6, 6], [6, 4], [4, 4]]
INNER = [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]
DAY = "2026-10-05"       # after the zoning date


def nested(area_a=8.0, area_b=2.0, date_="2026-10-01"):
    """A is the outer ring minus B (entity area 8 ha, its outer ring would say 10)."""
    zones = (ZoneRead(ZA, "A", 0, {"type": "Polygon", "coordinates": [OUTER, HOLE]},
                      area_a, None, ()),
             ZoneRead(ZB, "B", 1, {"type": "Polygon", "coordinates": [INNER]}, area_b, None, ()))
    return ZoningRead("run-x", "manual", None, date_, zones)


def sample(id_, lon, lat, day=DAY, **hz):
    return {"id": id_, "samplingDate": day, "location": {"lon": lon, "lat": lat},
            "horizons": [dict({"depthFrom": 0, "depthTo": 30}, **hz)]}


IN_A, IN_B = (1, 1), (5, 5)


def horizon(m):
    return m.analysis["horizons"][0]


def test_the_mean_is_weighted_by_the_zone_area_not_the_outer_ring():
    m = parcel_zone_mean([
        sample("a", *IN_A, sand=40.0, clay=20.0, ph=7.0, organicMatter=1.0,
               phosphorusAvailable=10.0, phosphorusMethod="olsen",
               potassiumExchangeable=100.0, potassiumMethod="ammonium_acetate"),
        sample("b", *IN_B, sand=60.0, clay=30.0, ph=8.0, organicMatter=2.0,
               phosphorusAvailable=20.0, phosphorusMethod="olsen",
               potassiumExchangeable=200.0, potassiumMethod="ammonium_acetate")], nested())
    h = horizon(m)
    assert h["sand"] == pytest.approx(44.0) and h["clay"] == pytest.approx(22.0)
    assert h["ph"] == pytest.approx(7.2) and h["organicMatter"] == pytest.approx(1.2)
    assert h["phosphorusAvailable"] == pytest.approx(12.0)   # ring areas (100, 4) would give ~10.4
    assert h["potassiumExchangeable"] == pytest.approx(120.0)
    assert m.analysis["id"] == "zone-mean:run-x" and m.analysis["samplingDate"] == DAY
    assert (m.zones_sampled, m.zones_total, m.area_pct) == (2, 2, 100.0)


def test_a_field_present_in_only_some_zones_is_the_mean_over_those():
    m = parcel_zone_mean([
        sample("a", *IN_A, sand=40.0, clay=20.0, phosphorusAvailable=10.0, phosphorusMethod="olsen"),
        sample("b", *IN_B, sand=60.0, clay=30.0)], nested())
    h = horizon(m)
    assert h["sand"] == pytest.approx(44.0)
    assert h["phosphorusAvailable"] == pytest.approx(10.0)   # only zone A has P
    assert "potassiumExchangeable" not in h and "ph" not in h


def test_sand_and_clay_are_one_reading_taken_only_where_both_are_present():
    m = parcel_zone_mean([sample("a", *IN_A, sand=40.0, clay=20.0, ph=7.0),
                          sample("b", *IN_B, sand=60.0, ph=8.0)], nested())
    h = horizon(m)
    assert h["sand"] == pytest.approx(40.0) and h["clay"] == pytest.approx(20.0)   # zone A only
    assert h["ph"] == pytest.approx(7.2)
    none = parcel_zone_mean([sample("a", *IN_A, sand=40.0, ph=7.0),
                             sample("b", *IN_B, clay=30.0, ph=8.0)], nested())
    assert "sand" not in horizon(none) and "clay" not in horizon(none)


def test_samples_before_the_zoning_date_are_ignored():
    old = sample("old", *IN_B, day="2026-09-01", sand=99.0, clay=1.0)
    m = parcel_zone_mean([sample("a", *IN_A, sand=40.0, clay=20.0),
                          sample("b", *IN_B, sand=60.0, clay=30.0), old], nested())
    assert horizon(m)["sand"] == pytest.approx(44.0)
    assert parcel_zone_mean([sample("a", *IN_A, sand=40.0), old], nested()) is None


def test_a_zone_uses_the_mean_of_its_newest_date_only():
    m = parcel_zone_mean([sample("a1", *IN_A, day="2026-10-02", sand=10.0, clay=10.0),
                          sample("a2", *IN_A, day="2026-10-06", sand=40.0, clay=20.0),
                          sample("a3", *IN_A, day="2026-10-06", sand=50.0, clay=20.0),
                          sample("b", *IN_B, day="2026-10-06", sand=45.0, clay=20.0)], nested(area_a=1.0, area_b=1.0))
    assert horizon(m)["sand"] == pytest.approx(45.0) and m.analysis["samplingDate"] == "2026-10-06"


def test_a_zone_without_a_usable_area_cannot_make_a_campaign_and_is_not_counted():
    two = [sample("a", *IN_A, sand=40.0, clay=20.0), sample("b", *IN_B, sand=60.0, clay=30.0)]
    assert parcel_zone_mean(two, nested(area_b=None)) is None      # one weighted zone only
    z = nested()
    bare = ZoneRead("urn:ngsi-ld:AgriManagementZone:p:C", "C", 2,
                    {"type": "Polygon", "coordinates": [[[20, 20], [21, 20], [21, 21], [20, 21], [20, 20]]]},
                    None, None, ())
    m = parcel_zone_mean([*two, sample("c", 20.5, 20.5, sand=1.0, clay=1.0)],
                         replace(z, zones=(*z.zones, bare)))
    assert horizon(m)["sand"] == pytest.approx(44.0) and (m.zones_sampled, m.zones_total) == (2, 2)


def test_no_campaign_without_zone_samples_or_without_a_zoning_date():
    assert parcel_zone_mean([], nested()) is None
    assert parcel_zone_mean([sample("far", 50, 50, sand=1.0)], nested()) is None
    two = [sample("a", *IN_A, sand=40.0), sample("b", *IN_B, sand=60.0)]
    assert parcel_zone_mean(two, nested(date_=None)) is None


def test_a_campaign_needs_two_different_zones_with_samples_of_the_same_day():
    one = [sample("a", *IN_A, sand=40.0, clay=20.0)]
    assert parcel_zone_mean(one, nested()) is None                  # one located analysis
    two_in_a = [*one, sample("a2", *IN_A, sand=50.0, clay=20.0)]
    assert parcel_zone_mean(two_in_a, nested()) is None             # same zone twice
    other_day = [*one, sample("b", *IN_B, day="2026-10-07", sand=60.0, clay=30.0)]
    assert parcel_zone_mean(other_day, nested()) is None            # two zones, two days
    same_day = [*one, sample("b", *IN_B, sand=60.0, clay=30.0)]
    assert parcel_zone_mean(same_day, nested()) is not None


def test_unusable_zone_readings_are_reported_not_hidden():
    bad = sample("a", *IN_A, sand=40.0, clay=20.0, phosphorusAvailable=10.0, phosphorusMethod="x")
    m = parcel_zone_mean([bad, sample("b", *IN_B, sand=60.0, clay=30.0)], nested())
    assert m.unusable == ("soil.p_olsen_mg_kg",) and "phosphorusAvailable" not in horizon(m)
    assert [n.code for n in m.notices] == ["soil_p_method_unsupported"]


# ---- build_soil ----------------------------------------------------------------------------

H = {"depthFrom": 0, "depthTo": 30, "sand": 40.0, "clay": 25.0, "ph": 7.8, "organicMatter": 1.9,
     "phosphorusAvailable": 14.0, "phosphorusMethod": "olsen",
     "potassiumExchangeable": 220.0, "potassiumMethod": "ammonium_acetate"}
LAB = {"id": "a1", "samplingDate": "2026-09-01", "horizons": [H]}
MEAN = {"id": "zone-mean:r", "samplingDate": DAY,
        "horizons": [dict(H, phosphorusAvailable=7.0, sand=50.0)]}


def test_without_a_zone_mean_build_soil_is_what_it_was():
    s = build_soil([LAB], [], None, None, {}, None)
    assert s == build_soil([LAB], [], None, None, {})
    assert s.analysis_id == "a1" and s.values["p_olsen_mg_kg"].source == "soil:lab-analysis:a1"


def test_the_zone_mean_is_the_parcel_soil_with_its_own_source():
    s = build_soil([LAB], [], None, None, {}, MEAN)
    assert (s.analysis_id, s.sampling_date) == ("zone-mean:r", DAY)
    p = s.values["p_olsen_mg_kg"]
    assert (p.value, p.provenance, p.source) == (7.0, "measured", "soil:zone-mean:r")
    assert s.values["sand_pct"].value == 50.0


def test_an_explicit_analysis_beats_the_zone_mean():
    s = build_soil([LAB], [], "a1", None, {}, MEAN)
    assert s == build_soil([LAB], [], "a1", None, {})


# ---- assemble ------------------------------------------------------------------------------

TODAY = date(2026, 10, 13)
REQ = SheetRequest(campaign=2027, parcel_ids=(URN,), tillage=True, irrigated=False,
                   rotation_years=4)


def pk(id_, p, k, link=None, day=None):
    from app.plans.clock import legal_today
    a = {"id": id_, "samplingDate": day or legal_today().isoformat(), "horizons": [
        {"depthFrom": 0, "depthTo": 30, "sand": 40.0, "clay": 25.0, "ph": 7.8,
         "organicMatter": 1.9, "phosphorusAvailable": p, "phosphorusMethod": "olsen",
         "potassiumExchangeable": k, "potassiumMethod": "ammonium_acetate"}]}
    if link:
        a["hasAgriManagementZone"] = link
    return a


def campaign_data(areas=(1.0, 3.0)):
    d = complete_data()
    d["zones"] = {URN: zone_set([0.4, 0.6])}
    for e, area in zip(d["zones"][URN], areas):
        e["areaHa"] = area
    z = [e["id"] for e in d["zones"][URN]]
    d["analyses"][URN] += [pk("z0", 4.0, 90.0, z[0]), pk("z1", 8.0, 110.0, z[1])]
    return d


async def test_a_zone_campaign_makes_the_parcel_soil_the_weighted_mean():
    src = FakeSources(**campaign_data())
    a = await assemble(REQ, src, TODAY)
    s = a.soil
    assert s.analysis_id == f"zone-mean:{RUN}"
    p, k = s.values["p_olsen_mg_kg"], s.values["k_mg_kg"]
    assert p.value == pytest.approx(7.0) and k.value == pytest.approx(105.0)
    assert p.provenance == "measured" and p.source == f"soil:zone-mean:{RUN}"
    note = next(n for n in a.notices if n.code == "parcel_soil_from_zones")
    assert note.params == {"zones_sampled": 2, "zones_total": 2, "area_pct": 100.0}


async def test_an_explicit_soil_analysis_keeps_the_choice_and_skips_the_zones():
    src = FakeSources(**campaign_data())
    a = await assemble(replace(REQ, soil_analysis_id="a1"), src, TODAY)
    assert a.soil.analysis_id == "a1"
    assert not [n for n in a.notices if n.code == "parcel_soil_from_zones"]
    assert not [c for c in src.calls if c[0] == "zone_entities"]


async def test_without_a_zone_campaign_the_newest_analysis_is_still_chosen():
    d = campaign_data()
    d["analyses"][URN] = d["analyses"][URN][:1]          # only the parcel analysis a1
    a = await assemble(REQ, FakeSources(**d), TODAY)
    assert a.soil.analysis_id == "a1"
    assert not [n for n in a.notices if n.code == "parcel_soil_from_zones"]
    d["zones"] = {}
    assert (await assemble(REQ, FakeSources(**d), TODAY)).soil == a.soil


async def test_unreadable_zones_keep_the_newest_analysis_and_say_so():
    d = campaign_data()
    d["fail"] = {"zone_entities": RuntimeError("broker down")}
    a = await assemble(REQ, FakeSources(**d), TODAY)
    assert a.soil.analysis_id != f"zone-mean:{RUN}"
    assert [n.code for n in a.notices if n.code.startswith("parcel_soil")] == [
        "parcel_soil_zones_unavailable"]


def test_a_field_no_zone_has_comes_from_the_parcel_analysis():
    only_pk = {"id": "zone-mean:r", "samplingDate": DAY, "horizons": [
        {"depthFrom": 0, "depthTo": 30, "phosphorusAvailable": 7.0, "phosphorusMethod": "olsen",
         "potassiumExchangeable": 105.0, "potassiumMethod": "ammonium_acetate"}]}
    s = build_soil([LAB], [], None, None, {}, only_pk)
    assert s.analysis_id == "zone-mean:r"
    assert (s.values["p_olsen_mg_kg"].value, s.values["p_olsen_mg_kg"].source) == (7.0, "soil:zone-mean:r")
    assert s.values["k_mg_kg"].value == 105.0
    for name, v in (("sand_pct", 40.0), ("clay_pct", 25.0), ("ph", 7.8), ("organic_matter_pct", 1.9)):
        assert s.values[name].value == v and s.values[name].source == "soil:lab-analysis:a1"
    assert s.values["sand_pct"].provenance == "measured"
    assert set(s.parcel_fallback_fields) == {"soil.sand_pct", "soil.clay_pct", "soil.ph",
                                             "soil.organic_matter_pct"}
    assert (s.parcel_fallback_id, s.parcel_fallback_date) == ("a1", "2026-09-01")


def test_a_zone_mean_covering_everything_has_no_fallback():
    assert build_soil([LAB], [], None, None, {}, MEAN).parcel_fallback_fields == ()


async def test_assemble_takes_pk_from_the_zones_and_the_rest_from_the_parcel_analysis():
    d = campaign_data()
    for a in d["analyses"][URN]:
        if a["id"] in ("z0", "z1"):
            for k in ("sand", "clay", "ph", "organicMatter"):
                del a["horizons"][0][k]
    a = await assemble(REQ, FakeSources(**d), TODAY)
    v = a.soil.values
    assert v["p_olsen_mg_kg"].value == pytest.approx(7.0)
    assert v["p_olsen_mg_kg"].source == f"soil:zone-mean:{RUN}"
    assert v["sand_pct"].source == "soil:lab-analysis:a1" and v["sand_pct"].value == 40.0
    codes = {n.code: n.params for n in a.notices}
    assert set(codes["parcel_soil_fields_from_parcel"]["fields"]) == {
        "soil.sand_pct", "soil.clay_pct", "soil.ph", "soil.organic_matter_pct"}
    assert calculate(a).status == COMPLETE


# ---- owner rule, fallback provenance, unusable readings --------------------------------------

def test_a_single_post_zoning_located_analysis_is_not_a_campaign():
    d = complete_data()
    d["zones"] = {URN: zone_set([0.4, 0.6])}
    d["analyses"][URN] += [pk("z0", 4.0, 90.0, d["zones"][URN][0]["id"])]
    import asyncio
    a = asyncio.run(assemble(REQ, FakeSources(**d), TODAY))
    base = complete_data()
    b = asyncio.run(assemble(REQ, FakeSources(**base), TODAY))
    assert a.soil.analysis_id == "z0"        # today: the newest analysis with fertility data
    assert not [n for n in a.notices if n.code.startswith("parcel_soil")]
    assert b.soil.analysis_id == "a1"


async def test_two_zones_on_different_days_are_not_a_campaign():
    from datetime import timedelta

    from app.plans.clock import legal_today
    d = campaign_data()
    d["analyses"][URN][-1]["samplingDate"] = (legal_today() + timedelta(days=1)).isoformat()
    a = await assemble(REQ, FakeSources(**d), TODAY)
    assert a.soil.analysis_id != f"zone-mean:{RUN}"
    assert not [n for n in a.notices if n.code.startswith("parcel_soil")]


async def test_a_failing_zone_mean_keeps_the_newest_analysis_and_says_so(monkeypatch):
    import app.calc.assemble as mod

    def boom(*a, **k):
        raise ValueError("broken zone geometry")
    monkeypatch.setattr(mod, "parcel_zone_mean", boom)
    a = await assemble(REQ, FakeSources(**campaign_data()), TODAY)
    assert a.soil.analysis_id != f"zone-mean:{RUN}"
    assert [n.code for n in a.notices if n.code.startswith("parcel_soil")] == [
        "parcel_soil_zones_unavailable"]


async def test_a_broken_zone_geometry_is_survived():
    d = campaign_data()
    d["zones"][URN][0]["location"] = {"type": "Polygon", "coordinates": "broken"}
    d["analyses"][URN][-1].pop("hasAgriManagementZone")
    d["analyses"][URN][-1]["location"] = {"lat": 0.5, "lon": 0.5}
    a = await assemble(REQ, FakeSources(**d), TODAY)
    assert a.soil.analysis_id is not None          # either today's choice or a mean, never a crash


async def test_the_fallback_analysis_is_recorded_for_the_plan():
    d = campaign_data()
    for a in d["analyses"][URN]:
        if a["id"] in ("z0", "z1"):
            for k in ("sand", "clay", "ph", "organicMatter"):
                del a["horizons"][0][k]
        else:
            a["samplingDate"] = "2015-03-01"
    a = await assemble(REQ, FakeSources(**d), TODAY)
    assert a.soil.parcel_fallback_id == "a1" and a.soil.parcel_fallback_date == "2015-03-01"
    item = calculate(a).inputs["soil.analysis_id"]
    assert item["parcel_fallback"] == {
        "id": "a1", "sampling_date": "2015-03-01",
        "fields": ["soil.sand_pct", "soil.clay_pct", "soil.ph", "soil.organic_matter_pct"]}


async def test_unusable_zone_readings_keep_their_notices_and_are_not_called_unmeasured():
    d = campaign_data()
    for a in d["analyses"][URN]:
        if a["id"] == "z0":
            a["horizons"][0]["phosphorusMethod"] = "unknown-method"
    a = await assemble(REQ, FakeSources(**d), TODAY)
    codes = [n.code for n in a.notices]
    assert "soil_p_method_unsupported" in codes
    # Zone 1 still gives P, so P stays a zone value and nothing is taken from the parcel.
    assert "parcel_soil_fields_from_parcel" not in codes


async def test_unusable_in_every_zone_p_falls_to_the_parcel_but_is_not_listed():
    d = campaign_data()
    for a in d["analyses"][URN]:
        if a["id"] in ("z0", "z1"):
            a["horizons"][0]["phosphorusMethod"] = "unknown-method"
    a = await assemble(REQ, FakeSources(**d), TODAY)
    codes = {n.code: n.params for n in a.notices}
    assert "soil_p_method_unsupported" in codes
    assert a.soil.values["p_olsen_mg_kg"].source == "soil:lab-analysis:a1"
    assert "soil.p_olsen_mg_kg" in a.soil.parcel_fallback_fields       # recorded for the plan
    assert "parcel_soil_fields_from_parcel" not in codes or \
        "soil.p_olsen_mg_kg" not in codes["parcel_soil_fields_from_parcel"]["fields"]


def test_bulk_density_is_listed_only_when_used():
    bd = dict(H, bulkDensity=1.3)
    lab = {"id": "a1", "samplingDate": "2015-03-01", "horizons": [bd]}
    only_pk = {"id": "zone-mean:r", "samplingDate": DAY, "horizons": [
        {"depthFrom": 0, "depthTo": 30, "phosphorusAvailable": 7.0, "phosphorusMethod": "olsen"}]}
    used = build_soil([lab], [], None, None, {}, only_pk)
    assert "soil.bulk_density_g_cm3" in used.parcel_fallback_fields
    from app.inputs.provenance import Override
    ov = {"soil.bulk_density_g_cm3": Override("soil.bulk_density_g_cm3", 1.1, "x", "u",
                                              "2026-10-13T10:00:00Z")}
    over = build_soil([lab], [], None, None, ov, only_pk)
    assert "soil.bulk_density_g_cm3" not in over.parcel_fallback_fields
    out_of_range = {"id": "a1", "samplingDate": "2015-03-01", "horizons": [dict(H, bulkDensity=9.0)]}
    assert "soil.bulk_density_g_cm3" not in build_soil(
        [out_of_range], [], None, None, {}, only_pk).parcel_fallback_fields


async def test_located_samples_with_an_undated_zoning_are_flagged():
    d = campaign_data()
    for e in d["zones"][URN]:
        del e["dateZoned"]
    a = await assemble(REQ, FakeSources(**d), TODAY)
    assert "zone_soil_no_zoning_date" in [n.code for n in a.notices]
    assert a.soil.analysis_id != f"zone-mean:{RUN}"
