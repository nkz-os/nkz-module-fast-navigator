"""Plans API (spec §9): plans, crop sheets, overrides, calculation and review round."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, Field, model_validator

from app.api import PLAN_ROLES, SheetIn, _urn, get_sources_factory
from app.db.pool import get_db
from app.inputs.organic import OrganicApplication
from app.inputs.parcel import is_parcel_identifier
from app.middleware import AuthContext, require_auth
from app.plans import repo, service, signing
from app.plans.applications import ApplicationIn
from app.plans.clock import legal_today
from app.plans.states import Action

router = APIRouter(prefix="/plans", tags=["FaST plans"])

WRITE_ROLES = ["Farmer", "TechnicalConsultant"]
SIGN_ROLES = ["TechnicalConsultant"]
FARM_PATTERN = r"^(tenant|urn:ngsi-ld:AgriFarm:[A-Za-z0-9._:-]+)$"
KEY_PATTERN = r"^[a-z0-9-]{1,40}$"
PARAM_PATTERN = r"^[a-z_]+(\.[a-z0-9_]+){1,2}$"


class PlanCreate(BaseModel):
    campaign: int = Field(ge=2000, le=2100)
    farm: str = Field(default="tenant", pattern=FARM_PATTERN, max_length=200)


class PlanSheetIn(SheetIn):
    key: str = Field(pattern=KEY_PATTERN)
    applications: list[ApplicationIn] = Field(default_factory=list, max_length=50)
    sigpac: dict[Annotated[str, Field(max_length=200)], Annotated[str, Field(max_length=200)]] = (
        Field(default_factory=dict, max_length=200))

    @model_validator(mode="after")
    def _consistent(self) -> PlanSheetIn:
        if self.overrides:
            raise ValueError("overrides are set through /sheets/{key}/overrides/{param}")
        urns = [_urn(p) for p in self.parcel_ids]
        if len(set(urns)) != len(urns):
            raise ValueError("a parcel appears twice in the sheet")
        if len({_urn(p) for p in self.sigpac}) != len(self.sigpac):
            raise ValueError("sigpac gives one parcel twice")
        for parcel, value in self.sigpac.items():
            if _urn(parcel) not in urns:
                raise ValueError(f"sigpac given for {parcel}, which is not in the sheet")
            if not is_parcel_identifier(value):
                raise ValueError(f"{value!r} is not a SIGPAC recinto or cadastral reference")
        for item in self.organic:
            OrganicApplication(**item.model_dump())     # its ValueError becomes a 422
        for app in self.applications:
            if app.organic_index is not None and app.organic_index >= len(self.organic):
                raise ValueError(f"organic_index {app.organic_index} is not an organic input")
        return self


class SheetsPut(BaseModel):
    row_version: int
    sheets: list[PlanSheetIn] = Field(max_length=20)

    @model_validator(mode="after")
    def _unique_keys(self) -> SheetsPut:
        keys = [s.key for s in self.sheets]
        if len(set(keys)) != len(keys):
            raise ValueError("sheet keys must be unique")
        return self


class OverridePut(BaseModel):
    row_version: int
    value: bool | float | Annotated[str, Field(max_length=64)]
    reason: str = Field(min_length=1, max_length=500)


class RowVersion(BaseModel):
    row_version: int


class ReturnIn(BaseModel):
    row_version: int
    comment: str = Field(min_length=1, max_length=2000)


def _actor(auth: AuthContext) -> service.Actor:
    return service.Actor(auth.tenant_id, auth.user_id, frozenset(auth.roles))


def _sheet_data(sheet: PlanSheetIn) -> repo.SheetData:
    inputs = sheet.model_dump(mode="json",
                              exclude={"key", "applications", "sigpac", "overrides", "parcel_ids"})
    declared = {_urn(k): v.strip().upper() for k, v in sheet.sigpac.items()}
    parcels = tuple((_urn(p), declared.get(_urn(p))) for p in sheet.parcel_ids)
    return repo.SheetData(sheet.key, inputs, parcels,
                          tuple(a.model_dump(mode="json") for a in sheet.applications))


@router.get("")
async def list_plans(campaign: int | None = Query(default=None, ge=2000, le=2100),
                     auth: AuthContext = require_auth(PLAN_ROLES), pool=Depends(get_db)) -> list:
    return await service.list_(pool, _actor(auth), campaign)


@router.post("", status_code=201)
async def create_plan(body: PlanCreate, auth: AuthContext = require_auth(WRITE_ROLES),
                      pool=Depends(get_db)) -> dict:
    return await service.create(pool, _actor(auth), body.campaign, body.farm)


@router.get("/{plan_id}")
async def get_plan(plan_id: uuid.UUID, auth: AuthContext = require_auth(PLAN_ROLES),
                   pool=Depends(get_db)) -> dict:
    return await service.get(pool, _actor(auth), plan_id)


@router.get("/{plan_id}/audit")
async def plan_audit(plan_id: uuid.UUID, auth: AuthContext = require_auth(PLAN_ROLES),
                     pool=Depends(get_db)) -> list:
    return await service.audit(pool, _actor(auth), plan_id)


@router.put("/{plan_id}/sheets")
async def put_sheets(plan_id: uuid.UUID, body: SheetsPut,
                     auth: AuthContext = require_auth(WRITE_ROLES), pool=Depends(get_db)) -> dict:
    return await service.edit_sheets(pool, _actor(auth), plan_id, body.row_version,
                                     [_sheet_data(s) for s in body.sheets])


@router.put("/{plan_id}/sheets/{key}/overrides/{param}")
async def put_override(plan_id: uuid.UUID, body: OverridePut,
                       key: str = Path(pattern=KEY_PATTERN),
                       param: str = Path(pattern=PARAM_PATTERN, max_length=64),
                       auth: AuthContext = require_auth(WRITE_ROLES), pool=Depends(get_db)) -> dict:
    return await service.set_override(pool, _actor(auth), plan_id, body.row_version, key, param,
                                      body.value, body.reason)


@router.delete("/{plan_id}/sheets/{key}/overrides/{param}")
async def delete_override(plan_id: uuid.UUID, row_version: int = Query(),
                          key: str = Path(pattern=KEY_PATTERN),
                          param: str = Path(pattern=PARAM_PATTERN, max_length=64),
                          auth: AuthContext = require_auth(WRITE_ROLES),
                          pool=Depends(get_db)) -> dict:
    return await service.delete_override(pool, _actor(auth), plan_id, row_version, key, param)


class NAdjustmentPut(BaseModel):
    row_version: int
    basis: Literal["foliar_analysis", "other_technique", "year_evolution"]
    date: dt.date
    reference: str | None = Field(default=None, max_length=200)
    description: str = Field(min_length=1, max_length=1000)
    justified_n_kg_ha: float = Field(gt=0, le=1000)


@router.put("/{plan_id}/sheets/{key}/n-adjustment")
async def put_n_adjustment(plan_id: uuid.UUID, body: NAdjustmentPut,
                           key: str = Path(pattern=KEY_PATTERN),
                           auth: AuthContext = require_auth(WRITE_ROLES),
                           pool=Depends(get_db)) -> dict:
    adj = body.model_dump(exclude={"row_version"}, mode="json")
    return await service.set_n_adjustment(pool, _actor(auth), plan_id, body.row_version, key, adj)


@router.delete("/{plan_id}/sheets/{key}/n-adjustment")
async def delete_n_adjustment(plan_id: uuid.UUID, row_version: int = Query(),
                              key: str = Path(pattern=KEY_PATTERN),
                              auth: AuthContext = require_auth(WRITE_ROLES),
                              pool=Depends(get_db)) -> dict:
    return await service.set_n_adjustment(pool, _actor(auth), plan_id, row_version, key, None)


@router.post("/{plan_id}/calculate")
async def calculate_plan(plan_id: uuid.UUID, body: RowVersion,
                         auth: AuthContext = require_auth(WRITE_ROLES), pool=Depends(get_db),
                         sources_factory=Depends(get_sources_factory)) -> dict:
    async with sources_factory(auth.tenant_id) as sources:
        return await service.calculate_plan(pool, sources, _actor(auth), plan_id,
                                            body.row_version, legal_today())


@router.post("/{plan_id}/rain-normal")
async def rain_normal(plan_id: uuid.UUID, auth: AuthContext = require_auth(WRITE_ROLES),
                      pool=Depends(get_db), sources_factory=Depends(get_sources_factory)) -> dict:
    async with sources_factory(auth.tenant_id) as sources:
        return await service.store_rain_normal(pool, sources, _actor(auth), plan_id)


@router.post("/{plan_id}/submit")
async def submit(plan_id: uuid.UUID, body: RowVersion,
                 auth: AuthContext = require_auth(WRITE_ROLES), pool=Depends(get_db)) -> dict:
    return await service.transition(pool, _actor(auth), plan_id, body.row_version, Action.SUBMIT)


@router.post("/{plan_id}/return")
async def return_plan(plan_id: uuid.UUID, body: ReturnIn,
                      auth: AuthContext = require_auth(WRITE_ROLES), pool=Depends(get_db)) -> dict:
    return await service.transition(pool, _actor(auth), plan_id, body.row_version, Action.RETURN,
                                    comment=body.comment)


class DeclarationsPut(BaseModel):
    row_version: int
    vulnerable_zone: bool | None = None
    vulnerable_zone_source: str | None = Field(default=None, max_length=500)
    voluntary_digital_notebook: bool = False


class CloseIn(BaseModel):
    row_version: int
    closure_basis: Literal["titular_cualificado", "titular_sin_obligacion"]
    signer_name: str = Field(min_length=1, max_length=200)


@router.put("/{plan_id}/declarations")
async def put_declarations(plan_id: uuid.UUID, body: DeclarationsPut,
                           auth: AuthContext = require_auth(WRITE_ROLES),
                           pool=Depends(get_db)) -> dict:
    return await service.set_declarations(
        pool, _actor(auth), plan_id, body.row_version, vulnerable_zone=body.vulnerable_zone,
        vulnerable_zone_source=body.vulnerable_zone_source,
        voluntary_digital_notebook=body.voluntary_digital_notebook)


@router.post("/{plan_id}/sign")
async def sign_plan(plan_id: uuid.UUID, body: RowVersion,
                    auth: AuthContext = require_auth(SIGN_ROLES), pool=Depends(get_db)) -> dict:
    return await signing.sign(pool, _actor(auth), plan_id, body.row_version, legal_today())


@router.post("/{plan_id}/close")
async def close_plan(plan_id: uuid.UUID, body: CloseIn,
                     auth: AuthContext = require_auth(WRITE_ROLES), pool=Depends(get_db)) -> dict:
    return await signing.close(pool, _actor(auth), plan_id, body.row_version, body.closure_basis,
                               body.signer_name, legal_today())


@router.post("/{plan_id}/revise", status_code=201)
async def revise_plan(plan_id: uuid.UUID, body: RowVersion,
                      auth: AuthContext = require_auth(WRITE_ROLES), pool=Depends(get_db)) -> dict:
    return await signing.revise(pool, _actor(auth), plan_id, body.row_version)


advisors_router = APIRouter(prefix="/advisors", tags=["FaST advisors"])


class AdvisorPut(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    registration_number: str = Field(min_length=1, max_length=64)


@advisors_router.get("/me")
async def my_advisor(auth: AuthContext = require_auth(SIGN_ROLES), pool=Depends(get_db)) -> dict:
    found = await signing.get_advisor(pool, _actor(auth))
    if found is None:
        raise service.NotFound("no advisor profile yet")
    return found


@advisors_router.put("/me")
async def put_my_advisor(body: AdvisorPut, auth: AuthContext = require_auth(SIGN_ROLES),
                         pool=Depends(get_db)) -> dict:
    return await signing.put_advisor(pool, _actor(auth), body.name, body.registration_number)


holder_router = APIRouter(prefix="/holder-qualification", tags=["FaST holder"])


class HolderQualificationPut(BaseModel):
    holder_name: str = Field(min_length=1, max_length=200)
    qualification: str = Field(min_length=1, max_length=200)
    reference: str = Field(min_length=1, max_length=200)


@holder_router.get("")
async def get_holder_qualification(auth: AuthContext = require_auth(WRITE_ROLES),
                                   pool=Depends(get_db)) -> dict:
    found = await signing.get_holder_qualification(pool, _actor(auth))
    if found is None:
        raise service.NotFound("no holder qualification recorded")
    return found


@holder_router.put("")
async def put_holder_qualification(body: HolderQualificationPut,
                                   auth: AuthContext = require_auth(SIGN_ROLES),
                                   pool=Depends(get_db)) -> dict:
    return await signing.put_holder_qualification(pool, _actor(auth), body.holder_name,
                                                  body.qualification, body.reference)
