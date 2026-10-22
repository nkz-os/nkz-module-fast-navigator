"""In-memory stand-in for app.calc.assemble.Sources (same coroutine names)."""
import copy

from tests.calc.builders import COEFF, H
from tests.conftest import load_contract

URN = "urn:ngsi-ld:AgriParcel:p1"
RING = [[-1.6, 42.8], [-1.5, 42.8], [-1.5, 42.9], [-1.6, 42.9], [-1.6, 42.8]]


class FakeSources:
    def __init__(self, **data):
        self.data = data
        self.calls: list[tuple] = []
        self.fail: dict[str, Exception] = data.pop("fail", {})

    def _hit(self, name, *args):
        self.calls.append((name, *args))
        if name in self.fail:
            raise self.fail[name]

    async def parcel(self, urn):
        self._hit("parcel", urn)
        return self.data.get("parcels", {}).get(urn)

    async def harvests(self, urn):
        self._hit("harvests", urn)
        return self.data.get("harvests", {}).get(urn, [])

    async def fertilizations(self, urn):
        self._hit("fertilizations", urn)
        return self.data.get("fertilizations", {}).get(urn, [])

    async def timeline(self, urn, at):
        self._hit("timeline", urn)
        return self.data.get("timelines", {}).get(urn)

    async def lab_analyses(self, urn):
        self._hit("lab_analyses", urn)
        return self.data.get("analyses", {}).get(urn, [])

    async def estimated_horizons(self, urn):
        self._hit("estimated_horizons", urn)
        return self.data.get("estimated", {}).get(urn, [])

    async def coefficients(self, eppo):
        self._hit("coefficients", eppo)
        return self.data.get("coefficients", {}).get(eppo)

    async def regional_yields(self, eppo, nuts):
        self._hit("regional_yields", eppo, nuts)
        return self.data.get("zone", {}).get((eppo, nuts))

    async def nuts_region(self, municipality=None, lat=None, lon=None):
        self._hit("nuts_region", municipality, lat, lon)
        return self.data.get("nuts", {}).get(municipality or "point")

    async def water_quality(self, entity_id):
        self._hit("water_quality", entity_id)
        return self.data.get("water", {}).get(entity_id)

    async def daily(self, urn, start, end):
        self._hit("daily", start.year)
        return self.data.get("days", {}).get(start.year, [])


def complete_data() -> dict:
    """One rainfed wheat parcel; wheat the year before; zone yields; a full lab analysis."""
    zone = load_contract("bioorch_regional_yields_trzax_es22.json")
    return copy.deepcopy({
        "parcels": {URN: {"id": URN, "type": "AgriParcel", "area": 10.0, "name": "North",
                          "location": {"type": "Polygon", "coordinates": [RING]}}},
        "timelines": {URN: {"cycles": [
            {"crop_id": "c1", "role": "main_crop", "species": "TRZAX",
             "start": {"date": "2025-10-25"}, "end": {"date": "2026-07-10"},
             "campaign_label": 2026},
            {"crop_id": "c2", "role": "main_crop", "species": "TRZAX",
             "start": {"date": "2026-10-25"}, "end": {"date": "2027-07-10"},
             "campaign_label": 2027}]}},
        "analyses": {URN: [{"id": "a1", "samplingDate": "2026-09-01", "horizons": [H]}]},
        "coefficients": {"TRZAX": COEFF},
        "zone": {("TRZAX", "ES22"): zone},
        "nuts": {"point": {"nuts": "ES22", "method": "natural_earth_province",
                           "name": "Comunidad Foral de Navarra"}},
    })
