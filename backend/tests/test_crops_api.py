from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from app.api import get_sources_factory
from app.main import app
from app.sources.errors import SourceUnavailable
from tests.fakes import URN, FakeSources, complete_data

HEADERS = {"X-Tenant-ID": "tenant-a", "X-User-ID": "u1", "X-User-Roles": "Farmer"}
URL = "/api/fast/sources/crops"
NAMES = {"es": "Trigo blando", "en": "Common wheat", "eu": "Garagar", "fr": "Blé", "ca": "Blat", "pt": "Trigo"}
LIST = {"crops": [{"eppo": "TRZAX", "slug": "wheat", "names": NAMES},
                  {"eppo": "VICFX", "slug": "faba", "names": {"es": "Haba", "en": "Faba bean"},
                   "has_coefficients": False}]}


def _client(**data):
    @asynccontextmanager
    async def factory(tenant_id):
        yield FakeSources(**data)

    app.dependency_overrides[get_sources_factory] = lambda: factory
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear():
    yield
    app.dependency_overrides.clear()


def test_lists_crops_by_name_with_the_coefficients_flag():
    r = _client(crop_list=LIST).get(URL, headers=HEADERS)
    assert r.status_code == 200, r.text
    crops = r.json()["crops"]
    assert [c["eppo"] for c in crops] == ["TRZAX", "VICFX"]
    assert crops[0] == {"eppo": "TRZAX", "names": NAMES, "has_coefficients": True}
    assert crops[1]["has_coefficients"] is False and "slug" not in crops[1]


def test_a_malformed_entry_is_dropped():
    bad = {"crops": [{"names": NAMES}, {"eppo": "no", "names": NAMES}, LIST["crops"][0]]}
    r = _client(crop_list=bad).get(URL, headers=HEADERS)
    assert [c["eppo"] for c in r.json()["crops"]] == ["TRZAX"]


def test_needs_a_plan_role():
    c = _client(crop_list=LIST)
    assert c.get(URL, headers=dict(HEADERS, **{"X-User-Roles": "Viewer"})).status_code == 403
    assert c.get(URL).status_code == 401


def test_bioorch_down_is_503_naming_the_source():
    c = _client(crop_list=LIST, fail={"crop_list": SourceUnavailable("bioorch", "answered 500")})
    r = c.get(URL, headers=HEADERS)
    assert r.status_code == 503 and r.json()["source"] == "bioorch"


def test_an_unknown_answer_from_bioorch_is_503():
    r = _client(crop_list=None).get(URL, headers=HEADERS)
    assert r.status_code == 503 and r.json()["source"] == "bioorch"


def test_the_parcel_summary_carries_the_cover_crop_hint():
    data = complete_data()
    data["timelines"][URN]["cycles"].append(
        {"crop_id": "cv", "role": "cover_crop", "species": "VICSA",
         "start": {"date": "2026-10-15"}, "end": {"date": "2027-04-14"}, "campaign_label": 2027})
    data["timelines"][URN]["cycles"][-2]["start"] = {"date": "2027-04-14"}
    c = _client(**data)
    one = c.get("/api/fast/sources/parcels/p1?campaign=2027", headers=HEADERS).json()
    assert one["cover_before"] == "VICSA"
    listed = c.get("/api/fast/sources/campaigns/2027/parcels", headers=HEADERS).json()["parcels"][0]
    assert listed["cover_before"] == "VICSA"
