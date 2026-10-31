"""Gather a sheet's inputs from their owners (spec §4) for the calculation."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field, replace
from datetime import date

import httpx

from app.config import Settings
from app.engine.types import Management
from app.inputs.crop import build_crop
from app.inputs.crops import FALLOW, crops_for_campaign
from app.inputs.irrigation import irrigation_credit
from app.inputs.organic import OrganicApplication, organic_credit
from app.inputs.parcel import ParcelInfo, parcel_info
from app.inputs.provenance import (
    DECLARED,
    MEASURED,
    Notice,
    Override,
    Sourced,
    missing,
    table,
)
from app.inputs.rain import RainNormal, rain_normal, rain_years
from app.inputs.soil import build_soil
from app.inputs.yield_target import (
    YieldTarget,
    combine_histories,
    history_yields,
    previous_zone_needed,
    resolve_previous_yield,
    resolve_yield,
    zone_needed,
)
from app.sources import bioorch, broker, cycles, soil, weather

from .sheet import AssembledInputs

logger = logging.getLogger(__name__)


class ParcelNotFound(LookupError):
    def __init__(self, urn: str):
        super().__init__(urn)
        self.urn = urn


@dataclass(frozen=True)
class SheetRequest:
    campaign: int
    parcel_ids: tuple[str, ...]
    tillage: bool
    irrigated: bool
    rotation_years: int
    strategy: int = 2
    previous_residues_burned: bool = False
    crop_eppo: str | None = None
    previous_crop_eppo: str | None = None
    residues: str | None = None   # "left" | "removed": residues of the campaign crop
    cycle_index: int = 0
    soil_analysis_id: str | None = None
    nmin_analysis_id: str | None = None
    declared_yields: dict[int, float] = field(default_factory=dict)
    previous_declared_yields: dict[int, float] = field(default_factory=dict)
    organic: tuple[OrganicApplication, ...] = ()
    water_m3_ha: float | None = None
    water_quality_id: str | None = None
    no3_mg_l: float | None = None
    nuts: str | None = None
    overrides: tuple[Override, ...] = ()


class Sources:
    """The live sources for one tenant; tests pass an object with the same coroutines."""

    def __init__(self, client: httpx.AsyncClient, orion, settings: Settings, tenant_id: str):
        self._client, self._orion, self._s, self._tenant = client, orion, settings, tenant_id

    async def coefficients(self, eppo: str) -> dict | None:
        return await bioorch.fetch_coefficients(self._client, self._s.bioorch_url, eppo)

    async def crop_list(self) -> dict | None:
        return await bioorch.fetch_crop_list(self._client, self._s.bioorch_url)

    async def regional_yields(self, eppo: str, nuts: str) -> dict | None:
        return await bioorch.fetch_regional_yields(self._client, self._s.bioorch_url, eppo, nuts)

    async def nuts_region(self, municipality: str | None = None, lat: float | None = None,
                          lon: float | None = None) -> dict | None:
        return await bioorch.fetch_nuts_region(self._client, self._s.bioorch_url,
                                               municipality=municipality, lat=lat, lon=lon)

    async def parcel(self, urn: str) -> dict | None:
        return await broker.fetch_parcel(self._orion, urn)

    async def parcels(self) -> list[dict]:
        return await broker.fetch_parcels(self._orion)

    async def harvests(self, urn: str) -> list[dict]:
        return await broker.fetch_harvests(self._orion, urn)

    async def fertilizations(self, urn: str) -> list[dict]:
        return await broker.fetch_fertilizations(self._orion, urn)

    async def water_quality(self, entity_id: str) -> dict | None:
        return await broker.fetch_water_quality(self._orion, entity_id)

    async def lab_analyses(self, urn: str) -> list[dict]:
        return await soil.fetch_lab_analyses(self._client, self._s.soil_url, self._tenant,
                                             self._s.hmac_secret, urn)

    async def estimated_horizons(self, urn: str) -> list[dict]:
        return await soil.fetch_estimated_horizons(self._client, self._s.soil_url, self._tenant,
                                                   self._s.hmac_secret, urn)

    async def timeline(self, urn: str, at: date) -> dict | None:
        return await cycles.fetch_timeline(self._orion, urn, at)

    async def daily(self, urn: str, start: date, end: date) -> list[dict]:
        return await weather.fetch_daily(self._client, self._s.weather_api_url, self._tenant,
                                         self._s.hmac_secret, urn, start, end)


async def resolve_region(sources, nuts: str | None, parcels: tuple[ParcelInfo, ...]
                         ) -> tuple[Sourced, tuple[Notice, ...]]:
    """NUTS 2 of the sheet: the chosen one, else each parcel's INE code, else its point."""
    if nuts:
        return Sourced(nuts, DECLARED, "plan"), ()
    found: dict[str, dict] = {}
    for parcel in parcels:
        if parcel.municipality_code:
            answer = await sources.nuts_region(municipality=parcel.municipality_code)
        elif parcel.point:
            answer = await sources.nuts_region(lat=parcel.point[0], lon=parcel.point[1])
        else:
            continue
        if answer and answer.get("nuts"):
            found.setdefault(answer["nuts"], answer)
    if len(found) == 1:
        code, answer = next(iter(found.items()))
        return Sourced(code, table(answer.get("method") or "nuts_region"),
                       "bioorch:nuts-region", answer.get("name")), ()
    if len(found) > 1:
        return (missing("bioorch:nuts-region"),
                (Notice("parcels_in_several_regions", {"regions": sorted(found)}),))
    return missing("bioorch:nuts-region"), (Notice("region_not_found", {}),)


def _merge_analyses(lists: list[list[dict]]) -> list[dict]:
    by_id: dict[str, dict] = {}
    for analyses in lists:
        for a in analyses:
            by_id.setdefault(a.get("id"), a)
    return sorted(by_id.values(), key=lambda a: a.get("samplingDate") or "", reverse=True)


def _no3(req: SheetRequest, water: dict | None, notices: list[Notice]) -> Sourced:
    if req.water_quality_id:
        entity = water if isinstance(water, dict) else {}
        value = entity.get("NO3")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            observed = entity.get("dateObserved")
            return Sourced(float(value), MEASURED, f"broker:{req.water_quality_id}",
                           observed if isinstance(observed, str) else None)
        notices.append(Notice("water_quality_not_found", {"id": req.water_quality_id}))
        return missing(f"broker:{req.water_quality_id}")
    if req.no3_mg_l is not None:
        return Sourced(float(req.no3_mg_l), DECLARED, "plan")
    return missing("plan")


async def _none() -> None:
    return None


async def assemble(req: SheetRequest, sources, today: date) -> AssembledInputs:
    overrides = {o.param: o for o in req.overrides}
    notices: list[Notice] = []
    entities = await asyncio.gather(*(sources.parcel(urn) for urn in req.parcel_ids))
    for urn, entity in zip(req.parcel_ids, entities):
        if entity is None:
            raise ParcelNotFound(urn)
    parcels = tuple(parcel_info(e) for e in entities)
    first = parcels[0].urn

    timelines, analyses, harvests, estimated = await asyncio.gather(
        asyncio.gather(*(sources.timeline(p.urn, today) for p in parcels)),
        asyncio.gather(*(sources.lab_analyses(p.urn) for p in parcels)),
        asyncio.gather(*(sources.harvests(p.urn) for p in parcels)),
        sources.estimated_horizons(first),
    )
    cycle_lists = [list((t or {}).get("cycles") or []) for t in timelines]

    choices = [crops_for_campaign(cycles_of, req.campaign, req.cycle_index, req.crop_eppo,
                                  req.previous_crop_eppo) for cycles_of in cycle_lists]
    choice = choices[0]
    differ = [p.urn for p, c in zip(parcels[1:], choices[1:])
              if (c.crop.value, c.previous.value) != (choice.crop.value, choice.previous.value)]
    if differ:
        notices.append(Notice("parcels_crops_differ", {"parcels": differ}))
    crop_eppo = choice.crop.value if choice.crop.known else None
    prev_eppo = (choice.previous.value
                 if choice.previous.known and choice.previous.value != FALLOW else None)
    coeff, prev_coeff = await asyncio.gather(
        sources.coefficients(crop_eppo) if crop_eppo else _none(),
        sources.coefficients(prev_eppo) if prev_eppo else _none())
    crop = build_crop(crop_eppo, coeff, overrides, "crop", residues=req.residues)
    previous_crop = build_crop(prev_eppo, prev_coeff, overrides, "previous_crop") if prev_eppo else None

    region: Sourced | None = None

    async def region_value() -> Sourced:
        nonlocal region
        if region is None:
            region, found = await resolve_region(sources, req.nuts, parcels)
            notices.extend(found)
        return region

    async def target(eppo: str | None, campaign: int, declared: dict[int, float],
                     prefix: str) -> YieldTarget:
        per_parcel, history_notices = [], []
        for parcel, cyc, hv in zip(parcels, cycle_lists, harvests):
            if eppo and parcel.area_ha.known:
                got, found = history_yields(cyc, hv, eppo, parcel.area_ha.value)
                per_parcel.append((got, parcel.area_ha.value))
                history_notices.extend(found)
        history = combine_histories(per_parcel)
        previous = prefix == "previous_yield"
        needed = (previous_zone_needed if previous else zone_needed)(
            campaign, history, declared, overrides, prefix)
        zone = None
        if eppo and needed:
            nuts = await region_value()
            if nuts.known:
                zone = await sources.regional_yields(eppo, nuts.value)
        resolve = resolve_previous_yield if previous else resolve_yield
        resolved = resolve(campaign, history, declared, zone, overrides, today, prefix)
        return replace(resolved, notices=tuple(history_notices) + resolved.notices)

    yield_target = await target(crop_eppo, req.campaign, req.declared_yields, "yield")
    previous_yield = None
    if prev_eppo:
        previous_yield = await target(prev_eppo, choice.previous_campaign or req.campaign - 1,
                                      req.previous_declared_yields, "previous_yield")

    soil_inputs = build_soil(_merge_analyses(list(analyses)), list(estimated),
                             req.soil_analysis_id, req.nmin_analysis_id, overrides)
    water = await sources.water_quality(req.water_quality_id) if req.water_quality_id else None
    irrigation = irrigation_credit(req.irrigated, req.water_m3_ha, _no3(req, water, notices),
                                   overrides)
    if region is None:
        region = (Sourced(req.nuts, DECLARED, "plan") if req.nuts
                  else missing("bioorch:nuts-region", "not_needed"))
    logger.info("sheet assembled campaign=%s parcels=%d crop=%s", req.campaign, len(parcels),
                crop_eppo)
    return AssembledInputs(
        campaign=req.campaign,
        management=Management(strategy=req.strategy, tillage=req.tillage, irrigated=req.irrigated),
        previous_residues_burned=req.previous_residues_burned,
        rotation_years=req.rotation_years,
        choice=choice, crop=crop, previous_crop=previous_crop,
        yield_target=yield_target, previous_yield=previous_yield,
        soil=soil_inputs, organic=organic_credit(req.organic, overrides), irrigation=irrigation,
        region=region, parcels=parcels, notices=tuple(notices))


async def fetch_rain_normal(sources, parcel_urn: str, campaign: int) -> RainNormal:
    """Ten calendar years, one request each, one after the other (weather-api fill budget)."""
    days = {}
    for year in rain_years(campaign):
        days[year] = await sources.daily(parcel_urn, date(year, 1, 1), date(year, 12, 31))
    return rain_normal(days)
