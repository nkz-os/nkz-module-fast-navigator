import json
import pathlib

CONTRACTS = pathlib.Path(__file__).parent / "fixtures" / "contracts"


def load_contract(name: str) -> dict:
    """A recorded response of a platform service (see fixtures/contracts)."""
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))
import asyncio

import asyncpg
import pytest

TRUNCATE_ALL = ("TRUNCATE fast.audit_log, fast.findings, fast.results, fast.applications, "
                "fast.sheet_parcels, fast.crop_sheets, fast.plans, fast.advisors, "
                "fast.holder_qualifications CASCADE")


async def _migrate(url: str) -> None:
    from app.db.migrate import apply_migrations

    conn = await asyncpg.connect(url)
    try:
        await apply_migrations(conn)
    finally:
        await conn.close()


async def _truncate(url: str) -> None:
    conn = await asyncpg.connect(url)
    try:
        await conn.execute(TRUNCATE_ALL)
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def pg_url():
    """A throwaway PostgreSQL 16 with the FaST migrations applied (needs Docker)."""
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine", driver=None) as pg:
        url = pg.get_connection_url()
        asyncio.run(_migrate(url))
        yield url


@pytest.fixture
async def pool(pg_url):
    from app.db.pool import create_pool

    p = await create_pool(pg_url)
    try:
        yield p
    finally:
        await p.close()
        await _truncate(pg_url)
