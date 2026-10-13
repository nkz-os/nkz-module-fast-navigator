"""The plan document: one shape for a signed plan's frozen copy and for a plan in progress."""
from __future__ import annotations

import asyncpg

from app.calc.sheet import CALC_VERSION
from app.engine import ENGINE_VERSION
from app.inputs.organic import ORGANIC_TABLE_VERSION
from app.plans import repo
from app.plans.applications import SPLIT_RULE_PREFIX
from app.plans.states import State
from app.rules.registry import RULES_VERSION


def _finding(row: dict) -> dict:
    params = dict(row["params"] or {})
    citation = params.pop("citation", None)
    return {"rule_id": row["rule_id"], "severity": row["severity"], "citation": citation,
            "params": params, "sheet_key": row["sheet_key"]}


async def plan_document(conn: asyncpg.Connection, plan: repo.PlanRow) -> dict:
    if plan.state in (State.SIGNED, State.SUPERSEDED) and plan.snapshot_sha256:
        snapshot = await repo.get_snapshot(conn, plan.id) or {}
        return {**snapshot, "state": plan.state,
                "signed_at": plan.signed_at.isoformat() if plan.signed_at else None,
                "snapshot_sha256": plan.snapshot_sha256, "live": False}
    sheets = await repo.get_sheets(conn, plan.id)
    results = await repo.get_results(conn, plan.id)
    rows = await repo.get_findings(conn, plan.id)
    return {
        "plan": {"id": str(plan.id), "campaign": plan.campaign, "farm": plan.farm,
                 "version": plan.version,
                 "supersedes": str(plan.supersedes) if plan.supersedes else None},
        "declarations": {"vulnerable_zone": plan.vulnerable_zone,
                         "vulnerable_zone_source": plan.vulnerable_zone_source,
                         "voluntary_digital_notebook": plan.voluntary_digital_notebook,
                         "irrigated_spring_2026": plan.irrigated_spring_2026},
        "rain": plan.rain,
        "sheets": [{"key": s.key, "inputs": s.inputs, "overrides": s.overrides,
                    "parcels": s.parcels, "applications": s.applications,
                    "n_adjustment": s.n_adjustment,
                    "result": (results.get(s.id) or {}).get("result"),
                    "applications_summary": (results.get(s.id) or {}).get("applications_summary")}
                   for s in sheets],
        "findings": [_finding(r) for r in rows if not r["rule_id"].startswith(SPLIT_RULE_PREFIX)],
        "split_findings": [r for r in rows if r["rule_id"].startswith(SPLIT_RULE_PREFIX)],
        "versions": {"engine": ENGINE_VERSION, "calc": CALC_VERSION, "rules": RULES_VERSION,
                     "organic_table": ORGANIC_TABLE_VERSION},
        "signature": None, "judged_at": None,
        "state": plan.state, "signed_at": None, "snapshot_sha256": None, "live": True,
    }
