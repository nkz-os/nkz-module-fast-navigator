"""The frontend fixtures are the backend's own answers: regenerate with UPDATE_UI_FIXTURES=1."""
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import get_sources_factory
from app.main import app
from tests.fakes import URN, FakeSources, complete_data

FIXTURES = Path(__file__).resolve().parents[2] / "src" / "test" / "fixtures"
HOLDER = {"X-Tenant-ID": "tenant-a", "X-User-ID": "u-holder", "X-User-Roles": "TenantAdmin"}
BODY = {"campaign": 2027, "parcel_ids": [URN], "tillage": True, "irrigated": False,
        "rotation_years": 4}
OTHER = "urn:ngsi-ld:AgriParcel:p0"


def _answer(data: dict, method: str, url: str, **kwargs) -> dict:
    @asynccontextmanager
    async def factory(tenant_id):
        yield FakeSources(**data)

    app.dependency_overrides[get_sources_factory] = lambda: factory
    try:
        r = TestClient(app).request(method, url, headers=HOLDER, **kwargs)
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    return r.json()


def _complete() -> dict:
    return _answer(complete_data(), "POST", "/api/fast/calc/preview", json=BODY)


def _incomplete() -> dict:
    data = complete_data()
    data["analyses"] = {}
    return _answer(data, "POST", "/api/fast/calc/preview", json=BODY)


def _parcels() -> dict:
    data = complete_data()
    data["parcels"][OTHER] = {"id": OTHER, "type": "AgriParcel", "area": 3.0, "name": "Alpha"}
    return _answer(data, "GET", "/api/fast/sources/campaigns/2027/parcels")


def _crops() -> dict:
    names = {"es": "Trigo blando", "en": "Common wheat", "eu": "Gari bigun",
             "fr": "Blé tendre", "ca": "Blat tou", "pt": "Trigo mole"}
    data = {"crop_list": {"crops": [
        {"eppo": "TRZAX", "slug": "wheat", "names": names},
        {"eppo": "VICFX", "slug": "faba-bean", "names": {
            "es": "Haba", "en": "Faba bean", "eu": "Baba", "fr": "Féverole", "ca": "Fava",
            "pt": "Fava"}},
        {"eppo": "CIEAR", "slug": "chickpea", "has_coefficients": False, "names": {
            "es": "Garbanzo", "en": "Chickpea", "eu": "Txitxirioa", "fr": "Pois chiche",
            "ca": "Cigró", "pt": "Grão-de-bico"}}]}}
    return _answer(data, "GET", "/api/fast/sources/crops")


BUILDERS = {"sheet-result-complete": _complete, "sheet-result-incomplete": _incomplete,
            "campaign-parcels": _parcels,
            "source-crops": _crops}


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_ui_fixture_is_the_backend_answer(name):
    path = FIXTURES / f"{name}.json"
    built = json.loads(json.dumps(BUILDERS[name]()))
    if os.environ.get("UPDATE_UI_FIXTURES") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(built, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    assert path.exists(), f"{path} is missing: run with UPDATE_UI_FIXTURES=1"
    assert json.loads(path.read_text()) == built
