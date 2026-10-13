"""Signature (advisor), closure by the holder (D1), revision and the frozen copy (spec §8)."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, date, datetime

import asyncpg

from app.calc.sheet import CALC_VERSION, calculate
from app.calc.snapshot import assembled_from_dict, sha256_of
from app.engine import ENGINE_VERSION
from app.inputs.organic import ORGANIC_TABLE_VERSION
from app.plans import repo
from app.plans.service import (
    Actor,
    Conflict,
    Invalid,
    NotFound,
    _load,
    _same_version,
    _view,
    build_context,
)
from app.plans.states import TECHNICIAN, Action, Guard, TransitionError, next_state
from app.rules import BLOCK, count_blocking, evaluate
from app.rules.es.advice import advice_required
from app.rules.registry import RULES_VERSION, all_rules

logger = logging.getLogger(__name__)

CLOSURE_BASES = ("titular_cualificado", "titular_sin_obligacion")


async def get_advisor(pool: asyncpg.Pool, actor: Actor) -> dict | None:
    async with pool.acquire() as conn:
        return await repo.get_advisor(conn, actor.tenant_id, actor.user_id)


async def put_advisor(pool: asyncpg.Pool, actor: Actor, name: str,
                      registration_number: str) -> dict:
    name, number = (name or "").strip(), (registration_number or "").strip()
    if not name or not number:
        raise Invalid("an advisor needs a name and a registration number (art. 21)")
    async with pool.acquire() as conn:
        return await repo.put_advisor(conn, actor.tenant_id, actor.user_id, name, number)


async def _freeze(conn, plan: repo.PlanRow, ctx, sheets, stored, signature: dict) -> dict:
    findings = [f.to_dict() for f in evaluate(all_rules(), ctx)]
    return {
        "plan": {"id": str(plan.id), "campaign": plan.campaign, "farm": plan.farm,
                 "version": plan.version},
        "declarations": {"vulnerable_zone": plan.vulnerable_zone,
                         "vulnerable_zone_source": plan.vulnerable_zone_source,
                         "voluntary_digital_notebook": plan.voluntary_digital_notebook},
        "rain": plan.rain,
        "sheets": [{"key": s.key, "inputs": s.inputs, "overrides": s.overrides,
                    "parcels": s.parcels, "applications": s.applications,
                    "result": (stored.get(s.id) or {}).get("result"),
                    "applications_summary": (stored.get(s.id) or {}).get("applications_summary"),
                    "assembled": (stored.get(s.id) or {}).get("assembled")} for s in sheets],
        "findings": findings,
        "versions": {"engine": ENGINE_VERSION, "calc": CALC_VERSION, "rules": RULES_VERSION,
                     "organic_table": ORGANIC_TABLE_VERSION,
                     "coefficients": {s.key: ((stored.get(s.id) or {}).get("result") or {})
                                      .get("versions", {}).get("coefficients") for s in sheets}},
        "signature": signature,
    }


async def _finish(conn, actor, plan, action: Action, guard_extra: dict, signature: dict,
                  today: date) -> dict:
    ctx, sheets, stored = await build_context(conn, plan, today)
    findings = evaluate(all_rules(), ctx)          # judged again at the signature date
    guard = Guard(calc_fresh=plan.calc_fresh, blocking_findings=count_blocking(findings),
                  close_allowed=guard_extra.get("close_allowed", False))
    try:
        next_state(plan.state, action, actor.roles, guard)
    except TransitionError as exc:
        if exc.code != "blocking_findings":
            raise
        blocking = sorted({f.rule_id for f in findings if f.severity == BLOCK})
        raise TransitionError("blocking_findings", f"blocking findings: {blocking}") from exc
    signed_at = datetime.now(UTC).replace(microsecond=0)      # one clock: seal and column
    signature = {**signature, "signed_at": signed_at.isoformat(timespec="seconds")}
    snapshot = await _freeze(conn, plan, ctx, sheets, stored, signature)
    seal = sha256_of(snapshot)
    plan = await repo.sign_plan(conn, plan.id, signature=signature, snapshot=snapshot, sha256=seal,
                                signed_at=signed_at)
    await repo.append_audit(conn, plan.id, actor.user_id, str(action),
                            {"sha256": seal, "rules": RULES_VERSION,
                             "findings": {s: sum(1 for f in findings if f.severity == s)
                                          for s in ("block", "warn", "info")}})
    logger.info("plan %s tenant=%s plan=%s", action, actor.tenant_id, plan.id)
    return await _view(conn, plan)


async def sign(pool: asyncpg.Pool, actor: Actor, plan_id: uuid.UUID, row_version: int,
               today: date) -> dict:
    async with pool.acquire() as conn, conn.transaction():
        plan = await _load(conn, actor, plan_id, for_update=True)
        _same_version(plan, row_version)
        if TECHNICIAN not in actor.roles:
            raise TransitionError("forbidden", f"sign needs one of {[TECHNICIAN]}")
        advisor = await repo.get_advisor(conn, actor.tenant_id, actor.user_id)
        if advisor is None:
            raise Invalid("set your advisor profile (name and registration number) first")
        return await _finish(conn, actor, plan, Action.SIGN, {},
                             {"kind": "advisor", "user_id": actor.user_id, **advisor}, today)


async def close(pool: asyncpg.Pool, actor: Actor, plan_id: uuid.UUID, row_version: int,
                basis: str, signer_name: str, today: date) -> dict:
    name = (signer_name or "").strip()
    if basis not in CLOSURE_BASES or not name:
        raise Invalid(f"closing needs a basis ({', '.join(CLOSURE_BASES)}) and the holder's name")
    async with pool.acquire() as conn, conn.transaction():
        plan = await _load(conn, actor, plan_id, for_update=True)
        _same_version(plan, row_version)
        ctx, _, _ = await build_context(conn, plan, today)
        allowed = basis == "titular_cualificado" or not advice_required(ctx)
        return await _finish(conn, actor, plan, Action.CLOSE, {"close_allowed": allowed},
                             {"kind": "holder", "user_id": actor.user_id, "name": name,
                              "closure_basis": basis}, today)


async def revise(pool: asyncpg.Pool, actor: Actor, plan_id: uuid.UUID, row_version: int) -> dict:
    async with pool.acquire() as conn, conn.transaction():
        plan = await _load(conn, actor, plan_id, for_update=True)
        _same_version(plan, row_version)
        target = next_state(plan.state, Action.REVISE, actor.roles, Guard(calc_fresh=True))
        await repo.update_plan(conn, plan.id, state=target)
        try:
            new = await repo.create_plan(
                conn, tenant_id=plan.tenant_id, farm=plan.farm, campaign=plan.campaign,
                user_id=actor.user_id, version=plan.version + 1, supersedes=plan.id,
                declarations={"vulnerable_zone": plan.vulnerable_zone,
                              "vulnerable_zone_source": plan.vulnerable_zone_source,
                              "voluntary_digital_notebook": plan.voluntary_digital_notebook},
                rain=plan.rain)
        except repo.PlanExists as exc:
            raise Conflict(str(exc)) from exc
        await repo.copy_plan_inputs(conn, plan.id, new.id)
        await repo.append_audit(conn, plan.id, actor.user_id, "revise", {"new_plan": str(new.id)})
        await repo.append_audit(conn, new.id, actor.user_id, "create",
                                {"revised_from": str(plan.id), "version": new.version})
        return await _view(conn, new)


def _sheet_summary(sheet: dict) -> dict:
    result = sheet.get("result") or {}
    inputs = result.get("inputs") or {}
    n = result.get("n") or {}
    return {"key": sheet["key"],
            "crop_eppo": (inputs.get("crop.eppo") or {}).get("value"),
            "previous_crop_eppo": (inputs.get("previous_crop.eppo") or {}).get("value"),
            "expected_yield_kg_ha": (inputs.get("yield.kg_ha") or {}).get("value"),
            "n_kg_ha": {"min": n.get("min_kg_ha"), "avg": n.get("avg_kg_ha"),
                        "max": n.get("max_kg_ha")},
            "p2o5_kg_ha": (result.get("p2o5") or {}).get("rate_kg_ha"),
            "k2o_kg_ha": (result.get("k2o") or {}).get("rate_kg_ha")}


async def summary(pool: asyncpg.Pool, tenant_id: str, parcel_urn: str, campaign: int) -> dict:
    async with pool.acquire() as conn:
        plans = await repo.signed_plans_for_campaign(conn, tenant_id, campaign)
    for plan, snapshot in plans:
        sheets = [s for s in snapshot.get("sheets") or []
                  if parcel_urn in {p["urn"] for p in s.get("parcels") or []}]
        if sheets:
            signature = {k: v for k, v in (plan.signature or {}).items() if k != "user_id"}
            return {"plan_id": str(plan.id), "version": plan.version, "campaign": plan.campaign,
                    "signed_at": plan.signed_at.isoformat() if plan.signed_at else None,
                    "snapshot_sha256": plan.snapshot_sha256, "signature": signature,
                    "sheets": [_sheet_summary(s) for s in sheets]}
    raise NotFound(f"no signed plan for {parcel_urn} in campaign {campaign}")


def verify_snapshot(snapshot: dict) -> list[str]:
    """Sheets whose recalculation from the frozen inputs does not give the frozen result."""
    bad = []
    for sheet in snapshot.get("sheets") or []:
        assembled = sheet.get("assembled")
        if assembled is None:
            bad.append(sheet["key"])
            continue
        again = json.loads(json.dumps(calculate(assembled_from_dict(assembled)).to_dict()))
        if again != sheet.get("result"):          # compared as stored JSON (tuples → lists)
            bad.append(sheet["key"])
    return bad
