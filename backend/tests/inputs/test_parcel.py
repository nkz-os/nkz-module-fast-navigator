import pytest

from app.inputs.parcel import SAREF_AREA, is_parcel_identifier, parcel_info
from app.inputs.provenance import MEASURED, MissingInput, Notice

RING = [[-1.6, 42.8], [-1.5, 42.8], [-1.5, 42.9], [-1.6, 42.9], [-1.6, 42.8]]


def _parcel(**changes):
    base = {"id": "urn:ngsi-ld:AgriParcel:p1", "type": "AgriParcel", "name": "North",
            "area": 8.9, "location": {"type": "Polygon", "coordinates": [RING]}}
    base.update(changes)
    return {k: v for k, v in base.items() if v is not None}


def test_area_in_hectares():
    info = parcel_info(_parcel())
    assert info.area_ha.value == 8.9 and info.area_ha.provenance == MEASURED
    assert not info.missing


def test_area_under_the_old_saref_key():
    entity = _parcel(area=None)
    entity[SAREF_AREA] = 30.9
    assert parcel_info(entity).area_ha.value == 30.9


@pytest.mark.parametrize("area", [None, 0, -1, "8.9"])
def test_no_usable_area_is_missing_never_zero(area):
    info = parcel_info(_parcel(area=area))
    assert not info.area_ha.known
    assert MissingInput("parcel.area_ha", "broker", {"parcel": "urn:ngsi-ld:AgriParcel:p1"}) in info.missing


@pytest.mark.parametrize("ref,kind", [("31201A00100123", "cadastral"),
                                      ("31201A001001230000XY", "cadastral"),
                                      ("31:201:0:0:1:123:1", "sigpac")])
def test_identifier_formats(ref, kind):
    ident = parcel_info(_parcel(cadastralReference=ref)).identifier
    assert ident.value == ref and ident.note == kind


def test_an_unrecognized_identifier_is_not_used():
    info = parcel_info(_parcel(cadastralReference="CATAST_Pol_ParcelaRusti.344737"))
    assert not info.identifier.known
    assert Notice("parcel_identifier_unrecognized",
                  {"parcel": "urn:ngsi-ld:AgriParcel:p1",
                   "value": "CATAST_POL_PARCELARUSTI.344737"}) in info.notices


def test_point_is_the_mean_of_the_outer_ring():
    lat, lon = parcel_info(_parcel()).point
    assert lat == pytest.approx(42.85) and lon == pytest.approx(-1.55)


def test_point_of_a_multipolygon():
    entity = _parcel(location={"type": "MultiPolygon", "coordinates": [[RING]]})
    assert parcel_info(entity).point == pytest.approx((42.85, -1.55))


@pytest.mark.parametrize("value,code", [("31201", "31201"), ("IMOTZ", None), (31201, None)])
def test_municipality_code_only_when_it_is_an_ine_code(value, code):
    assert parcel_info(_parcel(municipality=value)).municipality_code == code


def test_farm_from_either_relationship_name():
    assert parcel_info(_parcel(hasAgriFarm="urn:ngsi-ld:AgriFarm:f1")).farm == "urn:ngsi-ld:AgriFarm:f1"
    assert parcel_info(_parcel(refAgriFarm="urn:ngsi-ld:AgriFarm:f2")).farm == "urn:ngsi-ld:AgriFarm:f2"


@pytest.mark.parametrize("value,ok", [("31201A00100123", True), ("31:201:0:0:1:123:1", True),
                                      ("CATAST_Pol_ParcelaRusti.344737", False), ("", False)])
def test_is_parcel_identifier(value, ok):
    assert is_parcel_identifier(value) is ok


ENCL = [{"reference": "31:97:0:0:4:228:1", "overlapAreaHa": 0.947, "overlapPct": 43.36},
        {"reference": "31:97:0:0:4:90020:1", "overlapAreaHa": 0.642, "overlapPct": 29.41}]


@pytest.mark.parametrize("key", ["sigpacEnclosures", "https://nkz-os.org/ns/sigpacEnclosures",
                                 "https://uri.etsi.org/ngsi-ld/default-context/sigpacEnclosures"])
def test_enclosures_win_over_cadastral_reference(key):
    info = parcel_info(_parcel(cadastralReference="31201A00100123") | {key: ENCL})
    assert [e["reference"] for e in info.enclosures] == ["31:97:0:0:4:228:1", "31:97:0:0:4:90020:1"]
    assert info.identifier.value == "31:97:0:0:4:228:1, 31:97:0:0:4:90020:1"
    assert info.identifier.provenance == MEASURED and info.identifier.note == "sigpac"
    assert info.identifier.source.endswith(":sigpacEnclosures")
    assert info.enclosures[0]["overlap_pct"] == 43.36


def test_no_enclosures_keeps_cadastral_fallback():
    info = parcel_info(_parcel(cadastralReference="31201A00100123", sigpacEnclosures=[]))
    assert info.enclosures == () and info.identifier.value == "31201A00100123"


def test_malformed_enclosures_are_ignored():
    info = parcel_info(_parcel(sigpacEnclosures=[{"reference": "nope"}, "x", {"overlapPct": 5}]))
    assert info.enclosures == () and not info.identifier.known


@pytest.mark.parametrize("key", ["sigpacEnclosures", "https://nkz-os.org/ns/sigpacEnclosures",
                                 "https://uri.etsi.org/ngsi-ld/default-context/sigpacEnclosures"])
def test_single_enclosure_compacted_by_the_broker_to_an_object(key):
    # Orion-LD compacts a one-element array into the bare element
    info = parcel_info(_parcel(cadastralReference="31201A00100123") | {key: ENCL[0]})
    assert [e["reference"] for e in info.enclosures] == ["31:97:0:0:4:228:1"]
    assert info.identifier.value == "31:97:0:0:4:228:1"


def _uses(*pairs):
    return [{"reference": ref, "overlapPct": pct, "sigpacUse": use} for ref, pct, use in pairs]


def test_only_agricultural_enclosures_are_selected_by_default():
    info = parcel_info(_parcel(sigpacEnclosures=_uses(
        ("31:125:0:0:2:729:1", 84.27, "TA"), ("31:125:0:0:2:730:1", 9.1, "PR"),
        ("31:125:0:0:2:9001:1", 3.0, "CA"), ("31:125:0:0:2:731:1", 2.0, "ED"))))
    assert [(e["reference"], e["sigpac_use"], e["selected"]) for e in info.enclosures] == [
        ("31:125:0:0:2:729:1", "TA", True), ("31:125:0:0:2:730:1", "PR", True),
        ("31:125:0:0:2:9001:1", "CA", False), ("31:125:0:0:2:731:1", "ED", False)]
    assert info.identifier.value == "31:125:0:0:2:729:1, 31:125:0:0:2:730:1"


@pytest.mark.parametrize("use", ["AG", "CA", "ED", "EP", "FO", "IM", "IS", "MT", "ZC", "ZU", "ZV"])
def test_non_agricultural_uses_are_not_preselected(use):
    info = parcel_info(_parcel(sigpacEnclosures=_uses(
        ("31:1:0:0:1:1:1", 90.0, "TA"), ("31:1:0:0:1:2:1", 10.0, use))))
    assert [e["selected"] for e in info.enclosures] == [True, False]


def test_unknown_or_absent_use_is_preselected():
    info = parcel_info(_parcel(sigpacEnclosures=[
        {"reference": "31:1:0:0:1:1:1", "overlapPct": 60.0},
        {"reference": "31:1:0:0:1:2:1", "overlapPct": 40.0, "sigpacUse": "XX"}]))
    assert [e["selected"] for e in info.enclosures] == [True, True]
    assert info.enclosures[0]["sigpac_use"] is None


def test_only_non_agricultural_enclosures_keeps_them_all():
    # never leave the parcel without an identifier just because SIGPAC calls it a road
    info = parcel_info(_parcel(sigpacEnclosures=_uses(
        ("31:1:0:0:1:1:1", 70.0, "IM"), ("31:1:0:0:1:2:1", 30.0, "CA"))))
    assert [e["selected"] for e in info.enclosures] == [True, True]
    assert info.identifier.value == "31:1:0:0:1:1:1, 31:1:0:0:1:2:1"


def test_declared_choice_replaces_the_default():
    info = parcel_info(_parcel(sigpacEnclosures=_uses(
        ("31:1:0:0:1:1:1", 80.0, "TA"), ("31:1:0:0:1:2:1", 15.0, "TA"),
        ("31:1:0:0:1:3:1", 5.0, "IM"))),
        chosen=("31:1:0:0:1:1:1", "31:1:0:0:1:3:1"))
    assert [e["selected"] for e in info.enclosures] == [True, False, True]
    assert info.identifier.value == "31:1:0:0:1:1:1, 31:1:0:0:1:3:1"
    assert info.identifier.provenance == MEASURED


def test_a_stale_choice_falls_back_to_the_default():
    # the geometry changed and none of the chosen enclosures is still overlapped
    info = parcel_info(_parcel(sigpacEnclosures=_uses(
        ("31:1:0:0:1:1:1", 90.0, "TA"), ("31:1:0:0:1:3:1", 10.0, "IM"))),
        chosen=("31:9:0:0:9:9:9",))
    assert [e["selected"] for e in info.enclosures] == [True, False]
