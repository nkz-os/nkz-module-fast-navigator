"""Numbered, idempotent SQL migrations applied at start-up under an advisory lock."""
from __future__ import annotations

import logging
from pathlib import Path

import asyncpg

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_LOCK_KEY = 0x46615354  # one replica migrates at a time


async def apply_migrations(conn: asyncpg.Connection) -> list[str]:
    """Apply, in order, the migrations not yet recorded; returns the names applied now.
    Each file is idempotent too, so a crash between running and recording is safe."""
    await conn.execute("SELECT pg_advisory_lock($1)", _LOCK_KEY)
    try:
        await conn.execute("CREATE SCHEMA IF NOT EXISTS fast")
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS fast.schema_migrations ("
            "name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
        done = {r["name"] for r in await conn.fetch("SELECT name FROM fast.schema_migrations")}
        applied = []
        for path in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")):
            if path.name in done:
                continue
            async with conn.transaction():
                await conn.execute(path.read_text(encoding="utf-8"))
                await conn.execute("INSERT INTO fast.schema_migrations (name) VALUES ($1) "
                                   "ON CONFLICT (name) DO NOTHING", path.name)
            applied.append(path.name)
        logger.info("migrations applied: %s", applied)
        return applied
    finally:
        await conn.execute("SELECT pg_advisory_unlock($1)", _LOCK_KEY)
