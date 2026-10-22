"""Planned versus realized for one plan: loads the document and the notebook, computes (spec §11).
Nothing is stored."""
from __future__ import annotations

import asyncio
import uuid
from datetime import date

import asyncpg

from app.compliance.compute import HISTORY_CAMPAIGNS
from app.compliance.compute import compliance as compute_compliance
from app.compliance.realized import parse_operation
from app.plans import repo
from app.plans.document import plan_document
from app.plans.service import Actor, _load


async def compliance(pool: asyncpg.Pool, sources, actor: Actor, plan_id: uuid.UUID,
                     today: date) -> dict:
    async with pool.acquire() as conn:
        plan = await _load(conn, actor, plan_id)
        document = await plan_document(conn, plan)
        previous = await repo.signed_snapshots(
            conn, plan.tenant_id, plan.farm,
            list(range(plan.campaign - HISTORY_CAMPAIGNS, plan.campaign)))
    urns = sorted({p["urn"] for s in document["sheets"] for p in s["parcels"]})
    fetched = await asyncio.gather(*(sources.fertilizations(u) for u in urns))
    realized = {urn: [parse_operation(e) for e in entities]
                for urn, entities in zip(urns, fetched, strict=True)}
    return compute_compliance(document, previous, realized, today)
