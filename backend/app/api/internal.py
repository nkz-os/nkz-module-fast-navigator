"""
FaST Navigator Backend - Internal Routes

Called by in-cluster services (the field notebook), NEVER by the browser, so
these routes bypass api-gateway and carry no X-Tenant-ID / X-User-ID headers.
They authenticate via X-Internal-Service-Secret instead
(see app.middleware.verify_internal_secret).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query

from app.api import PARCEL_ID_PATTERN, _urn
from app.db.pool import get_db
from app.middleware import verify_internal_secret
from app.plans import nutrient_status as nutrient_status_mod
from app.plans import signing

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(verify_internal_secret)])


@router.get("/plans/summary")
async def plan_summary(tenant_id: str = Query(min_length=1, max_length=100),
                       parcel_id: str = Query(pattern=PARCEL_ID_PATTERN, max_length=200),
                       campaign: int = Query(ge=2000, le=2100),
                       pool=Depends(get_db)) -> dict:
    """Signed plan summary for the field notebook (spec 5.3, art. 5.1.a)."""
    return await signing.summary(pool, tenant_id, _urn(parcel_id), campaign)


@router.get("/parcels/{parcel_id}/nutrient-status")
async def nutrient_status(parcel_id: str = Path(pattern=PARCEL_ID_PATTERN, max_length=200),
                          tenant_id: str = Query(min_length=1, max_length=100),
                          campaign: int = Query(ge=2000, le=2100),
                          pool=Depends(get_db)) -> dict:
    """Stored nutrient results of a parcel; read-only, never recalculated. `plan: null` = none."""
    return await nutrient_status_mod.nutrient_status(pool, tenant_id, _urn(parcel_id), campaign)
