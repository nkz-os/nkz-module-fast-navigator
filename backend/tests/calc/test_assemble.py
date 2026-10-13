from dataclasses import replace
from datetime import date

import pytest

from app.calc.assemble import ParcelNotFound, SheetRequest, assemble, fetch_rain_normal
from app.calc.sheet import COMPLETE, calculate
from app.inputs.provenance import Notice
from app.sources.errors import SourceUnavailable
from tests.fakes import URN, FakeSources, complete_data

TODAY = date(2026, 10, 13)
REQ = SheetRequest(campaign=2027, parcel_ids=(URN,), tillage=True, irrigated=False,
                   rotation_years=4)


async def test_a_complete_sheet_from_the_sources():
    src = FakeSources(**complete_data())
    a = await assemble(REQ, src, TODAY)
    r = calculate(a)
    assert r.status == COMPLETE, r.missing
    assert a.yield_target.basis == "zone" and a.region.value == "ES22"
    assert a.region.provenance == "table:natural_earth_province"
    assert ("nuts_region", None, pytest.approx(42.85), pytest.approx(-1.55)) in src.calls
    assert len([c for c in src.calls if c[0] == "nuts_region"]) == 1


async def test_an_unknown_parcel():
    with pytest.raises(ParcelNotFound):
        await assemble(replace(REQ, parcel_ids=("urn:ngsi-ld:AgriParcel:nope",)),
                       FakeSources(**complete_data()), TODAY)


async def test_no_zone_lookup_when_the_declared_yields_suffice():
    src = FakeSources(**complete_data())
    req = replace(REQ, declared_yields={2023: 5000.0, 2024: 6000.0, 2025: 5500.0},
                  previous_declared_yields={2023: 5000.0, 2024: 5100.0, 2025: 5200.0})
    a = await assemble(req, src, TODAY)
    assert a.yield_target.basis == "declared" and a.previous_yield.basis == "declared"
    assert not any(c[0] in ("regional_yields", "nuts_region") for c in src.calls)
    assert a.region.note == "not_needed"


async def test_the_chosen_region_is_used_without_a_lookup():
    src = FakeSources(**complete_data())
    a = await assemble(replace(REQ, nuts="ES22"), src, TODAY)
    assert a.region.value == "ES22" and a.region.provenance == "declared"
    assert not any(c[0] == "nuts_region" for c in src.calls)


async def test_parcels_in_two_regions():
    data = complete_data()
    other = "urn:ngsi-ld:AgriParcel:p2"
    data["parcels"][other] = dict(data["parcels"][URN], id=other, municipality="01059")
    data["nuts"]["01059"] = {"nuts": "ES21", "method": "ine_province"}
    a = await assemble(replace(REQ, parcel_ids=(URN, other)), FakeSources(**data), TODAY)
    assert not a.region.known
    assert Notice("parcels_in_several_regions", {"regions": ["ES21", "ES22"]}) in a.notices
    assert a.yield_target.basis == "missing"


async def test_a_failing_source_stops_the_assembly():
    data = complete_data()
    data["fail"] = {"lab_analyses": SourceUnavailable("soil", "answered 500")}
    with pytest.raises(SourceUnavailable) as err:
        await assemble(REQ, FakeSources(**data), TODAY)
    assert err.value.source == "soil"


async def test_measured_nitrate_from_the_water_analysis():
    data = complete_data()
    wq = "urn:ngsi-ld:WaterQualityObserved:w1"
    data["water"] = {wq: {"id": wq, "NO3": 50.0, "dateObserved": "2026-05-01T00:00:00Z"}}
    req = replace(REQ, irrigated=True, water_m3_ha=3000.0, water_quality_id=wq)
    a = await assemble(req, FakeSources(**data), TODAY)
    assert a.irrigation.no3_mg_l.provenance == "measured"
    assert a.irrigation.n_kg_ha.value > 0


async def test_analyses_of_several_parcels_are_merged_newest_first():
    data = complete_data()
    other = "urn:ngsi-ld:AgriParcel:p2"
    data["parcels"][other] = dict(data["parcels"][URN], id=other)
    newer = {"id": "a2", "samplingDate": "2026-10-01",
             "horizons": data["analyses"][URN][0]["horizons"]}
    data["analyses"][other] = [newer, data["analyses"][URN][0]]
    a = await assemble(replace(REQ, parcel_ids=(URN, other), nuts="ES22"), FakeSources(**data), TODAY)
    assert a.soil.analysis_id == "a2"


async def test_rain_normal_asks_year_by_year_in_order():
    src = FakeSources(**complete_data())
    normal = await fetch_rain_normal(src, URN, 2027)
    assert [c[1] for c in src.calls if c[0] == "daily"] == list(range(2016, 2026))
    assert normal.annual_mm is None


def _yield_request():
    return replace(REQ, declared_yields={2023: 5000.0, 2024: 6000.0, 2025: 5500.0})


async def test_the_previous_crop_uses_its_own_declared_yield_without_a_zone_call():
    src = FakeSources(**complete_data())
    req = replace(_yield_request(), previous_declared_yields={2026: 3000.0})
    a = await assemble(req, src, TODAY)
    assert a.choice.previous_campaign == 2026
    assert a.previous_yield.yield_kg_ha.value == 3000.0
    assert a.previous_yield.yield_kg_ha.provenance == "declared"
    assert not any(c[0] == "regional_yields" for c in src.calls)


async def test_a_recorded_harvest_beats_the_declared_yield_of_the_previous_crop():
    data = complete_data()
    data["harvests"] = {URN: [{"id": "urn:ngsi-ld:AgriParcelOperation:h1",
                               "operationType": "harvesting",
                               "endedAt": "2026-07-10T10:00:00Z", "harvestedWeight": 60000}]}
    req = replace(_yield_request(), previous_declared_yields={2026: 3000.0})
    a = await assemble(req, FakeSources(**data), TODAY)
    assert a.previous_yield.yield_kg_ha.value == 6000.0
    assert a.previous_yield.yield_kg_ha.provenance == "measured"


async def test_parcels_with_different_crops_are_flagged():
    data = complete_data()
    other = "urn:ngsi-ld:AgriParcel:p2"
    data["parcels"][other] = dict(data["parcels"][URN], id=other)
    cycles = [dict(c) for c in data["timelines"][URN]["cycles"]]
    cycles[0]["species"] = "HORVX"
    data["timelines"][other] = {"cycles": cycles}
    a = await assemble(replace(REQ, parcel_ids=(URN, other), nuts="ES22"), FakeSources(**data), TODAY)
    assert Notice("parcels_crops_differ", {"parcels": [other]}) in a.notices
    assert a.choice.previous.value == "TRZAX"


async def test_parcels_with_the_same_crops_are_not_flagged():
    data = complete_data()
    other = "urn:ngsi-ld:AgriParcel:p2"
    data["parcels"][other] = dict(data["parcels"][URN], id=other)
    data["timelines"][other] = data["timelines"][URN]
    a = await assemble(replace(REQ, parcel_ids=(URN, other), nuts="ES22"), FakeSources(**data), TODAY)
    assert not any(n.code == "parcels_crops_differ" for n in a.notices)


async def test_a_water_quality_answer_that_is_not_an_entity_is_not_found():
    data = complete_data()
    wq = "urn:ngsi-ld:WaterQualityObserved:w1"
    data["water"] = {wq: [{"NO3": 50.0}]}
    req = replace(REQ, irrigated=True, water_m3_ha=3000.0, water_quality_id=wq)
    a = await assemble(req, FakeSources(**data), TODAY)
    assert Notice("water_quality_not_found", {"id": wq}) in a.notices
