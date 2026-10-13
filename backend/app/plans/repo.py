"""Storage of plans, crop sheets, parcels, applications, results, findings and audit (spec §9)."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime

import asyncpg

_PLAN_COLUMNS = ("id, tenant_id, farm, campaign, version, state, supersedes, row_version, "
                 "inputs_changed_at, calculated_at, rain, created_by, created_at, updated_at")
_ORGANIC_PARAM = re.compile(r"organic\.(0|[1-9][0-9]*)\.availability")


class PlanExists(Exception):
    """Another open plan exists for the same farm and campaign."""


@dataclass(frozen=True)
class PlanRow:
    id: uuid.UUID
    tenant_id: str
    farm: str
    campaign: int
    version: int
    state: str
    supersedes: uuid.UUID | None
    row_version: int
    inputs_changed_at: datetime
    calculated_at: datetime | None
    rain: dict | None
    created_by: str
    created_at: datetime
    updated_at: datetime

    @property
    def calc_fresh(self) -> bool:
        return self.calculated_at is not None and self.calculated_at >= self.inputs_changed_at


@dataclass(frozen=True)
class SheetData:
    key: str
    inputs: dict
    parcels: tuple[tuple[str, str | None], ...]     # (parcel URN, declared SIGPAC/cadastral id)
    applications: tuple[dict, ...]


@dataclass(frozen=True)
class SheetRow:
    id: uuid.UUID
    key: str
    seq: int
    inputs: dict
    overrides: list[dict]
    parcels: list[dict]
    applications: list[dict]


def _plan(row: asyncpg.Record) -> PlanRow:
    return PlanRow(**dict(row))


async def create_plan(conn: asyncpg.Connection, *, tenant_id: str, farm: str, campaign: int,
                      user_id: str, version: int = 1,
                      supersedes: uuid.UUID | None = None) -> PlanRow:
    try:
        row = await conn.fetchrow(
            f"INSERT INTO plans (id, tenant_id, farm, campaign, version, state, supersedes, "
            f"created_by) VALUES ($1, $2, $3, $4, $5, 'draft', $6, $7) RETURNING {_PLAN_COLUMNS}",
            uuid.uuid4(), tenant_id, farm, campaign, version, supersedes, user_id)
    except asyncpg.UniqueViolationError as exc:
        raise PlanExists(f"an open plan exists for {farm} and campaign {campaign}") from exc
    return _plan(row)


async def get_plan(conn: asyncpg.Connection, tenant_id: str, plan_id: uuid.UUID, *,
                   for_update: bool = False) -> PlanRow | None:
    lock = " FOR UPDATE" if for_update else ""
    row = await conn.fetchrow(
        f"SELECT {_PLAN_COLUMNS} FROM plans WHERE tenant_id = $1 AND id = $2{lock}",
        tenant_id, plan_id)
    return _plan(row) if row else None


async def list_plans(conn: asyncpg.Connection, tenant_id: str,
                     campaign: int | None = None) -> list[PlanRow]:
    if campaign is None:
        rows = await conn.fetch(f"SELECT {_PLAN_COLUMNS} FROM plans WHERE tenant_id = $1 "
                                "ORDER BY campaign DESC, version DESC", tenant_id)
    else:
        rows = await conn.fetch(f"SELECT {_PLAN_COLUMNS} FROM plans WHERE tenant_id = $1 "
                                "AND campaign = $2 ORDER BY version DESC", tenant_id, campaign)
    return [_plan(r) for r in rows]


async def update_plan(conn: asyncpg.Connection, plan_id: uuid.UUID, *, state: str,
                      inputs_changed: bool = False, calculated: bool = False) -> PlanRow:
    row = await conn.fetchrow(
        f"UPDATE plans SET state = $2, row_version = row_version + 1, updated_at = now(), "
        f"inputs_changed_at = CASE WHEN $3 THEN clock_timestamp() ELSE inputs_changed_at END, "
        f"calculated_at = CASE WHEN $4 THEN clock_timestamp() ELSE calculated_at END "
        f"WHERE id = $1 RETURNING {_PLAN_COLUMNS}", plan_id, state, inputs_changed, calculated)
    return _plan(row)


async def set_rain(conn: asyncpg.Connection, plan_id: uuid.UUID, rain: dict) -> PlanRow:
    row = await conn.fetchrow(
        f"UPDATE plans SET rain = $2, row_version = row_version + 1, updated_at = now() "
        f"WHERE id = $1 RETURNING {_PLAN_COLUMNS}", plan_id, rain)
    return _plan(row)


def _organic_key(item: dict) -> tuple:
    """What an organic input is for the availability override: the material and its composition
    (the dose does not change how much of its N is available)."""
    return (item.get("material"), item.get("n_pct"), item.get("p2o5_pct"), item.get("k2o_pct"))


def _carry_overrides(key: str, old_inputs: dict, old_overrides: list[dict],
                     new_inputs: dict) -> tuple[list[dict], list[dict]]:
    """Overrides of the new sheet, and the dropped ones. An organic override follows its input
    (matched by content, first unused match in order), not its list position."""
    old_organic = old_inputs.get("organic") or []
    new_organic = new_inputs.get("organic") or []
    new_index: dict[int, int] = {}
    used: set[int] = set()
    for i, item in enumerate(old_organic):
        for j, candidate in enumerate(new_organic):
            if j not in used and _organic_key(candidate) == _organic_key(item):
                used.add(j)
                new_index[i] = j
                break
    kept, dropped = [], []
    for override in old_overrides:
        match = _ORGANIC_PARAM.fullmatch(override["param"])
        if not match:
            kept.append(override)
        elif int(match.group(1)) in new_index:
            kept.append({**override, "param": f"organic.{new_index[int(match.group(1))]}"
                                              ".availability"})
        else:
            dropped.append({"sheet": key, "param": override["param"], "value": override["value"],
                            "user": override["user"]})
    return kept, dropped


async def replace_sheets(conn: asyncpg.Connection, plan_id: uuid.UUID,
                         sheets: list[SheetData]) -> list[dict]:
    """Make the plan's sheets exactly `sheets`. A kept key keeps its id and its overrides; an
    organic override follows its input, and those of inputs that no longer exist are dropped
    and returned (sheet, param, value, user) for the audit."""
    existing = {r["key"]: r for r in await conn.fetch(
        "SELECT id, key, inputs, overrides FROM crop_sheets WHERE plan_id = $1", plan_id)}
    keys = [s.key for s in sheets]
    await conn.execute("DELETE FROM crop_sheets WHERE plan_id = $1 AND NOT (key = ANY($2::text[]))",
                       plan_id, keys)
    await conn.execute("UPDATE crop_sheets SET seq = -seq - 1 WHERE plan_id = $1", plan_id)
    dropped: list[dict] = []
    for seq, sheet in enumerate(sheets):
        if sheet.key in existing:
            old = existing[sheet.key]
            sheet_id = old["id"]
            kept, lost = _carry_overrides(sheet.key, old["inputs"], old["overrides"], sheet.inputs)
            dropped += lost
            await conn.execute("UPDATE crop_sheets SET seq = $2, inputs = $3, overrides = $4 "
                               "WHERE id = $1", sheet_id, seq, sheet.inputs, kept)
        else:
            sheet_id = uuid.uuid4()
            await conn.execute("INSERT INTO crop_sheets (id, plan_id, key, seq, inputs) "
                               "VALUES ($1, $2, $3, $4, $5)", sheet_id, plan_id, sheet.key, seq,
                               sheet.inputs)
        await conn.execute("DELETE FROM sheet_parcels WHERE sheet_id = $1", sheet_id)
        await conn.executemany(
            "INSERT INTO sheet_parcels (sheet_id, ord, parcel_urn, sigpac) "
            "VALUES ($1, $2, $3, $4)",
            [(sheet_id, i, urn, sigpac) for i, (urn, sigpac) in enumerate(sheet.parcels)])
        await conn.execute("DELETE FROM applications WHERE sheet_id = $1", sheet_id)
        await conn.executemany(
            "INSERT INTO applications (id, sheet_id, seq, data) VALUES ($1, $2, $3, $4)",
            [(uuid.uuid4(), sheet_id, i, a) for i, a in enumerate(sheet.applications)])
    return dropped


async def get_sheets(conn: asyncpg.Connection, plan_id: uuid.UUID) -> list[SheetRow]:
    rows = await conn.fetch("SELECT id, key, seq, inputs, overrides FROM crop_sheets "
                            "WHERE plan_id = $1 ORDER BY seq", plan_id)
    ids = [r["id"] for r in rows]
    parcels: dict[uuid.UUID, list[dict]] = {i: [] for i in ids}
    for p in await conn.fetch("SELECT sheet_id, parcel_urn, sigpac FROM sheet_parcels "
                              "WHERE sheet_id = ANY($1::uuid[]) ORDER BY sheet_id, ord", ids):
        parcels[p["sheet_id"]].append({"urn": p["parcel_urn"], "sigpac": p["sigpac"]})
    apps: dict[uuid.UUID, list[dict]] = {i: [] for i in ids}
    for a in await conn.fetch("SELECT sheet_id, data FROM applications "
                              "WHERE sheet_id = ANY($1::uuid[]) ORDER BY seq", ids):
        apps[a["sheet_id"]].append(a["data"])
    return [SheetRow(r["id"], r["key"], r["seq"], r["inputs"], r["overrides"], parcels[r["id"]],
                     apps[r["id"]]) for r in rows]


async def set_overrides(conn: asyncpg.Connection, sheet_id: uuid.UUID,
                        overrides: list[dict]) -> None:
    await conn.execute("UPDATE crop_sheets SET overrides = $2 WHERE id = $1", sheet_id, overrides)


async def save_results(conn: asyncpg.Connection, plan_id: uuid.UUID,
                       rows: list[tuple[uuid.UUID, dict, dict]], findings: list[dict]) -> None:
    await conn.execute("DELETE FROM results WHERE sheet_id IN "
                       "(SELECT id FROM crop_sheets WHERE plan_id = $1)", plan_id)
    await conn.executemany("INSERT INTO results (sheet_id, result, applications_summary) "
                           "VALUES ($1, $2, $3)", rows)
    await conn.execute("DELETE FROM findings WHERE plan_id = $1", plan_id)
    await conn.executemany(
        "INSERT INTO findings (plan_id, sheet_id, rule_id, severity, params) "
        "VALUES ($1, $2, $3, $4, $5)",
        [(plan_id, f.get("sheet_id"), f["rule_id"], f["severity"], f.get("params") or {})
         for f in findings])


async def get_results(conn: asyncpg.Connection, plan_id: uuid.UUID) -> dict[uuid.UUID, dict]:
    rows = await conn.fetch(
        "SELECT r.sheet_id, r.result, r.applications_summary, r.calculated_at FROM results r "
        "JOIN crop_sheets s ON s.id = r.sheet_id WHERE s.plan_id = $1", plan_id)
    return {r["sheet_id"]: {"result": r["result"], "applications_summary": r["applications_summary"],
                            "calculated_at": r["calculated_at"]} for r in rows}


async def get_findings(conn: asyncpg.Connection, plan_id: uuid.UUID) -> list[dict]:
    rows = await conn.fetch(
        "SELECT f.rule_id, f.severity, f.params, s.key AS sheet_key FROM findings f "
        "LEFT JOIN crop_sheets s ON s.id = f.sheet_id WHERE f.plan_id = $1 ORDER BY f.id",
        plan_id)
    return [dict(r) for r in rows]


async def append_audit(conn: asyncpg.Connection, plan_id: uuid.UUID, user_id: str, action: str,
                       detail: dict) -> None:
    await conn.execute("INSERT INTO audit_log (plan_id, user_id, action, detail) "
                       "VALUES ($1, $2, $3, $4)", plan_id, user_id, action, detail)


async def get_audit(conn: asyncpg.Connection, plan_id: uuid.UUID) -> list[dict]:
    rows = await conn.fetch("SELECT at, user_id, action, detail FROM audit_log "
                            "WHERE plan_id = $1 ORDER BY id", plan_id)
    return [dict(r) for r in rows]
