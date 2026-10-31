"""BioOrch public reference endpoints: balance coefficients, zone yields, NUTS 2 regions."""
from __future__ import annotations

import httpx

from .http import get_json

SOURCE = "bioorch"
_BASE = "/api/graph/agriculture"


async def fetch_coefficients(client: httpx.AsyncClient, base_url: str, eppo: str) -> dict | None:
    return await get_json(client, SOURCE, f"{base_url}{_BASE}/crop-balance-coefficients",
                          params={"eppo": eppo})


async def fetch_crop_list(client: httpx.AsyncClient, base_url: str) -> dict | None:
    """Crops with balance coefficients and their names: the same route, without `eppo`."""
    return await get_json(client, SOURCE, f"{base_url}{_BASE}/crop-balance-coefficients")


async def fetch_regional_yields(client: httpx.AsyncClient, base_url: str, eppo: str, nuts: str,
                                recent: int = 5) -> dict | None:
    return await get_json(client, SOURCE, f"{base_url}{_BASE}/regional-yields",
                          params={"eppo": eppo, "nuts": nuts, "recent": recent})


async def fetch_nuts_region(client: httpx.AsyncClient, base_url: str, *,
                            municipality: str | None = None, lat: float | None = None,
                            lon: float | None = None) -> dict | None:
    """NUTS 2 region of an INE municipality code, or of a point (lat/lon)."""
    if municipality:
        params: dict = {"municipality": municipality}
    elif lat is not None and lon is not None:
        params = {"lat": lat, "lon": lon}
    else:
        raise ValueError("municipality or lat/lon is required")
    return await get_json(client, SOURCE, f"{base_url}{_BASE}/nuts-region", params=params)


async def fetch_nuts_regions(client: httpx.AsyncClient, base_url: str,
                             country: str = "ES") -> dict | None:
    return await get_json(client, SOURCE, f"{base_url}{_BASE}/nuts-regions",
                          params={"country": country})
