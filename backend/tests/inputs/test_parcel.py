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
