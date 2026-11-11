import pytest

from app.sources import broker
from app.zones.read import select_zoning, zonings_of

PARCEL = "urn:ngsi-ld:AgriParcel:parcel-1"
SQUARE = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}


def kv(i, run="run-a", link="hasAgriParcel", parcel=PARCEL, **extra):
    """A zone in keyValues form."""
    e = {"id": f"urn:ngsi-ld:AgriManagementZone:parcel-1:Z{i}", "type": "AgriManagementZone",
         link: parcel, "location": SQUARE, "zoneName": f"Zone {i + 1}", "zoneId": i,
         "areaHa": 2.5, "meanValue": 0.5, "zoningRunId": run, "zoningMethod": "vegetationIndex",
         "dateZoned": "2026-10-01T05:00:00Z", "variableAttribute": "NDVI"}
    e.update(extra)
    return e


def normalized(i, run="run-a", link="hasAgriParcel", parcel=PARCEL, prefix=""):
    """The same zone normalized, with terms under a prefix and a Relationship link."""
    def p(v):
        return {"type": "Property", "value": v}
    e = {"id": f"urn:ngsi-ld:AgriManagementZone:parcel-1:Z{i}", "type": "AgriManagementZone",
         link: {"type": "Relationship", "object": parcel},
         "location": {"type": "GeoProperty", "value": SQUARE}}
    for name, value in (("zoneName", f"Zone {i + 1}"), ("zoneId", i), ("areaHa", 2.5),
                        ("meanValue", 0.5), ("zoningRunId", run), ("zoningMethod", "vegetationIndex"),
                        ("variableAttribute", "NDVI")):
        e[prefix + name] = p(value)
    e[prefix + "dateZoned"] = p({"@type": "DateTime", "@value": "2026-10-01T05:00:00Z"})
    return e


@pytest.mark.parametrize("make", [
    lambda i, **k: kv(i, **k),
    lambda i, **k: normalized(i, **k),
    lambda i, **k: normalized(i, prefix="nkz:", **k),
    lambda i, **k: normalized(i, prefix="https://nkz-os.org/ns/", **k),
])
@pytest.mark.parametrize("link", ["hasAgriParcel", "refAgriParcel"])
def test_both_link_spellings_and_all_attribute_forms(make, link):
    zoning = select_zoning([make(0, link=link), make(1, link=link)], PARCEL, "run-a")
    assert zoning is not None
    assert (zoning.run_id, zoning.method, zoning.variable, zoning.date) == (
        "run-a", "vegetationIndex", "NDVI", "2026-10-01")
    assert [(z.label, z.rank, z.area_ha, z.mean_value, z.problems) for z in zoning.zones] == [
        ("Zone 1", 1, 2.5, 0.5, ()), ("Zone 2", 2, 2.5, 0.5, ())]
    assert zoning.zones[0].geometry == SQUARE


def test_the_run_is_chosen_by_id_and_never_falls_back():
    entities = [kv(0, run="run-a"), kv(1, run="run-b"), kv(2, run="run-b")]
    assert len(select_zoning(entities, PARCEL, "run-b").zones) == 2
    assert len(select_zoning(entities, PARCEL, "run-a").zones) == 1
    assert select_zoning(entities, PARCEL, "run-c") is None
    assert {z.run_id for z in zonings_of(entities, PARCEL)} == {"run-a", "run-b"}


def test_a_manual_zoning_has_no_mean_value_and_that_is_not_a_defect():
    manual = [kv(i, run="m", zoningMethod="manual", meanValue=None, variableAttribute=None)
              for i in range(2)]
    for e in manual:
        del e["meanValue"], e["variableAttribute"]
    zoning = select_zoning(manual, PARCEL, "m")
    assert zoning.method == "manual" and zoning.variable is None
    assert [(z.mean_value, z.problems) for z in zoning.zones] == [(None, ()), (None, ())]


def test_missing_area_and_invalid_values_are_reported_not_replaced():
    entities = [kv(0, areaHa=None), kv(1, meanValue=0), kv(2, meanValue=-0.2),
                kv(3, meanValue="0.4"), kv(4, areaHa=-1), kv(5)]
    del entities[0]["areaHa"]
    zones = {z.id.rsplit("Z", 1)[1]: z for z in select_zoning(entities, PARCEL, "run-a").zones}
    assert zones["0"].area_ha is None and zones["0"].problems == ("area_ha",)
    assert zones["1"].mean_value is None and zones["1"].problems == ("mean_value_invalid",)
    assert zones["2"].problems == ("mean_value_invalid",)
    assert zones["3"].problems == ("mean_value_invalid",)
    assert zones["4"].area_ha is None and zones["4"].problems == ("area_ha",)
    assert zones["5"].problems == ()


def test_an_entity_linked_to_another_parcel_is_ignored():
    other = kv(9, parcel="urn:ngsi-ld:AgriParcel:parcel-2")
    zoning = select_zoning([kv(0), other], PARCEL, "run-a")
    assert [z.id for z in zoning.zones] == ["urn:ngsi-ld:AgriManagementZone:parcel-1:Z0"]


class FakeOrion:
    def __init__(self, by_link):
        self.by_link, self.calls = by_link, []

    async def query_entities(self, type=None, q=None, limit=100, offset=0, attrs=None,
                             options=None):
        self.calls.append((type, q, offset, options))
        link = q.split("==")[0]
        return self.by_link.get(link, []) if offset == 0 else []


async def test_the_broker_read_queries_both_links_and_merges_by_id():
    orion = FakeOrion({"hasAgriParcel": [kv(0), kv(1)],
                       "refAgriParcel": [kv(1, link="refAgriParcel"), kv(2, link="refAgriParcel")]})
    got = await broker.fetch_zone_entities(orion, PARCEL)
    assert sorted(e["id"][-2:] for e in got) == ["Z0", "Z1", "Z2"]
    assert [(t, q) for t, q, *_ in orion.calls] == [
        ("AgriManagementZone", f'hasAgriParcel=="{PARCEL}"'),
        ("AgriManagementZone", f'refAgriParcel=="{PARCEL}"')]
    assert {o for *_, o in orion.calls} == {"sysAttrs"}


async def test_the_broker_read_refuses_a_urn_that_could_break_the_query():
    with pytest.raises(ValueError):
        await broker.fetch_zone_entities(FakeOrion({}), 'urn:x"; type=="y')
