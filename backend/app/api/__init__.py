"""FaST API: calculation preview and the data the plan wizard shows (spec §9, §10)."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from contextlib import asynccontextmanager
from typing import Annotated
from datetime import UTC, date, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from nkz_platform_sdk import OrionClient
from pydantic import BaseModel, Field, field_validator

from app.calc.assemble import ParcelNotFound, SheetRequest, Sources, assemble
from app.calc.sheet import calculate
from app.config import Settings, get_settings
from app.inputs.crops import (
    EPPO, campaign_main_cycles, cover_before, crops_for_campaign, cycle_view,
)
from app.inputs.organic import OrganicApplication
from app.inputs.overrides import check_override, farmer_may_override
from app.inputs.parcel import parcel_info
from app.inputs.provenance import Override
from app.middleware import AuthContext, require_auth
from app.sources.errors import SourceUnavailable

logger = logging.getLogger(__name__)

PLAN_ROLES = ["Farmer", "TechnicalConsultant", "TenantAdmin"]
TECHNICIAN = "TechnicalConsultant"
# Non-technician editors (role matrix 2026-10-31): the holder (TenantAdmin) and the technician.
# Farmer (field worker) only reads.
EDITOR_ROLES = ["TenantAdmin", "TechnicalConsultant"]
PARCEL_ID_PATTERN = r"^(urn:ngsi-ld:AgriParcel:)?[A-Za-z0-9._-]+$"
WATER_QUALITY_PATTERN = r"^urn:ngsi-ld:WaterQualityObserved:[A-Za-z0-9._-]+$"
EPPO_PATTERN = r"^[A-Z0-9]{5,6}$"

router = APIRouter(tags=["FaST"])


def get_sources_factory(settings: Settings = Depends(get_settings)):
    """Opens the live sources for one tenant (tests replace this dependency)."""
    @asynccontextmanager
    async def factory(tenant_id: str):
        orion = OrionClient(tenant_id)
        try:
            async with httpx.AsyncClient() as client:
                yield Sources(client, orion, settings, tenant_id)
        finally:
            await orion.close()

    return factory


class OverrideIn(BaseModel):
    param: str
    value: bool | float | str
    reason: str = Field(min_length=1, max_length=500)


class OrganicIn(BaseModel):
    material: str
    rate_t_ha: float
    n_pct: float
    p2o5_pct: float
    k2o_pct: float


class SheetIn(BaseModel):
    campaign: int = Field(ge=2000, le=2100)
    parcel_ids: list[Annotated[str, Field(pattern=PARCEL_ID_PATTERN, max_length=200)]] = Field(
        min_length=1, max_length=200)
    tillage: bool
    irrigated: bool
    rotation_years: int = Field(ge=1, le=20)
    strategy: int = Field(default=2, ge=1, le=4)
    previous_residues_burned: bool = False
    crop_eppo: str | None = Field(default=None, pattern=EPPO_PATTERN)
    previous_crop_eppo: str | None = Field(default=None, pattern=r"^([A-Z0-9]{5,6}|fallow)$")
    cycle_index: int = Field(default=0, ge=0, le=3)
    soil_analysis_id: str | None = Field(default=None, max_length=200)
    nmin_analysis_id: str | None = Field(default=None, max_length=200)
    declared_yields: dict[int, float] = Field(default_factory=dict)
    previous_declared_yields: dict[int, float] = Field(default_factory=dict)
    organic: list[OrganicIn] = Field(default_factory=list, max_length=20)
    water_m3_ha: float | None = Field(default=None, ge=0, le=30000)
    water_quality_id: str | None = Field(default=None, pattern=WATER_QUALITY_PATTERN,
                                         max_length=200)
    no3_mg_l: float | None = Field(default=None, ge=0, le=1000)
    nuts: str | None = Field(default=None, pattern=r"^[A-Z]{2}[0-9A-Z]{2}$")
    overrides: list[OverrideIn] = Field(default_factory=list, max_length=100)

    @field_validator("declared_yields", "previous_declared_yields")
    @classmethod
    def _yields(cls, v: dict[int, float]) -> dict[int, float]:
        for year, kg in v.items():
            if not 2000 <= year <= 2100 or not 0 < kg <= 200_000:
                raise ValueError("declared yields are kg/ha > 0 per year 2000-2100")
        return v


def _urn(parcel_id: str) -> str:
    return parcel_id if parcel_id.startswith("urn:") else f"urn:ngsi-ld:AgriParcel:{parcel_id}"


def _overrides(items: list[OverrideIn], auth: AuthContext) -> tuple[Override, ...]:
    at = datetime.now(UTC).isoformat(timespec="seconds")
    out = []
    for item in items:
        if not farmer_may_override(item.param) and TECHNICIAN not in auth.roles:
            raise HTTPException(403, f"only a technical consultant may override {item.param}")
        try:
            check_override(item.param, item.value)
            out.append(Override(item.param, item.value, item.reason, auth.user_id, at))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    return tuple(out)


_ORGANIC_PARAM = re.compile(r"organic\.(0|[1-9][0-9]*)\.availability")


def _request(body: SheetIn, auth: AuthContext) -> SheetRequest:
    for item in body.overrides:
        m = _ORGANIC_PARAM.fullmatch(item.param)
        if m and int(m.group(1)) >= len(body.organic):
            raise HTTPException(422, f"{item.param} refers to an organic application that is not in the request")
    try:
        organic = tuple(OrganicApplication(**o.model_dump()) for o in body.organic)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    fields = body.model_dump(exclude={"parcel_ids", "organic", "overrides"})
    return SheetRequest(parcel_ids=tuple(_urn(p) for p in body.parcel_ids), organic=organic,
                        overrides=_overrides(body.overrides, auth), **fields)


@router.post("/calc/preview")
async def calc_preview(body: SheetIn, auth: AuthContext = require_auth(EDITOR_ROLES),
                       sources_factory=Depends(get_sources_factory)) -> dict:
    req = _request(body, auth)
    try:
        async with sources_factory(auth.tenant_id) as sources:
            assembled = await assemble(req, sources, date.today())
    except ParcelNotFound as exc:
        raise HTTPException(404, f"parcel not found: {exc.urn}") from exc
    result = calculate(assembled)
    logger.info("calc preview tenant=%s campaign=%s status=%s", auth.tenant_id, req.campaign,
                result.status)
    return result.to_dict()


CAMPAIGN_PARCELS_CONCURRENCY = 8


async def _parcel_summary(sources, entity: dict, campaign: int, today: date,
                          urn: str | None = None) -> dict:
    urn = urn or entity["id"]
    timeline, analyses = await asyncio.gather(sources.timeline(urn, today),
                                              sources.lab_analyses(urn))
    info = parcel_info(entity)
    cycles = list((timeline or {}).get("cycles") or [])
    choice = crops_for_campaign(cycles, campaign)
    main = campaign_main_cycles(cycles, campaign)
    return {
        "parcel": {"id": urn, "name": info.name, "area_ha": info.area_ha.to_dict(),
                   "identifier": info.identifier.to_dict(), "farm": info.farm,
                   "irrigation_regime": info.irrigation_regime},
        "crop": choice.crop.to_dict(), "previous_crop": choice.previous.to_dict(),
        "previous_campaign": choice.previous_campaign,
        "cycle": cycle_view(main[0] if main else None),
        "cover_before": cover_before(cycles, campaign),
        "notices": [n.to_dict() for n in (*info.notices, *choice.notices)],
        "analyses": [{"id": a.get("id"), "samplingDate": a.get("samplingDate"),
                      "laboratoryReference": a.get("laboratoryReference"),
                      "fields": sorted({k for h in a.get("horizons") or [] for k in h})}
                     for a in analyses],
    }


@router.get("/sources/parcels/{parcel_id}")
async def parcel_sources(parcel_id: Annotated[str, Path(pattern=PARCEL_ID_PATTERN, max_length=200)],
                         campaign: int = Query(ge=2000, le=2100),
                         auth: AuthContext = require_auth(PLAN_ROLES),
                         sources_factory=Depends(get_sources_factory)) -> dict:
    urn = _urn(parcel_id)
    async with sources_factory(auth.tenant_id) as sources:
        entity = await sources.parcel(urn)
        if entity is None:
            raise HTTPException(404, f"parcel not found: {urn}")
        return await _parcel_summary(sources, entity, campaign, date.today(), urn)


@router.get("/sources/campaigns/{campaign}/parcels")
async def campaign_parcels(campaign: Annotated[int, Path(ge=2000, le=2100)],
                           auth: AuthContext = require_auth(PLAN_ROLES),
                           sources_factory=Depends(get_sources_factory)) -> dict:
    started = time.monotonic()
    today = date.today()
    gate = asyncio.Semaphore(CAMPAIGN_PARCELS_CONCURRENCY)

    async def one(sources, entity: dict) -> dict:
        async with gate:
            body = await _parcel_summary(sources, entity, campaign, today)
        return {**body["parcel"], **{k: v for k, v in body.items() if k != "parcel"}}

    async with sources_factory(auth.tenant_id) as sources:
        entities = [e for e in await sources.parcels() if e.get("id")]
        # TaskGroup cancels the other parcels on the first failure, before the sources client
        # closes; the failure itself (e.g. a 503 naming its source) is re-raised unwrapped.
        try:
            async with asyncio.TaskGroup() as tg:
                tasks = [tg.create_task(one(sources, e)) for e in entities]
        except ExceptionGroup as group:
            raise group.exceptions[0] from None
        parcels = [t.result() for t in tasks]
    parcels = sorted(parcels, key=lambda p: (p["name"] is None, p["name"] or "", p["id"]))
    logger.info("campaign parcels tenant=%s campaign=%s count=%d ms=%d", auth.tenant_id,
                campaign, len(parcels), int((time.monotonic() - started) * 1000))
    return {"campaign": campaign, "parcels": parcels}


@router.get("/sources/crops")
async def source_crops(auth: AuthContext = require_auth(PLAN_ROLES),
                       sources_factory=Depends(get_sources_factory)) -> dict:
    """Crops the user can pick by name, in the order BioOrch gives (by Spanish name)."""
    async with sources_factory(auth.tenant_id) as sources:
        answer = await sources.crop_list()
    if not isinstance(answer, dict) or not isinstance(answer.get("crops"), list):
        raise SourceUnavailable("bioorch", "no crop list")
    crops = []
    for item in answer["crops"]:
        eppo, names = (item or {}).get("eppo"), (item or {}).get("names")
        if not isinstance(eppo, str) or not EPPO.match(eppo) or not isinstance(names, dict):
            logger.warning("crop list entry dropped eppo=%r", eppo)
            continue
        crops.append({"eppo": eppo, "names": names,
                      "has_coefficients": item.get("has_coefficients", True) is not False})
    return {"crops": crops}
