"""Plan use cases: each one locks the plan, checks its version, moves it through the state
machine and leaves an audit entry (spec §8, §9)."""
from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime

import asyncpg

from app.calc.assemble import SheetRequest, assemble, fetch_rain_normal
from app.calc.sheet import calculate
from app.calc.snapshot import assembled_to_dict
from app.inputs.organic import OrganicApplication
from app.inputs.overrides import check_override, farmer_may_override
from app.inputs.provenance import Override
from app.plans import repo
from app.plans.applications import ApplicationIn, split_findings, summarize
from app.plans.clock import legal_today
from app.plans.states import TECHNICIAN, Action, Guard, State, TransitionError, next_state
from app.rules import evaluate
from app.rules.context import PlanContext, SheetContext
from app.rules.es.annex3 import valid_adjustment
from app.rules.registry import RULES_VERSION, all_rules

logger = logging.getLogger(__name__)

_RAIN_STATES = {State.DRAFT, State.CALCULATED, State.IN_REVIEW}


class NotFound(LookupError):
    """No such plan or sheet in this tenant."""


class Conflict(Exception):
    """The plan changed since the client read it, or another open plan exists."""


class Invalid(ValueError):
    """A request that is well-formed but not acceptable for this plan (answered 422)."""


@dataclass(frozen=True)
class Actor:
    tenant_id: str
    user_id: str
    roles: frozenset[str]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


HISTORY_CAMPAIGNS = 4


def _history(sheet_parcels: list[dict], snapshots: dict[int, dict]) -> tuple[dict, ...]:
    urns = {p["urn"] for p in sheet_parcels}
    out = []
    for campaign in sorted(snapshots):
        for old in snapshots[campaign].get("sheets") or []:
            if urns & {p["urn"] for p in old.get("parcels") or []}:
                result, summary = old.get("result") or {}, old.get("applications_summary") or {}
                out.append({
                    "campaign": campaign,
                    "p2o5_planned_kg_ha": summary.get("p2o5_kg_ha"),
                    "p2o5_calculated_kg_ha": (result.get("p2o5") or {}).get("before_organic_kg_ha"),
                    "k2o_planned_kg_ha": summary.get("k2o_kg_ha"),
                    "k2o_calculated_kg_ha": (result.get("k2o") or {}).get("before_organic_kg_ha"),
                })
                break
    return tuple(out)


async def build_context(conn: asyncpg.Connection, plan: repo.PlanRow, at: date, *,
                        fresh: dict | None = None):
    """PlanContext from what the plan stores (or from `fresh` results, keyed by sheet id)."""
    sheets = await repo.get_sheets(conn, plan.id)
    stored = fresh if fresh is not None else await repo.get_results(conn, plan.id)
    previous = list(range(plan.campaign - HISTORY_CAMPAIGNS, plan.campaign))
    snapshots = await repo.signed_snapshots(conn, plan.tenant_id, plan.farm, previous)
    contexts = tuple(SheetContext(
        key=s.key, inputs=s.inputs, parcels=tuple(s.parcels), applications=tuple(s.applications),
        result=(stored.get(s.id) or {}).get("result"),
        summary=(stored.get(s.id) or {}).get("applications_summary"),
        history=_history(s.parcels, snapshots), n_adjustment=s.n_adjustment) for s in sheets)
    ctx = PlanContext(campaign=plan.campaign, sheets=contexts, rain=plan.rain,
                      vulnerable_zone=plan.vulnerable_zone,
                      voluntary_digital_notebook=plan.voluntary_digital_notebook, at=at)
    return ctx, sheets, stored


def rule_findings(ctx: PlanContext, sheets: list[repo.SheetRow]) -> list[dict]:
    ids = {s.key: s.id for s in sheets}
    return [{"rule_id": f.rule_id, "severity": f.severity,
             "params": {**f.params, "citation": f.citation},
             "sheet_id": ids.get(f.sheet_key)} for f in evaluate(all_rules(), ctx)]


async def _view(conn: asyncpg.Connection, plan: repo.PlanRow) -> dict:
    sheets = await repo.get_sheets(conn, plan.id)
    results = await repo.get_results(conn, plan.id)
    out_sheets = []
    for s in sheets:
        stored = results.get(s.id)
        out_sheets.append({
            "key": s.key, "seq": s.seq, "inputs": s.inputs, "overrides": s.overrides,
            "parcels": s.parcels, "applications": s.applications,
            "n_adjustment": s.n_adjustment,
            "result": stored["result"] if stored else None,
            "applications_summary": stored["applications_summary"] if stored else None,
        })
    findings = await repo.get_findings(conn, plan.id)
    rules_version = RULES_VERSION
    if plan.state in (State.SIGNED, State.SUPERSEDED) and plan.snapshot_sha256:
        # a signed plan shows the verdict it was sealed with, not today's rules
        sealed = await repo.get_snapshot(conn, plan.id) or {}
        rules_version = (sealed.get("versions") or {}).get("rules", rules_version)
        findings = [*(sealed.get("split_findings") or []),
                    *({"rule_id": f["rule_id"], "severity": f["severity"],
                       "params": {**f["params"], "citation": f["citation"]},
                       "sheet_key": f["sheet_key"]} for f in sealed.get("findings") or [])]
    return {
        "id": str(plan.id), "farm": plan.farm, "campaign": plan.campaign,
        "version": plan.version, "state": plan.state, "row_version": plan.row_version,
        "supersedes": str(plan.supersedes) if plan.supersedes else None,
        "calc_fresh": plan.calc_fresh, "calculated_at": _iso(plan.calculated_at),
        "rain_normal": plan.rain, "sheets": out_sheets,
        "findings": findings,
        "declarations": {"vulnerable_zone": plan.vulnerable_zone,
                         "vulnerable_zone_source": plan.vulnerable_zone_source,
                         "voluntary_digital_notebook": plan.voluntary_digital_notebook},
        "signature": plan.signature, "signed_at": _iso(plan.signed_at),
        "snapshot_sha256": plan.snapshot_sha256, "rules_version": rules_version,
    }


async def _load(conn: asyncpg.Connection, actor: Actor, plan_id: uuid.UUID, *,
                for_update: bool = False) -> repo.PlanRow:
    plan = await repo.get_plan(conn, actor.tenant_id, plan_id, for_update=for_update)
    if plan is None:
        raise NotFound(f"plan {plan_id}")
    return plan


def _same_version(plan: repo.PlanRow, row_version: int) -> None:
    if plan.row_version != row_version:
        raise Conflict(f"the plan changed (row_version is {plan.row_version}, "
                       f"the request read {row_version}); reload and retry")


async def create(pool: asyncpg.Pool, actor: Actor, campaign: int, farm: str) -> dict:
    async with pool.acquire() as conn, conn.transaction():
        try:
            plan = await repo.create_plan(conn, tenant_id=actor.tenant_id, farm=farm,
                                          campaign=campaign, user_id=actor.user_id)
        except repo.PlanExists as exc:
            raise Conflict(str(exc)) from exc
        await repo.append_audit(conn, plan.id, actor.user_id, "create",
                                {"campaign": campaign, "farm": farm})
        return await _view(conn, plan)


async def get(pool: asyncpg.Pool, actor: Actor, plan_id: uuid.UUID) -> dict:
    async with pool.acquire() as conn:
        return await _view(conn, await _load(conn, actor, plan_id))


async def list_(pool: asyncpg.Pool, actor: Actor, campaign: int | None) -> list[dict]:
    async with pool.acquire() as conn:
        plans = await repo.list_plans(conn, actor.tenant_id, campaign)
        return [{"id": str(p.id), "farm": p.farm, "campaign": p.campaign, "version": p.version,
                 "state": p.state, "row_version": p.row_version, "calc_fresh": p.calc_fresh,
                 "updated_at": _iso(p.updated_at)} for p in plans]


async def audit(pool: asyncpg.Pool, actor: Actor, plan_id: uuid.UUID) -> list[dict]:
    async with pool.acquire() as conn:
        plan = await _load(conn, actor, plan_id)
        return [{**e, "at": _iso(e["at"])} for e in await repo.get_audit(conn, plan.id)]


async def edit_sheets(pool: asyncpg.Pool, actor: Actor, plan_id: uuid.UUID, row_version: int,
                      sheets: list[repo.SheetData]) -> dict:
    async with pool.acquire() as conn, conn.transaction():
        plan = await _load(conn, actor, plan_id, for_update=True)
        _same_version(plan, row_version)
        target = next_state(plan.state, Action.EDIT, actor.roles, Guard(calc_fresh=plan.calc_fresh))
        for s in sheets:
            if s.inputs.get("campaign") != plan.campaign:
                raise Invalid(f"sheet {s.key} is for campaign {s.inputs.get('campaign')}, "
                                 f"the plan for {plan.campaign}")
        dropped = await repo.replace_sheets(conn, plan.id, sheets)
        plan = await repo.update_plan(conn, plan.id, state=target, inputs_changed=True)
        await repo.append_audit(conn, plan.id, actor.user_id, "edit_sheets",
                                {"sheets": [s.key for s in sheets], "dropped_overrides": dropped})
        return await _view(conn, plan)


def _may_override(actor: Actor, param: str) -> None:
    if not farmer_may_override(param) and TECHNICIAN not in actor.roles:
        raise TransitionError("forbidden", f"only a technical consultant may override {param}")


async def _edit_overrides(pool, actor, plan_id, row_version, key, param, change) -> dict:
    async with pool.acquire() as conn, conn.transaction():
        plan = await _load(conn, actor, plan_id, for_update=True)
        _same_version(plan, row_version)
        target = next_state(plan.state, Action.EDIT, actor.roles, Guard(calc_fresh=plan.calc_fresh))
        sheet = next((s for s in await repo.get_sheets(conn, plan.id) if s.key == key), None)
        if sheet is None:
            raise NotFound(f"sheet {key}")
        overrides, detail = change(sheet)
        await repo.set_overrides(conn, sheet.id, overrides)
        plan = await repo.update_plan(conn, plan.id, state=target, inputs_changed=True)
        await repo.append_audit(conn, plan.id, actor.user_id, detail.pop("action"),
                                {"sheet": key, "param": param, **detail})
        return await _view(conn, plan)


async def set_override(pool: asyncpg.Pool, actor: Actor, plan_id: uuid.UUID, row_version: int,
                       key: str, param: str, value: float | str | bool, reason: str) -> dict:
    _may_override(actor, param)
    try:
        check_override(param, value)
    except ValueError as exc:
        raise Invalid(str(exc)) from exc
    stamped = asdict(Override(param, value, reason, actor.user_id,
                              datetime.now(UTC).isoformat(timespec="seconds")))

    def change(sheet: repo.SheetRow):
        if param.startswith("organic."):
            index = int(param.split(".")[1])
            if index >= len(sheet.inputs.get("organic") or []):
                raise Invalid(f"{param} refers to an organic input the sheet does not have")
        kept = [o for o in sheet.overrides if o["param"] != param]
        return kept + [stamped], {"action": "set_override", "value": value,
                                  "reason": stamped["reason"]}

    return await _edit_overrides(pool, actor, plan_id, row_version, key, param, change)


async def delete_override(pool: asyncpg.Pool, actor: Actor, plan_id: uuid.UUID,
                          row_version: int, key: str, param: str) -> dict:
    _may_override(actor, param)

    def change(sheet: repo.SheetRow):
        kept = [o for o in sheet.overrides if o["param"] != param]
        if len(kept) == len(sheet.overrides):
            raise NotFound(f"override {param} in sheet {key}")
        return kept, {"action": "delete_override"}

    return await _edit_overrides(pool, actor, plan_id, row_version, key, param, change)


_ADJUSTMENT_FIELDS = ("basis", "date", "reference", "description", "justified_n_kg_ha")


async def set_n_adjustment(pool: asyncpg.Pool, actor: Actor, plan_id: uuid.UUID,
                           row_version: int, key: str, adjustment: dict | None) -> dict:
    """The technician's justified N adjustment for one sheet (annex III-I.3); None removes it."""
    if TECHNICIAN not in actor.roles:
        raise TransitionError("forbidden", f"only a technical consultant may adjust N "
                                           f"(needs {TECHNICIAN})")
    stamped = None
    if adjustment is not None:
        if not isinstance(adjustment, dict):
            raise Invalid("the adjustment must be an object")
        if valid_adjustment(adjustment, legal_today()) is None:
            raise Invalid("incomplete or future-dated justification")
        known = {k: adjustment.get(k) for k in _ADJUSTMENT_FIELDS}
        stamped = {**known, "user": actor.user_id,
                   "at": datetime.now(UTC).isoformat(timespec="seconds")}
    async with pool.acquire() as conn, conn.transaction():
        plan = await _load(conn, actor, plan_id, for_update=True)
        _same_version(plan, row_version)
        target = next_state(plan.state, Action.EDIT, actor.roles, Guard(calc_fresh=plan.calc_fresh))
        sheet = next((s for s in await repo.get_sheets(conn, plan.id) if s.key == key), None)
        if sheet is None:
            raise NotFound(f"sheet {key}")
        await repo.set_n_adjustment(conn, sheet.id, stamped)
        plan = await repo.update_plan(conn, plan.id, state=target, inputs_changed=True)
        detail = ({"sheet": key, "removed": True} if stamped is None else
                  {"sheet": key, "basis": stamped["basis"],
                   "justified_n_kg_ha": stamped["justified_n_kg_ha"]})
        await repo.append_audit(conn, plan.id, actor.user_id, "n_adjustment", detail)
        return await _view(conn, plan)


def _request(campaign: int, sheet: repo.SheetRow) -> SheetRequest:
    inputs = {k: v for k, v in sheet.inputs.items()
              if k not in ("campaign", "parcel_ids", "organic", "overrides")}
    for name in ("declared_yields", "previous_declared_yields"):
        inputs[name] = {int(year): float(kg) for year, kg in (inputs.get(name) or {}).items()}
    return SheetRequest(
        campaign=campaign,
        parcel_ids=tuple(p["urn"] for p in sheet.parcels),
        organic=tuple(OrganicApplication(**o) for o in sheet.inputs.get("organic") or []),
        overrides=tuple(Override(**o) for o in sheet.overrides),
        **inputs)


async def calculate_plan(pool: asyncpg.Pool, sources, actor: Actor, plan_id: uuid.UUID,
                         row_version: int, today: date) -> dict:
    async with pool.acquire() as conn:
        plan = await _load(conn, actor, plan_id)
        _same_version(plan, row_version)
        target = next_state(plan.state, Action.CALCULATE, actor.roles,
                            Guard(calc_fresh=plan.calc_fresh))
        sheets = await repo.get_sheets(conn, plan.id)
    if not sheets:
        raise Invalid("the plan has no crop sheets")

    rows, findings, statuses, versions = [], [], {}, {}
    for sheet in sheets:
        assembled = await assemble(_request(plan.campaign, sheet), sources, today)
        result = calculate(assembled).to_dict()
        organic = [OrganicApplication(**o) for o in sheet.inputs.get("organic") or []]
        apps = [ApplicationIn.model_validate(a) for a in sheet.applications]
        summary = summarize(apps, organic)
        if result["n"] is not None:
            findings += [{**f, "sheet_id": sheet.id} for f in split_findings(
                apps, organic, result["n"]["min_kg_ha"], result["n"]["max_kg_ha"])]
        rows.append((sheet.id, result, summary, assembled_to_dict(assembled)))
        statuses[sheet.key] = result["status"]
        versions[sheet.key] = result["versions"]

    async with pool.acquire() as conn, conn.transaction():
        plan = await _load(conn, actor, plan_id, for_update=True)
        _same_version(plan, row_version)
        fresh = {sid: {"result": r, "applications_summary": s} for sid, r, s, _ in rows}
        ctx, current, _ = await build_context(conn, plan, today, fresh=fresh)
        findings += rule_findings(ctx, current)
        await repo.save_results(conn, plan.id, rows, findings)
        plan = await repo.update_plan(conn, plan.id, state=target, calculated=True)
        await repo.append_audit(conn, plan.id, actor.user_id, "calculate",
                                {"status": statuses, "versions": versions,
                                 "rules": RULES_VERSION})
        logger.info("plan calculated tenant=%s plan=%s sheets=%d", actor.tenant_id, plan.id,
                    len(rows))
        return await _view(conn, plan)


async def set_declarations(pool, actor, plan_id, row_version, *, vulnerable_zone,
                           vulnerable_zone_source, voluntary_digital_notebook) -> dict:
    source = (vulnerable_zone_source or "").strip() or None
    if vulnerable_zone is False and source is None:
        raise Invalid("declaring the farm outside vulnerable zones needs its source")
    async with pool.acquire() as conn, conn.transaction():
        plan = await _load(conn, actor, plan_id, for_update=True)
        _same_version(plan, row_version)
        target = next_state(plan.state, Action.EDIT, actor.roles, Guard(calc_fresh=plan.calc_fresh))
        plan = await repo.set_declarations(conn, plan.id, vulnerable_zone=vulnerable_zone,
                                           vulnerable_zone_source=source,
                                           voluntary_digital_notebook=voluntary_digital_notebook)
        if target != State(plan.state):
            plan = await repo.update_plan(conn, plan.id, state=target)
        await repo.append_audit(conn, plan.id, actor.user_id, "declarations",
                                {"vulnerable_zone": vulnerable_zone, "source": source,
                                 "voluntary_digital_notebook": voluntary_digital_notebook})
        return await _view(conn, plan)


def _may_store_rain(plan: repo.PlanRow, actor: Actor) -> None:
    if State(plan.state) not in _RAIN_STATES:
        raise TransitionError("not_allowed", f"the plan is {plan.state}")
    if not ({"Farmer", TECHNICIAN} & actor.roles):
        raise TransitionError("forbidden", "only the farmer or the technician may do this")
    if State(plan.state) == State.IN_REVIEW and TECHNICIAN not in actor.roles:
        raise TransitionError("forbidden", "in review only the technician edits")


async def store_rain_normal(pool: asyncpg.Pool, sources, actor: Actor,
                            plan_id: uuid.UUID) -> dict:
    async with pool.acquire() as conn:
        plan = await _load(conn, actor, plan_id)
        sheets = await repo.get_sheets(conn, plan.id)
    _may_store_rain(plan, actor)
    parcel = next((p["urn"] for s in sheets for p in s.parcels), None)
    if parcel is None:
        raise Invalid("the plan has no parcels")
    normal = (await fetch_rain_normal(sources, parcel, plan.campaign)).to_dict()
    normal["parcel"] = parcel
    async with pool.acquire() as conn, conn.transaction():
        plan = await _load(conn, actor, plan_id, for_update=True)
        _may_store_rain(plan, actor)
        plan = await repo.set_rain(conn, plan.id, normal)
        await repo.append_audit(conn, plan.id, actor.user_id, "rain_normal",
                                {"parcel": parcel, "years": normal["years"]})
        return await _view(conn, plan)


async def transition(pool: asyncpg.Pool, actor: Actor, plan_id: uuid.UUID, row_version: int,
                     action: Action, comment: str | None = None) -> dict:
    if action == Action.RETURN and not (comment and comment.strip()):
        raise Invalid("returning a plan needs a comment")
    if action in (Action.SIGN, Action.CLOSE, Action.REVISE):
        raise TransitionError("not_allowed", "use the signing use cases")
    async with pool.acquire() as conn, conn.transaction():
        plan = await _load(conn, actor, plan_id, for_update=True)
        _same_version(plan, row_version)
        target = next_state(plan.state, action, actor.roles, Guard(calc_fresh=plan.calc_fresh))
        plan = await repo.update_plan(conn, plan.id, state=target)
        await repo.append_audit(conn, plan.id, actor.user_id, str(action),
                                {"comment": comment} if comment else {})
        return await _view(conn, plan)
